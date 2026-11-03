"""
Unit tests for LoadBalancer class.
"""

import logging
import time
import unittest

from load_balancer import LoadBalancer
from task import Task, TaskStatus, reset_task_id_generator


class TestLoadBalancer(unittest.TestCase):
    def setUp(self) -> None:
        reset_task_id_generator(1)
        # Use null logger to keep test output clean
        null_logger = logging.getLogger("TestLB")
        null_logger.addHandler(logging.NullHandler())
        self.lb = LoadBalancer(worker_count=3, logger=null_logger, auto_start=True)

    def tearDown(self) -> None:
        self.lb.shutdown()

    def test_initial_state(self) -> None:
        self.assertEqual(len(self.lb.workers), 3)
        self.assertEqual([w.worker_id for w in self.lb.workers], ["Worker-1", "Worker-2", "Worker-3"])
        self.assertEqual(len(self.lb.get_all_tasks()), 0)

        metrics = self.lb.get_metrics()
        self.assertEqual(metrics["total_submitted"], 0)
        self.assertEqual(metrics["total_completed"], 0)
        self.assertEqual(metrics["worker_count"], 3)

    def test_task_submission_and_round_robin_distribution(self) -> None:
        t1 = self.lb.create_and_submit_task("Task 1", duration=0.1)
        t2 = self.lb.create_and_submit_task("Task 2", duration=0.1)
        t3 = self.lb.create_and_submit_task("Task 3", duration=0.1)
        t4 = self.lb.create_and_submit_task("Task 4", duration=0.1)

        self.assertEqual(t1.assigned_worker, "Worker-1")
        self.assertEqual(t2.assigned_worker, "Worker-2")
        self.assertEqual(t3.assigned_worker, "Worker-3")
        self.assertEqual(t4.assigned_worker, "Worker-1")

        # Verify lookup
        self.assertEqual(self.lb.get_task(t1.task_id), t1)
        self.assertEqual(self.lb.get_task(t2.task_id), t2)
        self.assertIsNone(self.lb.get_task("NON_EXISTENT"))

        # Wait for all tasks to complete
        for w in self.lb.workers:
            w.task_queue.join()
        time.sleep(0.05)

        self.assertEqual(t1.status, TaskStatus.COMPLETED)
        self.assertEqual(t2.status, TaskStatus.COMPLETED)
        self.assertEqual(t3.status, TaskStatus.COMPLETED)
        self.assertEqual(t4.status, TaskStatus.COMPLETED)

        metrics = self.lb.get_metrics()
        self.assertEqual(metrics["total_submitted"], 4)
        self.assertEqual(metrics["total_completed"], 4)
        self.assertEqual(metrics["worker_completed"]["Worker-1"], 2)
        self.assertEqual(metrics["worker_completed"]["Worker-2"], 1)
        self.assertEqual(metrics["worker_completed"]["Worker-3"], 1)

    def test_shutdown_prevents_submission(self) -> None:
        self.lb.shutdown()
        with self.assertRaises(RuntimeError):
            self.lb.create_and_submit_task("After shutdown", duration=0.1)


if __name__ == "__main__":
    unittest.main()

