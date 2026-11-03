"""
load_balancer.py - Core Load Balancer component.

Coordinates task submission, Round Robin scheduling, backend worker
management, task tracking, and basic metrics collection.
"""

from collections import OrderedDict
import logging
import threading
from typing import Dict, List, Optional, Sequence

from scheduler import BaseScheduler, RoundRobinScheduler
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
    Central load balancer managing workers, scheduling, and task lifecycle.

    Responsibilities:
    - Initialize and maintain backend workers.
    - Employ scheduling policy (Round Robin in Phase 1).
    - Ingest tasks and assign them to workers.
    - Track all tasks and collect operational metrics.
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

        # Initialize workers
        if worker_names:
            names = list(worker_names)
        else:
            names = [f"Worker-{i + 1}" for i in range(worker_count)]

        self.workers: List[Worker] = [
            Worker(worker_id=name, logger=self.logger) for name in names
        ]

        # Thread-safe task repository (preserves insertion order)
        self._tasks: "OrderedDict[str, Task]" = OrderedDict()
        self._lock = threading.Lock()
        self._is_shutdown = False

        if auto_start:
            self.start()

    def start(self) -> None:
        """Start all backend worker threads."""
        for worker in self.workers:
            worker.start()

    def submit_task(self, task: Task) -> Task:
        """
        Accept, record, schedule, and assign a task to a backend worker.

        Args:
            task: Task instance to schedule.

        Returns:
            The submitted Task instance with updated status and assigned worker.

        Raises:
            RuntimeError: If the load balancer has already been shut down.
        """
        if self._is_shutdown:
            raise RuntimeError("Cannot submit task: Load Balancer is shut down.")

        with self._lock:
            self._tasks[task.task_id] = task

        if self.logger:
            self.logger.info(f"Task {task.task_id} created")

        # Select target worker via scheduler
        selected_worker = self.scheduler.select_worker(self.workers)

        # Enqueue to worker
        selected_worker.add_task(task)

        if self.logger:
            self.logger.info(f"Task {task.task_id} assigned to {selected_worker.worker_id}")

        return task

    def create_and_submit_task(
        self,
        name: str,
        duration: float,
        task_type: str = "CPU_TASK",
    ) -> Task:
        """Helper to create and submit a task in one call."""
        task = Task(name=name, duration=duration, task_type=task_type)
        return self.submit_task(task)

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

    def get_metrics(self) -> dict:
        """
        Collect real-time operational metrics across workers and tasks.

        Returns:
            Dictionary containing task counts, worker status counts, and
            individual worker completion counts.
        """
        tasks = self.get_all_tasks()
        worker_statuses = self.get_worker_status()

        total_submitted = len(tasks)
        total_completed = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)
        total_running = sum(1 for t in tasks if t.status == TaskStatus.RUNNING)
        total_queued = sum(1 for t in tasks if t.status == TaskStatus.QUEUED)
        total_failed = sum(1 for t in tasks if t.status == TaskStatus.FAILED)

        worker_completed = {
            ws["worker_id"]: ws["completed"] for ws in worker_statuses
        }

        return {
            "total_submitted": total_submitted,
            "total_completed": total_completed,
            "total_running": total_running,
            "total_queued": total_queued,
            "total_failed": total_failed,
            "worker_completed": worker_completed,
            "worker_count": len(self.workers),
        }

    def shutdown(self, wait: bool = True, timeout: Optional[float] = 5.0) -> None:
        """
        Gracefully stop all backend workers and shut down the load balancer.
        """
        self._is_shutdown = True
        for worker in self.workers:
            worker.stop(wait=wait, timeout=timeout)

