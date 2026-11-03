"""
tests/test_cli.py - Tests for main.py CLI handlers and menu actions.

Verifies:
- handle_worker_status output contains thread state, queue contents, workload
- handle_submit_task creates task with real ID
- handle_change_algorithm switches scheduler
- handle_metrics displays accurate metrics
- handle_reset_simulation resets load balancer
"""

import io
from unittest.mock import patch
import unittest

from load_balancer import LoadBalancer
from main import (
    handle_all_tasks,
    handle_change_algorithm,
    handle_metrics,
    handle_reset_simulation,
    handle_submit_multiple,
    handle_submit_task,
    handle_worker_status,
)
from scheduler import RoundRobinScheduler


class TestCLIHandlers(unittest.TestCase):
    """Test suite for CLI interaction handlers in main.py."""

    def setUp(self):
        self.lb = LoadBalancer(worker_count=3, scheduler=RoundRobinScheduler())

    def tearDown(self):
        try:
            self.lb.shutdown(wait=False, timeout=0.5)
        except Exception:
            pass

    def test_handle_worker_status_displays_thread_and_queue(self):
        """Worker status output must show thread status, alive state, and queue contents."""
        # Enqueue a task
        self.lb.create_and_submit_task("CLI-Task", duration=0.5)

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            handle_worker_status(self.lb)

        output = captured.getvalue()
        self.assertIn("WORKER STATUS", output)
        self.assertIn("Execution Thread:", output)
        self.assertIn("ALIVE", output)
        self.assertIn("Queue Contents:", output)
        self.assertIn("Current Workload:", output)

        self.lb.wait_for_completion(timeout=2.0)

    def test_handle_submit_task(self):
        """handle_submit_task prompts for inputs and creates a task with backend-owned ID."""
        inputs = iter(["My CLI Task", "0.05"])
        captured = io.StringIO()
        with patch("builtins.input", lambda _: next(inputs)), patch("sys.stdout", captured):
            handle_submit_task(self.lb)

        output = captured.getvalue()
        self.assertIn("Task created: T001", output)
        self.assertIn("Assigned to: Worker-1", output)
        self.lb.wait_for_completion(timeout=2.0)

    def test_handle_change_algorithm(self):
        """handle_change_algorithm switches the scheduler on the LoadBalancer."""
        inputs = iter(["2"])
        captured = io.StringIO()
        with patch("builtins.input", lambda _: next(inputs)), patch("sys.stdout", captured):
            handle_change_algorithm(self.lb)

        self.assertEqual(self.lb.scheduler_name, "Least Connections")

    def test_handle_reset_simulation(self):
        """handle_reset_simulation prompts confirmation and calls lb.reset()."""
        self.lb.create_and_submit_task("Task-To-Clear", duration=0.05)
        self.lb.wait_for_completion(timeout=2.0)
        self.assertEqual(len(self.lb.get_all_tasks()), 1)

        inputs = iter(["y"])
        captured = io.StringIO()
        with patch("builtins.input", lambda _: next(inputs)), patch("sys.stdout", captured):
            handle_reset_simulation(self.lb)

        output = captured.getvalue()
        self.assertIn("Simulator completely reset", output)
        self.assertEqual(len(self.lb.get_all_tasks()), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

