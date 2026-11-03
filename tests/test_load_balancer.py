"""
Unit tests for LoadBalancer class.
"""

import logging
import time
import unittest

from load_balancer import LoadBalancer
from scheduler import LeastConnectionsScheduler, RoundRobinScheduler
from task import Task, TaskStatus, reset_task_id_generator


class TestLoadBalancer(unittest.TestCase):
    def setUp(self) -> None:
        reset_task_id_generator(1)
        null_logger = logging.getLogger("TestLB")
        null_logger.addHandler(logging.NullHandler())
        self.lb = LoadBalancer(worker_count=3, logger=null_logger, auto_start=True)

    def tearDown(self) -> None:
        self.lb.shutdown()

    def test_initial_state(self) -> None:
        self.assertEqual(len(self.lb.workers), 3)
        self.assertEqual([w.worker_id for w in self.lb.workers], ["Worker-1", "Worker-2", "Worker-3"])
        self.assertEqual(len(self.lb.get_all_tasks()), 0)
        self.assertEqual(self.lb.scheduler_name, "Round Robin")

        metrics = self.lb.get_metrics()
        self.assertEqual(metrics["total_submitted"], 0)
        self.assertEqual(metrics["total_completed"], 0)
        self.assertEqual(metrics["worker_count"], 3)
        self.assertEqual(metrics["scheduler_name"], "Round Robin")

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
        self.assertTrue(self.lb.wait_for_completion(timeout=5.0))

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

    def test_switch_algorithm_dynamically(self) -> None:
        self.assertEqual(self.lb.scheduler_name, "Round Robin")

        # Switch to Least Connections
        self.lb.set_algorithm("least_connections")
        self.assertEqual(self.lb.scheduler_name, "Least Connections")

        # Switch back to Round Robin
        self.lb.set_algorithm("round_robin")
        self.assertEqual(self.lb.scheduler_name, "Round Robin")

    def test_least_connections_distribution(self) -> None:
        # Switch to Least Connections
        self.lb.set_algorithm("least_connections")

        # Worker-1 gets a long task (0.6s)
        t1 = self.lb.create_and_submit_task("Long-1", duration=0.6)
        self.assertEqual(t1.assigned_worker, "Worker-1")
        self.assertEqual(t1.scheduling_algorithm, "Least Connections")

        # Workers 2 and 3 get short tasks (0.1s)
        t2 = self.lb.create_and_submit_task("Short-2", duration=0.1)
        t3 = self.lb.create_and_submit_task("Short-3", duration=0.1)
        self.assertEqual(t2.assigned_worker, "Worker-2")
        self.assertEqual(t3.assigned_worker, "Worker-3")

        # Wait for t2 and t3 to finish while Worker-1 is still busy
        time.sleep(0.25)
        self.assertEqual(t2.status, TaskStatus.COMPLETED)
        self.assertEqual(t3.status, TaskStatus.COMPLETED)
        self.assertEqual(t1.status, TaskStatus.RUNNING)

        # Submit next task. Worker-1 is busy (workload >= 1), Workers 2 and 3 are idle (workload 0)
        # Least Connections MUST route to Worker-2 (first idle worker), NOT Worker-1
        t4 = self.lb.create_and_submit_task("Short-4", duration=0.1)
        self.assertEqual(t4.assigned_worker, "Worker-2")

        # Finish all tasks
        self.assertTrue(self.lb.wait_for_completion(timeout=5.0))

    def test_task_workload_metadata_recorded(self) -> None:
        self.lb.set_algorithm("least_connections")
        t = self.lb.create_and_submit_task("Meta-Task", duration=0.1)
        self.assertEqual(t.scheduling_algorithm, "Least Connections")
        self.assertIsNotNone(t.workload_before_assignment)
        self.assertIsNotNone(t.workload_after_assignment)
        self.assertEqual(t.workload_after_assignment, t.workload_before_assignment + 1)

    def test_enhanced_metrics(self) -> None:
        t1 = self.lb.create_and_submit_task("T1", duration=0.1)
        t2 = self.lb.create_and_submit_task("T2", duration=0.1)
        self.assertTrue(self.lb.wait_for_completion(timeout=5.0))

        m = self.lb.get_metrics()
        self.assertEqual(m["total_completed"], 2)
        self.assertGreater(m["total_execution_time"], 0.0)
        self.assertGreater(m["avg_execution_time"], 0.0)
        self.assertGreaterEqual(m["avg_waiting_time"], 0.0)
        self.assertGreater(m["throughput"], 0.0)
        self.assertIn("worker_workload", m)
        self.assertIn("worker_assigned", m)

    def test_shutdown_prevents_submission(self) -> None:
        self.lb.shutdown()
        with self.assertRaises(RuntimeError):
            self.lb.create_and_submit_task("After shutdown", duration=0.1)


if __name__ == "__main__":
    unittest.main()
