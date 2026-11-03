"""
scheduler.py - Scheduling algorithms for Python Load Balancer.

Implements load balancing algorithms:
- Round Robin (Phase 1)
- Least Connections / Least Workload (Phase 2)
Both schedulers feature fault-tolerant worker selection that skips failed
or stopped backend workers (Phase 3).
"""

from abc import ABC, abstractmethod
import threading
from typing import Sequence

from server import Worker


class BaseScheduler(ABC):
    """Abstract base class for load balancing schedulers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable algorithm name."""
        pass

    @abstractmethod
    def select_worker(self, workers: Sequence[Worker]) -> Worker:
        """Select an available, healthy worker from the workers pool."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset internal scheduler state."""
        pass


class RoundRobinScheduler(BaseScheduler):
    """
    Round Robin scheduling algorithm.

    Cycles sequentially through the available, healthy backend workers:
    Worker-1 -> Worker-2 -> Worker-3 -> Worker-1 -> Worker-2 ...

    Fault-tolerant: Automatically excludes workers in FAILED or STOPPED states.
    Thread-safe to ensure race-free worker selection under concurrent submissions.
    """

    def __init__(self) -> None:
        self._index: int = 0
        self._lock: threading.Lock = threading.Lock()

    @property
    def name(self) -> str:
        return "Round Robin"

    def select_worker(self, workers: Sequence[Worker]) -> Worker:
        """
        Select the next healthy worker using Round Robin order.

        Args:
            workers: Non-empty sequence of backend workers.

        Returns:
            The selected Worker instance.

        Raises:
            ValueError: If the workers sequence is empty.
            RuntimeError: If all workers are in FAILED or STOPPED state.
        """
        if not workers:
            raise ValueError("Cannot schedule task: workers list is empty.")

        with self._lock:
            # Fault tolerance: filter strictly for active, healthy workers
            available = [w for w in workers if w.is_available]
            if not available:
                raise RuntimeError(
                    "Cannot schedule task: no available workers (all workers are FAILED or STOPPED)."
                )

            selected_worker = available[self._index % len(available)]
            self._index = (self._index + 1) % len(available)
            return selected_worker

    def reset(self) -> None:
        """Reset the pointer back to the first worker."""
        with self._lock:
            self._index = 0

    @property
    def current_index(self) -> int:
        """Return the current scheduler index."""
        with self._lock:
            return self._index


class LeastConnectionsScheduler(BaseScheduler):
    """
    Least Connections / Least Workload scheduling algorithm.

    Assigns incoming tasks to the healthy worker with the lowest active workload:
        current workload = (1 if currently executing a task else 0) + queued tasks

    Fault-tolerant: Automatically excludes workers in FAILED or STOPPED states.

    Tie-Breaking:
        When multiple available workers share the same minimum workload,
        deterministic tie-breaking selects the first healthy worker encountered
        in the sequence.

    Thread-safe to ensure consistent workload evaluation under concurrent submissions.
    """

    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()

    @property
    def name(self) -> str:
        return "Least Connections"

    def select_worker(self, workers: Sequence[Worker]) -> Worker:
        """
        Select the healthy worker with the minimum active workload.

        Args:
            workers: Non-empty sequence of backend workers.

        Returns:
            The selected Worker instance.

        Raises:
            ValueError: If the workers sequence is empty.
            RuntimeError: If all workers are in FAILED or STOPPED state.
        """
        if not workers:
            raise ValueError("Cannot schedule task: workers list is empty.")

        with self._lock:
            available = [w for w in workers if w.is_available]
            if not available:
                raise RuntimeError(
                    "Cannot schedule task: no available workers (all workers are FAILED or STOPPED)."
                )

            # Python min() is stable: in case of equal workloads,
            # the first minimum encountered in available sequence is selected.
            selected_worker = min(available, key=lambda w: w.get_workload())
            return selected_worker

    def reset(self) -> None:
        """Reset internal state (no-op for stateless Least Connections)."""
        pass


def create_scheduler(name_or_alias: str) -> BaseScheduler:
    """
    Factory function to instantiate a scheduler by name or alias.

    Args:
        name_or_alias: Algorithm identifier (e.g., 'round_robin', 'least_connections',
                       'rr', 'lc', '1', '2').

    Returns:
        An instance of BaseScheduler.

    Raises:
        ValueError: If the identifier is unrecognised.
    """
    cleaned = name_or_alias.strip().lower().replace("-", "_").replace(" ", "_")
    if cleaned in ("1", "round_robin", "rr", "roundrobin"):
        return RoundRobinScheduler()
    elif cleaned in ("2", "least_connections", "lc", "leastconnections", "least_workload"):
        return LeastConnectionsScheduler()
    else:
        raise ValueError(
            f"Unknown scheduler algorithm: '{name_or_alias}'. "
            "Supported algorithms: 'round_robin', 'least_connections'."
        )
