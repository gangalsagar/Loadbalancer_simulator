"""
server.py - Backend Worker / Server abstraction for Python Load Balancer.

Implements concurrent worker threads that process tasks from thread-safe
task queues with realistic failure simulation, task interruption handling,
and thread-safe recovery (Phase 3).
"""

from enum import Enum
import logging
import queue
import threading
import time
from typing import Callable, List, Optional

from task import Task, TaskStatus


class WorkerStatus(str, Enum):
    """Lifecycle states of a backend worker."""
    IDLE = "IDLE"
    BUSY = "BUSY"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


class Worker:
    """
    Backend worker running in an independent thread to execute assigned tasks.

    Each worker owns an isolated FIFO queue.Queue, continuously dequeues tasks,
    simulates realistic execution using the task's specified duration, and
    records real status, failure counts, and recovery metrics.

    Phase 3 enhancements:
    - Distinct FAILED vs. STOPPED states.
    - Controlled failure simulation interrupting active task processing.
    - Atomically drain queued tasks for recovery/re-routing.
    - Safe restart of worker thread upon recovery without duplicate threads.
    """

    def __init__(
        self,
        worker_id: str,
        logger: Optional[logging.Logger] = None,
        on_task_started: Optional[Callable[["Worker", Task], None]] = None,
        on_task_completed: Optional[Callable[["Worker", Task], None]] = None,
    ) -> None:
        self.worker_id = worker_id
        self.logger = logger
        self.task_queue: "queue.Queue[Optional[Task]]" = queue.Queue()
        self.current_task: Optional[Task] = None
        self.completed_task_count: int = 0
        self.failed_task_count: int = 0
        self.interrupted_task_count: int = 0
        self.assigned_task_count: int = 0
        self.failure_count: int = 0
        self.recovery_count: int = 0
        self.total_execution_time: float = 0.0
        self.status: WorkerStatus = WorkerStatus.IDLE

        self.on_task_started = on_task_started
        self.on_task_completed = on_task_completed

        self._stop_event = threading.Event()
        self._fail_event = threading.Event()
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the worker thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._fail_event.clear()
            self.status = WorkerStatus.IDLE
            self._thread = threading.Thread(
                target=self._run,
                name=f"Thread-{self.worker_id}",
                daemon=True,
            )
            self._thread.start()

    def add_task(self, task: Task) -> None:
        """
        Assign and enqueue a task to this worker.
        Rejects tasks if worker is FAILED or STOPPED.
        """
        with self._lock:
            if not self.is_available:
                raise RuntimeError(
                    f"Cannot assign task {task.task_id} to {self.worker_id}: "
                    f"worker is in {self.status.value} state."
                )
            self.assigned_task_count += 1
            task.mark_queued(self.worker_id)
            self.task_queue.put(task)

    def _run(self) -> None:
        """Main execution loop running inside the worker thread."""
        while not self._stop_event.is_set() and not self._fail_event.is_set():
            try:
                task = self.task_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            # Check for shutdown sentinel
            if task is None:
                self.task_queue.task_done()
                break

            # Verify worker has not failed before beginning task
            with self._lock:
                if self._fail_event.is_set() or self.status == WorkerStatus.FAILED:
                    # Put task back so it can be drained/re-routed
                    self.task_queue.put(task)
                    self.task_queue.task_done()
                    break

                self.status = WorkerStatus.BUSY
                self.current_task = task
                task.mark_running()

            if self.logger:
                self.logger.info(f"{self.worker_id} started Task {task.task_id}")
            if self.on_task_started:
                try:
                    self.on_task_started(self, task)
                except Exception:
                    pass

            # Interruptible execution: waits on _fail_event.
            # If fail() is triggered, wait() returns True immediately.
            interrupted = self._fail_event.wait(timeout=task.duration)

            if interrupted:
                # Worker failed during active task execution
                with self._lock:
                    task.mark_interrupted(f"Worker {self.worker_id} experienced failure")
                    self.interrupted_task_count += 1
                    self.failed_task_count += 1
                    self.current_task = None
                    self.status = WorkerStatus.FAILED

                self.task_queue.task_done()
                if self.logger:
                    self.logger.warning(
                        f"{self.worker_id} FAILED during execution of Task {task.task_id}. "
                        f"Task marked INTERRUPTED."
                    )
                break

            # Normal task completion
            try:
                with self._lock:
                    task.mark_completed(f"Executed by {self.worker_id}")
                    self.completed_task_count += 1
                    if task.execution_time is not None:
                        self.total_execution_time += task.execution_time
                    else:
                        self.total_execution_time += task.duration
            except Exception as exc:
                with self._lock:
                    task.mark_failed(str(exc))
                    self.failed_task_count += 1
            finally:
                with self._lock:
                    self.current_task = None
                    if not self._stop_event.is_set() and not self._fail_event.is_set():
                        self.status = WorkerStatus.IDLE
                self.task_queue.task_done()

                if self.logger:
                    self.logger.info(f"{self.worker_id} completed Task {task.task_id}")
                if self.on_task_completed:
                    try:
                        self.on_task_completed(self, task)
                    except Exception:
                        pass

        with self._lock:
            if self._fail_event.is_set():
                self.status = WorkerStatus.FAILED
            elif self._stop_event.is_set():
                self.status = WorkerStatus.STOPPED

    def fail(self) -> None:
        """
        Simulate an unexpected worker failure.
        Marks worker as FAILED, signals interruption to active thread,
        and disables accepting new tasks.
        """
        with self._lock:
            if self.status == WorkerStatus.FAILED:
                return
            self.status = WorkerStatus.FAILED
            self.failure_count += 1
            self._fail_event.set()

        if self.logger:
            self.logger.warning(f"Simulating FAILURE on {self.worker_id}")

    def drain_queued_tasks(self) -> List[Task]:
        """
        Atomically drain all unexecuted tasks waiting in this worker's queue.
        Drained tasks can be safely re-routed by the load balancer.

        Returns:
            List of unstarted Task instances drained from the queue.
        """
        drained: List[Task] = []
        with self._lock:
            while True:
                try:
                    task = self.task_queue.get_nowait()
                    if task is not None:
                        drained.append(task)
                    self.task_queue.task_done()
                except queue.Empty:
                    break
        return drained

    def recover(self) -> None:
        """
        Recover a failed worker.
        Safely ensures any previous thread has finished, clears failure flags,
        increments recovery count, starts a fresh thread, and restores IDLE state.
        """
        with self._lock:
            if self.status != WorkerStatus.FAILED and not self._fail_event.is_set():
                raise RuntimeError(
                    f"Cannot recover {self.worker_id}: worker is not in FAILED state (current: {self.status.value})."
                )

        # Wait for old thread to exit cleanly before instantiating a new thread
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3.0)

        with self._lock:
            self._fail_event.clear()
            self._stop_event.clear()
            self.current_task = None
            self.recovery_count += 1
            self.status = WorkerStatus.IDLE

            # Start fresh worker thread
            self._thread = threading.Thread(
                target=self._run,
                name=f"Thread-{self.worker_id}",
                daemon=True,
            )
            self._thread.start()

        if self.logger:
            self.logger.info(f"{self.worker_id} has been RECOVERED and is now IDLE.")

    def stop(self, wait: bool = True, timeout: Optional[float] = 5.0) -> None:
        """
        Gracefully stop the worker thread as part of normal shutdown.
        Sets stop event, puts sentinel to unblock queue, and joins thread.
        """
        self._stop_event.set()
        self.task_queue.put(None)  # Sentinel to unblock get()
        if wait and self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        with self._lock:
            self.status = WorkerStatus.STOPPED

    def get_workload(self) -> int:
        """
        Calculate the current workload of this worker.

        Workload is defined as:
            current workload = (1 if currently executing a task else 0) + queued tasks

        Returns:
            Non-negative integer representing the active workload.
        """
        with self._lock:
            executing = 1 if self.current_task is not None else 0
            return executing + self.task_queue.qsize()

    @property
    def is_available(self) -> bool:
        """Whether the worker is active, healthy, and accepting tasks."""
        with self._lock:
            return (
                not self._stop_event.is_set()
                and not self._fail_event.is_set()
                and self.status not in (WorkerStatus.STOPPED, WorkerStatus.FAILED)
            )

    def get_queue_snapshot(self) -> List[dict]:
        """
        Return a thread-safe snapshot of queued tasks.

        Returns:
            List of dictionaries containing task_id, name, and duration for each queued task.
        """
        with self._lock:
            snapshot = []
            temp_queue = []
            # Drain queue temporarily to read all tasks
            while True:
                try:
                    task = self.task_queue.get_nowait()
                    if task is not None:
                        snapshot.append({
                            "task_id": task.task_id,
                            "name": task.name,
                            "duration": task.duration,
                        })
                        temp_queue.append(task)
                    self.task_queue.task_done()
                except queue.Empty:
                    break
            # Put tasks back in the same order
            for task in temp_queue:
                self.task_queue.put(task)
            return snapshot

    def get_status_dict(self) -> dict:
        """Return a thread-safe snapshot of worker status."""
        with self._lock:
            executing = 1 if self.current_task is not None else 0
            queue_size = self.task_queue.qsize()
            workload = executing + queue_size
            avg_exec = (
                self.total_execution_time / self.completed_task_count
                if self.completed_task_count > 0
                else 0.0
            )
            # Thread state representation
            thread_alive = self._thread is not None and self._thread.is_alive()
            if self.status == WorkerStatus.FAILED:
                thread_state = "FAILED"
            elif self.status == WorkerStatus.STOPPED:
                thread_state = "STOPPED"
            elif self.current_task is not None:
                thread_state = "RUNNING"
            elif queue_size > 0:
                thread_state = "WAITING"
            else:
                thread_state = "IDLE"

            return {
                "worker_id": self.worker_id,
                "status": self.status.value,
                "current_task_id": self.current_task.task_id if self.current_task else None,
                "current_task_name": self.current_task.name if self.current_task else None,
                "queue_size": queue_size,
                "workload": workload,
                "completed": self.completed_task_count,
                "failed": self.failed_task_count,
                "interrupted": self.interrupted_task_count,
                "assigned": self.assigned_task_count,
                "failures": self.failure_count,
                "recoveries": self.recovery_count,
                "available": self.is_available,
                "total_execution_time": self.total_execution_time,
                "avg_execution_time": avg_exec,
                "thread_alive": thread_alive,
                "thread_state": thread_state,
            }

    def __repr__(self) -> str:
        return (
            f"<Worker id={self.worker_id} status={self.status.value} "
            f"available={self.is_available} queue={self.task_queue.qsize()} "
            f"completed={self.completed_task_count} failures={self.failure_count}>"
        )
