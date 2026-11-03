"""
server.py - Backend Worker / Server abstraction for Python Load Balancer.

Implements concurrent worker threads that process tasks from thread-safe
task queues.
"""

from enum import Enum
import logging
import queue
import threading
import time
from typing import Callable, Optional

from task import Task, TaskStatus


class WorkerStatus(str, Enum):
    """Lifecycle states of a backend worker."""
    IDLE = "IDLE"
    BUSY = "BUSY"
    STOPPED = "STOPPED"


class Worker:
    """
    Backend worker running in an independent thread to execute assigned tasks.

    Each worker owns an isolated FIFO queue.Queue, continuously dequeues tasks,
    simulates realistic execution using the task's specified duration, and
    records real status and completion counts.
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
        self.status: WorkerStatus = WorkerStatus.IDLE

        self.on_task_started = on_task_started
        self.on_task_completed = on_task_completed

        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the worker thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
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
        Updates task state to QUEUED and associates assigned worker.
        """
        task.mark_queued(self.worker_id)
        self.task_queue.put(task)

    def _run(self) -> None:
        """Main execution loop running inside the worker thread."""
        while not self._stop_event.is_set():
            try:
                task = self.task_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            # Check for shutdown sentinel
            if task is None:
                self.task_queue.task_done()
                break

            # Begin task execution
            with self._lock:
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

            try:
                # Simulate task execution based on designated duration
                time.sleep(task.duration)
                with self._lock:
                    task.mark_completed(f"Executed by {self.worker_id}")
                    self.completed_task_count += 1
            except Exception as exc:
                with self._lock:
                    task.mark_failed(str(exc))
            finally:
                with self._lock:
                    self.current_task = None
                    if not self._stop_event.is_set():
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
            self.status = WorkerStatus.STOPPED

    def stop(self, wait: bool = True, timeout: Optional[float] = 5.0) -> None:
        """
        Gracefully stop the worker thread.
        Sets stop event, puts sentinel to unblock queue, and joins thread.
        """
        self._stop_event.set()
        self.task_queue.put(None)  # Sentinel to unblock get()
        if wait and self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        with self._lock:
            self.status = WorkerStatus.STOPPED

    def get_status_dict(self) -> dict:
        """Return a thread-safe snapshot of worker status."""
        with self._lock:
            return {
                "worker_id": self.worker_id,
                "status": self.status.value,
                "current_task_id": self.current_task.task_id if self.current_task else None,
                "current_task_name": self.current_task.name if self.current_task else None,
                "queue_size": self.task_queue.qsize(),
                "completed": self.completed_task_count,
            }

    def __repr__(self) -> str:
        return (
            f"<Worker id={self.worker_id} status={self.status.value} "
            f"queue={self.task_queue.qsize()} completed={self.completed_task_count}>"
        )

