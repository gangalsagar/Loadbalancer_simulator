"""
load_balancer.py - Core Load Balancer component.

Coordinates task submission, scheduling algorithms (Round Robin, Least Connections),
backend worker management, task tracking, metrics collection, and fault tolerance
including worker failure simulation, task recovery, and worker restoration (Phase 3).
"""

from collections import OrderedDict
import logging
import threading
import time
from typing import Dict, List, Optional, Sequence, Tuple

from scheduler import BaseScheduler, RoundRobinScheduler, create_scheduler
from server import Worker, WorkerStatus
from task import Task, TaskStatus


def setup_logger(name: str = "LoadBalancer", level: int = logging.INFO) -> logging.Logger:
    """Configure a clean, timestamped console logger."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            fmt="[%(asctime)s] %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.propagate = False
    return logger


class LoadBalancer:
    """
    Central load balancer managing workers, scheduling, task lifecycle,
    and fault tolerance.

    Responsibilities:
    - Initialize and maintain backend workers.
    - Employ scheduling policy (Round Robin or Least Connections).
    - Ingest tasks and assign them to healthy workers.
    - Track all tasks and collect operational metrics.
    - Allow safe dynamic switching between scheduling algorithms.
    - Simulate worker failures, interrupt active tasks, and drain/re-route queued tasks.
    - Recover failed workers and safely resume task assignments.
    - Gracefully shut down worker threads.
    """

    def __init__(
        self,
        worker_count: int = 3,
        worker_names: Optional[Sequence[str]] = None,
        scheduler: Optional[BaseScheduler] = None,
        logger: Optional[logging.Logger] = None,
        auto_start: bool = True,
    ) -> None:
        """
        Initialize the Load Balancer.

        Args:
            worker_count: Number of backend workers to instantiate (default 3).
            worker_names: Optional custom list of worker IDs.
            scheduler: Scheduling strategy instance (default: RoundRobinScheduler).
            logger: Custom logger instance or None for default.
            auto_start: Whether to automatically start worker threads upon init.
        """
        self.logger = logger if logger is not None else setup_logger()
        self.scheduler: BaseScheduler = scheduler if scheduler is not None else RoundRobinScheduler()
        self._start_time: float = time.time()

        # Initialize workers
        if worker_names:
            names = list(worker_names)
        else:
            names = [f"Worker-{i + 1}" for i in range(worker_count)]

        self.workers: List[Worker] = [
            Worker(worker_id=name, logger=self.logger) for name in names
        ]

        # Fault tolerance metrics and tracking
        self.total_worker_failures: int = 0
        self.total_worker_recoveries: int = 0
        self.total_re_routed: int = 0
        self._backlogged_tasks: List[Task] = []

        # Thread-safe task repository (preserves insertion order)
        self._tasks: "OrderedDict[str, Task]" = OrderedDict()
        self._lock = threading.RLock()
        self._is_shutdown = False

        if auto_start:
            self.start()

    @property
    def scheduler_name(self) -> str:
        """Name of the currently active scheduling algorithm."""
        with self._lock:
            return self.scheduler.name

    def set_scheduler(self, scheduler: BaseScheduler) -> None:
        """
        Switch the active scheduling strategy safely.

        Args:
            scheduler: An instance implementing BaseScheduler.
        """
        with self._lock:
            old_name = self.scheduler.name
            self.scheduler = scheduler
            new_name = self.scheduler.name
        if self.logger:
            self.logger.info(f"Scheduling algorithm switched: {old_name} -> {new_name}")

    def set_algorithm(self, name_or_alias: str) -> BaseScheduler:
        """
        Switch the active scheduling strategy by name or alias.

        Args:
            name_or_alias: 'round_robin', 'least_connections', 'rr', 'lc', '1', '2'.

        Returns:
            The newly activated BaseScheduler instance.
        """
        new_scheduler = create_scheduler(name_or_alias)
        self.set_scheduler(new_scheduler)
        return new_scheduler

    def start(self) -> None:
        """Start all backend worker threads."""
        for worker in self.workers:
            worker.start()

    def get_worker_by_id(self, worker_id: str) -> Optional[Worker]:
        """Find a worker instance by its ID."""
        for w in self.workers:
            if w.worker_id == worker_id:
                return w
        return None

    def get_available_workers(self) -> List[Worker]:
        """Return list of workers currently active, healthy, and accepting tasks."""
        return [w for w in self.workers if w.is_available]

    def get_failed_workers(self) -> List[Worker]:
        """Return list of workers currently in FAILED state."""
        return [w for w in self.workers if w.status == WorkerStatus.FAILED]

    def submit_task(self, task: Task) -> Task:
        """
        Accept, record, schedule, and assign a task to a healthy backend worker.

        Args:
            task: Task instance to schedule.

        Returns:
            The submitted Task instance with updated status, assigned worker,
            and scheduling decision metadata.

        Raises:
            RuntimeError: If the load balancer is shut down, or if all workers are failed.
        """
        if self._is_shutdown:
            raise RuntimeError("Cannot submit task: Load Balancer is shut down.")

        with self._lock:
            self._tasks[task.task_id] = task
            active_scheduler = self.scheduler

        if self.logger:
            self.logger.info(f"Task {task.task_id} created")

        # Select target worker via active scheduler with race-condition retry
        max_attempts = max(1, len(self.workers))
        for _ in range(max_attempts):
            selected_worker = active_scheduler.select_worker(self.workers)
            workload_before = selected_worker.get_workload()

            try:
                # Enqueue to selected worker
                selected_worker.add_task(task)
                break
            except RuntimeError:
                # Worker failed during the window between selection and enqueue; retry with another worker
                continue
        else:
            raise RuntimeError("Cannot schedule task: all available workers became unavailable.")

        workload_after = selected_worker.get_workload()

        # Record scheduling metadata on task
        task.scheduling_algorithm = active_scheduler.name
        task.workload_before_assignment = workload_before
        task.workload_after_assignment = workload_after

        if self.logger:
            if active_scheduler.name == "Least Connections":
                self.logger.info(
                    f"Task {task.task_id} assigned to {selected_worker.worker_id} "
                    f"(Algorithm: Least Connections, Workload: {workload_before} -> {workload_after})"
                )
            else:
                self.logger.info(
                    f"Task {task.task_id} assigned to {selected_worker.worker_id} "
                    f"(Algorithm: Round Robin)"
                )

        return task

    def create_and_submit_task(
        self,
        name: str,
        duration: float,
        task_type: str = "CPU_TASK",
        arrival_time: Optional[float] = None,
    ) -> Task:
        """Helper to create and submit a task in one call."""
        if arrival_time is None:
            arrival_time = time.time()
        task = Task(name=name, duration=duration, task_type=task_type, arrival_time=arrival_time)
        return self.submit_task(task)

    def _re_route_task(self, task: Task) -> None:
        """Internal helper to assign a recovered task to a healthy available worker."""
        with self._lock:
            active_scheduler = self.scheduler

        selected_worker = active_scheduler.select_worker(self.workers)
        workload_before = selected_worker.get_workload()
        task.mark_re_routed(selected_worker.worker_id)
        selected_worker.add_task(task)
        workload_after = selected_worker.get_workload()

        task.scheduling_algorithm = active_scheduler.name
        task.workload_before_assignment = workload_before
        task.workload_after_assignment = workload_after

        if self.logger:
            self.logger.info(
                f"Task {task.task_id} re-routed to {selected_worker.worker_id} "
                f"(previously queued on {task.original_worker})"
            )

    def simulate_worker_failure(self, worker_id: str) -> Worker:
        """
        Simulate an unexpected failure of a backend worker.

        1. Transitions the worker to FAILED state.
        2. Signals interruption to any actively executing task (marking it INTERRUPTED).
        3. Atomically drains all unexecuted queued tasks from the failed worker.
        4. Re-routes recovered tasks to healthy available workers via the active scheduler.

        Args:
            worker_id: The ID of the worker to fail (e.g., 'Worker-2').

        Returns:
            The failed Worker instance.

        Raises:
            ValueError: If worker_id does not exist.
        """
        worker = self.get_worker_by_id(worker_id)
        if worker is None:
            raise ValueError(f"Worker '{worker_id}' does not exist.")

        with self._lock:
            if worker.status == WorkerStatus.FAILED:
                return worker
            self.total_worker_failures += 1

        # Trigger worker failure (signals interrupt to executing thread)
        worker.fail()

        # Drain queued tasks from the failed worker
        drained_tasks = worker.drain_queued_tasks()

        # Re-route drained tasks to healthy workers
        for t in drained_tasks:
            with self._lock:
                self.total_re_routed += 1
            try:
                self._re_route_task(t)
            except RuntimeError:
                # No healthy workers available right now; store in backlog until recovery
                with self._lock:
                    t.status = TaskStatus.PENDING
                    self._backlogged_tasks.append(t)

        if self.logger:
            self.logger.warning(
                f"Worker {worker_id} FAILED. Recovered and re-routed {len(drained_tasks)} queued tasks."
            )

        return worker

    def recover_worker(self, worker_id: str) -> Worker:
        """
        Restore a failed worker to healthy IDLE operation.

        1. Restores the worker to IDLE state.
        2. Starts a fresh worker thread safely.
        3. Re-enables worker for scheduler selection.
        4. Dispatches any backlogged tasks that were waiting for an available worker.

        Args:
            worker_id: The ID of the worker to restore.

        Returns:
            The recovered Worker instance.

        Raises:
            ValueError: If worker_id is invalid.
            RuntimeError: If worker is not in FAILED state.
        """
        worker = self.get_worker_by_id(worker_id)
        if worker is None:
            raise ValueError(f"Worker '{worker_id}' does not exist.")

        with self._lock:
            if worker.status != WorkerStatus.FAILED:
                raise RuntimeError(
                    f"Cannot recover {worker_id}: worker is in {worker.status.value} state, not FAILED."
                )
            self.total_worker_recoveries += 1

        worker.recover()

        # Dispatch backlogged tasks if any exist
        with self._lock:
            backlog = list(self._backlogged_tasks)
            self._backlogged_tasks.clear()

        for t in backlog:
            try:
                self._re_route_task(t)
            except RuntimeError:
                with self._lock:
                    self._backlogged_tasks.append(t)
                break

        if self.logger:
            self.logger.info(f"Worker {worker_id} RECOVERED and is now accepting tasks.")

        return worker

    def recover_tasks_from_worker(self, worker_id: str) -> List[Task]:
        """Drain and return queued tasks from a worker."""
        worker = self.get_worker_by_id(worker_id)
        if worker is None:
            raise ValueError(f"Worker '{worker_id}' does not exist.")
        return worker.drain_queued_tasks()

    def get_task(self, task_id: str) -> Optional[Task]:
        """Look up a task by its unique ID."""
        with self._lock:
            return self._tasks.get(task_id)

    def get_all_tasks(self) -> List[Task]:
        """Return a snapshot of all submitted tasks."""
        with self._lock:
            return list(self._tasks.values())

    def get_worker_status(self) -> List[dict]:
        """Return status dictionaries for all registered workers."""
        return [w.get_status_dict() for w in self.workers]

    def get_worker_queues(self) -> dict:
        """Return queue snapshots for all workers."""
        return {w.worker_id: w.get_queue_snapshot() for w in self.workers}

    def get_metrics(self) -> dict:
        """
        Collect real-time operational metrics across workers and tasks.

        Returns:
            Dictionary containing global task metrics, timing averages,
            fault tolerance counts, and detailed per-worker metrics.
        """
        tasks = self.get_all_tasks()
        worker_statuses = self.get_worker_status()

        total_submitted = len(tasks)
        completed_tasks = [t for t in tasks if t.status == TaskStatus.COMPLETED]
        total_completed = len(completed_tasks)
        total_running = sum(1 for t in tasks if t.status == TaskStatus.RUNNING)
        total_queued = sum(1 for t in tasks if t.status == TaskStatus.QUEUED)
        total_failed = sum(1 for t in tasks if t.status == TaskStatus.FAILED)
        total_interrupted = sum(1 for t in tasks if t.status == TaskStatus.INTERRUPTED)

        total_exec_time = sum(
            (t.execution_time if t.execution_time is not None else t.duration)
            for t in completed_tasks
        )
        avg_exec_time = (
            total_exec_time / total_completed if total_completed > 0 else 0.0
        )

        total_waiting_time = sum(t.waiting_time for t in completed_tasks)
        avg_waiting_time = (
            total_waiting_time / total_completed if total_completed > 0 else 0.0
        )

        elapsed_time = max(0.001, time.time() - self._start_time)
        throughput = total_completed / elapsed_time

        worker_completed = {
            ws["worker_id"]: ws["completed"] for ws in worker_statuses
        }
        worker_workload = {
            ws["worker_id"]: ws["workload"] for ws in worker_statuses
        }
        worker_assigned = {
            ws["worker_id"]: ws["assigned"] for ws in worker_statuses
        }
        worker_failures = {
            ws["worker_id"]: ws.get("failures", 0) for ws in worker_statuses
        }
        worker_recoveries = {
            ws["worker_id"]: ws.get("recoveries", 0) for ws in worker_statuses
        }
        worker_states = {
            ws["worker_id"]: ws["status"] for ws in worker_statuses
        }
        worker_available = {
            ws["worker_id"]: ws.get("available", True) for ws in worker_statuses
        }

        return {
            "total_submitted": total_submitted,
            "total_completed": total_completed,
            "total_running": total_running,
            "total_queued": total_queued,
            "total_failed": total_failed,
            "total_interrupted": total_interrupted,
            "total_re_routed": self.total_re_routed,
            "total_worker_failures": self.total_worker_failures,
            "total_worker_recoveries": self.total_worker_recoveries,
            "available_worker_count": len(self.get_available_workers()),
            "failed_worker_count": len(self.get_failed_workers()),
            "scheduler_name": self.scheduler.name,
            "total_execution_time": total_exec_time,
            "avg_execution_time": avg_exec_time,
            "avg_waiting_time": avg_waiting_time,
            "throughput": throughput,
            "elapsed_time": elapsed_time,
            "worker_completed": worker_completed,
            "worker_workload": worker_workload,
            "worker_assigned": worker_assigned,
            "worker_failures": worker_failures,
            "worker_recoveries": worker_recoveries,
            "worker_states": worker_states,
            "worker_available": worker_available,
            "worker_count": len(self.workers),
            "worker_statuses": worker_statuses,
        }

    def wait_for_completion(self, timeout: Optional[float] = 10.0) -> bool:
        """
        Wait until all queued tasks are processed and workers settle.

        Args:
            timeout: Maximum seconds to wait (None for indefinite).

        Returns:
            True if all tasks finished within timeout, False otherwise.
        """
        start = time.time()
        for worker in self.workers:
            if worker.is_available:
                worker.task_queue.join()

        deadline = (time.time() + timeout) if timeout else None
        while deadline is None or time.time() < deadline:
            with self._lock:
                all_settled = all(
                    w.status in (WorkerStatus.IDLE, WorkerStatus.FAILED, WorkerStatus.STOPPED)
                    for w in self.workers
                )
                all_done = (
                    sum(
                        1
                        for t in self._tasks.values()
                        if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.INTERRUPTED)
                    )
                    == len(self._tasks)
                )
            if all_settled and all_done:
                return True
            time.sleep(0.02)
        return False

    def shutdown(self, wait: bool = True, timeout: Optional[float] = 5.0) -> None:
        """
        Gracefully stop all backend workers and shut down the load balancer.
        """
        self._is_shutdown = True
        for worker in self.workers:
            worker.stop(wait=wait, timeout=timeout)
