"""
scheduler.py - Scheduling algorithms for Python Load Balancer.

Implements the Round Robin scheduling algorithm for Phase 1.
"""

from abc import ABC, abstractmethod
import threading
from typing import List, Sequence

from server import Worker


class BaseScheduler(ABC):
    """Abstract base class for load balancing schedulers."""

    @abstractmethod
    def select_worker(self, workers: Sequence[Worker]) -> Worker:
        """Select a worker from the available workers pool."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset internal scheduler state."""
        pass


class RoundRobinScheduler(BaseScheduler):
    """
    Round Robin scheduling algorithm.

    Cycles sequentially through the available backend workers:
    Worker-1 -> Worker-2 -> Worker-3 -> Worker-1 -> Worker-2 ...

    Thread-safe to ensure race-free worker selection under concurrent submissions.
    """

    def __init__(self) -> None:
        self._index: int = 0
        self._lock: threading.Lock = threading.Lock()

    def select_worker(self, workers: Sequence[Worker]) -> Worker:
        """
        Select the next worker using Round Robin order.

        Args:
            workers: Non-empty sequence of backend workers.

        Returns:
            The selected Worker instance.

        Raises:
            ValueError: If the workers sequence is empty.
        """
        if not workers:
            raise ValueError("Cannot schedule task: workers list is empty.")

        with self._lock:
            selected_worker = workers[self._index % len(workers)]
            self._index = (self._index + 1) % len(workers)
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

