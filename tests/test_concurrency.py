"""
Concurrency verification tests.

Demonstrates and verifies that tasks distributed across multiple backend
workers execute concurrently rather than sequentially.
"""

import logging
import time
import unittest

from load_balancer import LoadBalancer
from task import TaskStatus, reset_task_id_generator


class TestConcurrency(unittest.TestCase):
    def setUp(self) -> None:
        reset_task_id_generator(1)
        null_logger = logging.getLogger("TestConcurrency")
        null_logger.addHandler(logging.NullHandler())
        self.lb = LoadBalancer(worker_count=3, logger=null_logger, auto_start=True)

    def tearDown(self) -> None:
        self.lb.shutdown()

    def test_concurrent_execution_speedup(self) -> None:
        """
        Verify that 3 tasks of duration D run concurrently in ~D time,
        drastically faster than sequential 3 * D time.
        """
        task_duration = 0.4
        sequential_expected = 3 * task_duration  # ~1.2s

        start_time = time.time()

        t1 = self.lb.create_and_submit_task("Concurrent-1", duration=task_duration)
        t2 = self.lb.create_and_submit_task("Concurrent-2", duration=task_duration)
        t3 = self.lb.create_and_submit_task("Concurrent-3", duration=task_duration)

        # Wait for all workers to finish their queues
        for w in self.lb.workers:
            w.task_queue.join()

        elapsed_time = time.time() - start_time

        # Verify all tasks succeeded
        self.assertEqual(t1.status, TaskStatus.COMPLETED)
        self.assertEqual(t2.status, TaskStatus.COMPLETED)
        self.assertEqual(t3.status, TaskStatus.COMPLETED)

        # Elapsed time for concurrent execution must be significantly less
        # than sequential time (e.g. well below 1.0s vs 1.2s minimum)
        self.assertLess(
            elapsed_time,
            sequential_expected * 0.8,
            f"Expected concurrency speedup: elapsed {elapsed_time:.2f}s "
            f"should be substantially less than sequential {sequential_expected:.2f}s."
        )

    def test_execution_time_window_overlap(self) -> None:
        """
        Mathematically verify that the execution windows [started_at, completed_at]
        of the 3 concurrent tasks overlap with each other.
        """
        task_duration = 0.35

        t1 = self.lb.create_and_submit_task("Overlap-1", duration=task_duration)
        t2 = self.lb.create_and_submit_task("Overlap-2", duration=task_duration)
        t3 = self.lb.create_and_submit_task("Overlap-3", duration=task_duration)

        for w in self.lb.workers:
            w.task_queue.join()

        # Check overlap: Task 1 and Task 2
        # Overlap exists if max(start1, start2) < min(end1, end2)
        overlap_1_2 = max(t1.started_at, t2.started_at) < min(t1.completed_at, t2.completed_at)
        overlap_2_3 = max(t2.started_at, t3.started_at) < min(t2.completed_at, t3.completed_at)

        self.assertTrue(overlap_1_2, "Execution windows of Task 1 and Task 2 did not overlap!")
        self.assertTrue(overlap_2_3, "Execution windows of Task 2 and Task 3 did not overlap!")


if __name__ == "__main__":
    unittest.main()

