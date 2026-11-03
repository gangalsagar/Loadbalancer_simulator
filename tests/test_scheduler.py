"""
Unit tests for Scheduler components (Round Robin and Least Connections).
"""

import unittest

from scheduler import LeastConnectionsScheduler, RoundRobinScheduler, create_scheduler
from server import Worker
from task import Task


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


class TestLeastConnectionsScheduler(unittest.TestCase):
    def setUp(self) -> None:
        self.scheduler = LeastConnectionsScheduler()
        self.w1 = Worker("Worker-1")
        self.w2 = Worker("Worker-2")
        self.w3 = Worker("Worker-3")
        self.workers = [self.w1, self.w2, self.w3]

    def test_selects_minimum_workload(self) -> None:
        """
        Worker 1: workload = 4 (1 executing, 3 queued)
        Worker 2: workload = 1 (1 executing, 0 queued)
        Worker 3: workload = 2 (0 executing, 2 queued)

        Scheduler must pick Worker 2 (workload 1).
        """
        # Configure Worker 1
        self.w1.current_task = Task("Executing-1")
        self.w1.task_queue.put(Task("Q1"))
        self.w1.task_queue.put(Task("Q2"))
        self.w1.task_queue.put(Task("Q3"))
        self.assertEqual(self.w1.get_workload(), 4)

        # Configure Worker 2
        self.w2.current_task = Task("Executing-2")
        self.assertEqual(self.w2.get_workload(), 1)

        # Configure Worker 3
        self.w3.task_queue.put(Task("Q4"))
        self.w3.task_queue.put(Task("Q5"))
        self.assertEqual(self.w3.get_workload(), 2)

        # Selection
        selected = self.scheduler.select_worker(self.workers)
        self.assertEqual(selected.worker_id, "Worker-2")

    def test_deterministic_tie_breaking(self) -> None:
        """
        Worker 1: workload = 2
        Worker 2: workload = 2
        Worker 3: workload = 3

        When two workers share minimum workload, the first encountered (Worker 1)
        must be selected deterministically.
        """
        self.w1.task_queue.put(Task("W1-1"))
        self.w1.task_queue.put(Task("W1-2"))

        self.w2.task_queue.put(Task("W2-1"))
        self.w2.task_queue.put(Task("W2-2"))

        self.w3.task_queue.put(Task("W3-1"))
        self.w3.task_queue.put(Task("W3-2"))
        self.w3.task_queue.put(Task("W3-3"))

        self.assertEqual(self.w1.get_workload(), 2)
        self.assertEqual(self.w2.get_workload(), 2)
        self.assertEqual(self.w3.get_workload(), 3)

        selected = self.scheduler.select_worker(self.workers)
        self.assertEqual(selected.worker_id, "Worker-1")

    def test_all_idle_workers_tie_breaking(self) -> None:
        """When all workers are idle (workload 0), Worker-1 is chosen."""
        selected = self.scheduler.select_worker(self.workers)
        self.assertEqual(selected.worker_id, "Worker-1")

    def test_empty_workers_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.scheduler.select_worker([])

    def test_stopped_workers_filtered_if_active_exist(self) -> None:
        """Stopped workers should not be selected if active workers exist."""
        self.w1.stop()
        self.assertFalse(self.w1.is_available)
        self.assertTrue(self.w2.is_available)
        self.assertTrue(self.w3.is_available)

        selected = self.scheduler.select_worker(self.workers)
        self.assertIn(selected.worker_id, ["Worker-2", "Worker-3"])
        self.assertEqual(selected.worker_id, "Worker-2")


class TestSchedulerFactory(unittest.TestCase):
    def test_create_round_robin(self) -> None:
        sched1 = create_scheduler("round_robin")
        self.assertIsInstance(sched1, RoundRobinScheduler)
        sched2 = create_scheduler("rr")
        self.assertIsInstance(sched2, RoundRobinScheduler)
        sched3 = create_scheduler("1")
        self.assertIsInstance(sched3, RoundRobinScheduler)

    def test_create_least_connections(self) -> None:
        sched1 = create_scheduler("least_connections")
        self.assertIsInstance(sched1, LeastConnectionsScheduler)
        sched2 = create_scheduler("lc")
        self.assertIsInstance(sched2, LeastConnectionsScheduler)
        sched3 = create_scheduler("2")
        self.assertIsInstance(sched3, LeastConnectionsScheduler)

    def test_unknown_scheduler_raises(self) -> None:
        with self.assertRaises(ValueError):
            create_scheduler("invalid_algo")


if __name__ == "__main__":
    unittest.main()
