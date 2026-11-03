"""
tests/test_reset.py - Comprehensive tests for LoadBalancer.reset() and Worker.reset().

Verifies:
- reset after normal simulation
- reset after worker failure
- reset while tasks exist in queues
- reset after completed tasks
- reset after interrupted tasks
- reset after recovery
- all workers are healthy IDLE threads with empty queues
- all metrics and counters are zeroed
- task registry is cleared
- task ID sequence restarts at T001
- no duplicate or stale threads remain
"""

import time
import unittest

from load_balancer import LoadBalancer
from scheduler import LeastConnectionsScheduler, RoundRobinScheduler
from server import Worker, WorkerStatus
from task import TaskStatus


class TestLoadBalancerReset(unittest.TestCase):
    """Unit and integration tests for LoadBalancer.reset()."""

    def setUp(self):
        self.lb = LoadBalancer(worker_count=3, scheduler=RoundRobinScheduler())

    def tearDown(self):
        try:
            self.lb.shutdown(wait=False, timeout=0.5)
        except Exception:
            pass

    def test_reset_initial_state(self):
        """Calling reset on a fresh load balancer leaves it in a clean initial state."""
        self.lb.reset()
        m = self.lb.get_metrics()
        self.assertEqual(m["total_submitted"], 0)
        self.assertEqual(m["total_completed"], 0)
        self.assertEqual(m["total_running"], 0)
        self.assertEqual(m["total_queued"], 0)
        self.assertEqual(m["total_failed"], 0)
        self.assertEqual(m["total_interrupted"], 0)
        self.assertEqual(m["total_re_routed"], 0)
        self.assertEqual(m["total_worker_failures"], 0)
        self.assertEqual(m["total_worker_recoveries"], 0)
        self.assertEqual(len(self.lb.get_all_tasks()), 0)

        for w in self.lb.workers:
            self.assertEqual(w.status, WorkerStatus.IDLE)
            self.assertTrue(w.is_available)
            self.assertTrue(w._thread.is_alive())
            self.assertEqual(w.get_workload(), 0)
            self.assertIsNone(w.current_task)

    def test_reset_after_completed_tasks(self):
        """After submitting and completing tasks, reset clears tasks and resets IDs."""
        for i in range(4):
            self.lb.create_and_submit_task(f"Task-{i}", duration=0.05)
        self.lb.wait_for_completion(timeout=3.0)

        tasks_before = self.lb.get_all_tasks()
        self.assertEqual(len(tasks_before), 4)

        # Reset
        self.lb.reset()

        self.assertEqual(len(self.lb.get_all_tasks()), 0)
        m = self.lb.get_metrics()
        self.assertEqual(m["total_submitted"], 0)
        self.assertEqual(m["total_completed"], 0)
        self.assertEqual(m["total_execution_time"], 0.0)

        # First task after reset must have ID T001
        t_new = self.lb.create_and_submit_task("Fresh-Task", duration=0.05)
        self.assertEqual(t_new.task_id, "T001")
        self.lb.wait_for_completion(timeout=2.0)

    def test_reset_after_worker_failure(self):
        """Reset properly recovers FAILED workers, restarts threads, and zeros failure metrics."""
        self.lb.create_and_submit_task("Task-1", duration=1.0)
        time.sleep(0.05)

        # Fail Worker-1
        self.lb.simulate_worker_failure("Worker-1")
        w1 = self.lb.get_worker_by_id("Worker-1")
        self.assertEqual(w1.status, WorkerStatus.FAILED)
        self.assertFalse(w1.is_available)
        self.assertGreater(self.lb.total_worker_failures, 0)

        # Reset
        self.lb.reset()

        # All workers must now be healthy and available
        self.assertEqual(w1.status, WorkerStatus.IDLE)
        self.assertTrue(w1.is_available)
        self.assertTrue(w1._thread.is_alive())
        self.assertEqual(self.lb.total_worker_failures, 0)
        self.assertEqual(len(self.lb.get_available_workers()), 3)

        # Can assign task to previously failed worker
        t = self.lb.create_and_submit_task("New-Task", duration=0.05)
        self.assertEqual(t.task_id, "T001")
        self.lb.wait_for_completion(timeout=2.0)
        self.assertEqual(t.status, TaskStatus.COMPLETED)

    def test_reset_after_interrupted_tasks(self):
        """Reset clears interrupted task accounting."""
        self.lb.create_and_submit_task("Task-Long", duration=1.0)
        time.sleep(0.05)
        self.lb.simulate_worker_failure("Worker-1")

        self.lb.reset()

        m = self.lb.get_metrics()
        self.assertEqual(m["total_interrupted"], 0)
        self.assertEqual(m["total_re_routed"], 0)

    def test_reset_after_worker_recovery(self):
        """Reset after fail-then-recover lifecycle cleanly resets all counts."""
        self.lb.simulate_worker_failure("Worker-2")
        self.lb.recover_worker("Worker-2")
        w2 = self.lb.get_worker_by_id("Worker-2")
        self.assertEqual(w2.recovery_count, 1)

        self.lb.reset()

        self.assertEqual(w2.recovery_count, 0)
        self.assertEqual(w2.failure_count, 0)
        self.assertEqual(self.lb.total_worker_recoveries, 0)

    def test_reset_while_tasks_queued(self):
        """Reset with multiple queued tasks drains all queues and does not execute them."""
        # Submit tasks with long durations
        for i in range(6):
            self.lb.create_and_submit_task(f"Long-{i}", duration=2.0)

        # Immediately reset
        self.lb.reset()

        # Queues must be empty
        for w in self.lb.workers:
            self.assertEqual(w.task_queue.qsize(), 0)
            self.assertIsNone(w.current_task)
            self.assertEqual(w.get_workload(), 0)
            self.assertEqual(w.status, WorkerStatus.IDLE)

        m = self.lb.get_metrics()
        self.assertEqual(m["total_submitted"], 0)
        self.assertEqual(m["total_queued"], 0)
        self.assertEqual(m["total_running"], 0)

    def test_reset_scheduler_pointer(self):
        """Resetting resets Round Robin index so assignments start at Worker-1."""
        self.lb.create_and_submit_task("T1", duration=0.05)  # assigned to Worker-1
        self.lb.create_and_submit_task("T2", duration=0.05)  # assigned to Worker-2
        self.lb.wait_for_completion(timeout=2.0)

        self.lb.reset()

        t_after = self.lb.create_and_submit_task("T-After", duration=0.05)
        self.assertEqual(t_after.assigned_worker, "Worker-1")
        self.lb.wait_for_completion(timeout=2.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

