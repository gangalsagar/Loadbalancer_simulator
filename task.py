"""
task.py - Task abstraction for Python Load Balancer.

Defines the Task dataclass, TaskStatus enumeration, and a thread-safe
task ID generator.
"""

from dataclasses import dataclass, field
from enum import Enum
import threading
import time
from typing import Optional


class TaskStatus(str, Enum):
    """Lifecycle states of a task."""
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


class TaskIdGenerator:
    """Thread-safe sequential task ID generator (e.g., T001, T002)."""

    def __init__(self, prefix: str = "T", start: int = 1) -> None:
        self._prefix = prefix
        self._counter = start
        self._lock = threading.Lock()

    def next_id(self) -> str:
        with self._lock:
            tid = f"{self._prefix}{self._counter:03d}"
            self._counter += 1
            return tid

    def reset(self, start: int = 1) -> None:
        with self._lock:
            self._counter = start


# Module-level default generator
_default_id_generator = TaskIdGenerator()


def generate_task_id() -> str:
    """Generate a unique sequential task ID."""
    return _default_id_generator.next_id()


def reset_task_id_generator(start: int = 1) -> None:
    """Reset the module-level task ID counter (primarily for testing)."""
    _default_id_generator.reset(start)


@dataclass
class Task:
    """
    Represents a discrete computational unit submitted to the load balancer.

    Attributes:
        task_id: Unique task identifier (e.g., 'T001').
        name: Human-readable task name or description.
        duration: Simulated processing duration in seconds.
        arrival_time: Epoch timestamp when task becomes available for scheduling.
        task_type: Classification of the task (e.g., 'CPU_TASK', 'IO_TASK').
        created_at: Epoch timestamp of task creation.
        started_at: Epoch timestamp when worker began processing.
        completed_at: Epoch timestamp when worker finished processing.
        assigned_worker: Identifier of the assigned backend worker.
        status: Current lifecycle state of the task.
        result: Outcome description upon successful completion.
        error: Error message if the task failed.
    """
    task_id: str = field(default_factory=generate_task_id)
    name: str = "Default Task"
    duration: float = 1.0
    arrival_time: float = field(default_factory=time.time)
    task_type: str = "CPU_TASK"
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    assigned_worker: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    scheduling_algorithm: Optional[str] = None
    workload_before_assignment: Optional[int] = None
    workload_after_assignment: Optional[int] = None
    interrupted_at: Optional[float] = None
    failure_reason: Optional[str] = None
    was_re_routed: bool = False
    original_worker: Optional[str] = None
    retry_count: int = 0

    @property
    def execution_time(self) -> Optional[float]:
        """Total execution duration in seconds, or None if not started."""
        if self.started_at is None:
            return None
        end_time = self.completed_at if self.completed_at is not None else time.time()
        return max(0.0, end_time - self.started_at)

    @property
    def waiting_time(self) -> float:
        """Time spent waiting in queue before execution started."""
        if self.started_at is None:
            return max(0.0, time.time() - self.created_at)
        return max(0.0, self.started_at - self.created_at)

    @property
    def turnaround_time(self) -> Optional[float]:
        """Total time from submission to completion, or None if incomplete."""
        if self.completed_at is None:
            return None
        return max(0.0, self.completed_at - self.created_at)

    def mark_queued(self, worker_id: str) -> None:
        """Mark the task as queued for a specific worker."""
        self.assigned_worker = worker_id
        self.status = TaskStatus.QUEUED

    def mark_running(self) -> None:
        """Mark the task as actively executing."""
        self.started_at = time.time()
        self.status = TaskStatus.RUNNING

    def mark_completed(self, result: Optional[str] = None) -> None:
        """Mark the task as successfully completed."""
        self.completed_at = time.time()
        self.status = TaskStatus.COMPLETED
        self.result = result or "Completed successfully"

    def mark_failed(self, error: str) -> None:
        """Mark the task as failed with an error message."""
        self.completed_at = time.time()
        self.status = TaskStatus.FAILED
        self.error = error

    def mark_interrupted(self, reason: str = "Worker failure") -> None:
        """Mark the task as interrupted due to worker failure."""
        self.completed_at = time.time()
        self.interrupted_at = self.completed_at
        self.status = TaskStatus.INTERRUPTED
        self.failure_reason = reason
        self.error = f"Interrupted: {reason}"

    def mark_re_routed(self, new_worker_id: str) -> None:
        """Mark the task as re-routed to a new worker after failure."""
        if self.original_worker is None and self.assigned_worker is not None:
            self.original_worker = self.assigned_worker
        self.assigned_worker = new_worker_id
        self.was_re_routed = True
        self.retry_count += 1
        self.status = TaskStatus.QUEUED

