"""
Unit tests for Scheduler component (Round Robin).
"""

import unittest

from scheduler import RoundRobinScheduler
from server import Worker


class TestRoundRobinScheduler(unittest.TestCase):
    def setUp(self) -> None:
        self.scheduler = RoundRobinScheduler()
        self.workers = [
            Worker("Worker-1"),
            Worker("Worker-2"),
            Worker("Worker-3"),
        ]

    def test_round_robin_sequence(self) -> None:
        """
        Explicitly verify Round Robin cycle:
        T1 -> Worker-1
        T2 -> Worker-2
        T3 -> Worker-3
        T4 -> Worker-1
        T5 -> Worker-2
        T6 -> Worker-3
        """
        expected_sequence = [
            "Worker-1",  # T1
            "Worker-2",  # T2
            "Worker-3",  # T3
            "Worker-1",  # T4
            "Worker-2",  # T5
            "Worker-3",  # T6
        ]

        actual_sequence = [
            self.scheduler.select_worker(self.workers).worker_id
            for _ in range(6)
        ]

        self.assertEqual(actual_sequence, expected_sequence)

    def test_reset_scheduler(self) -> None:
        # Advance by 2
        w1 = self.scheduler.select_worker(self.workers)
        w2 = self.scheduler.select_worker(self.workers)
        self.assertEqual(w1.worker_id, "Worker-1")
        self.assertEqual(w2.worker_id, "Worker-2")

        # Reset
        self.scheduler.reset()
        w_reset = self.scheduler.select_worker(self.workers)
        self.assertEqual(w_reset.worker_id, "Worker-1")

    def test_empty_workers_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.scheduler.select_worker([])


if __name__ == "__main__":
    unittest.main()
