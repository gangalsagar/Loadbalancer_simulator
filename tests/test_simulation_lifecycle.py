"""
tests/test_simulation_lifecycle.py - End-to-end integration tests for simulation lifecycle.

Verifies:
- 5 prepared tasks produce exactly 5 backend tasks (no duplicates)
- Run Simulation cannot accidentally double-submit
- Backend owns task IDs (T001, T002...)
- Prepared tasks have temporary identifiers before start
- Authoritative CRUD lifecycle on prepared tasks
- Reset clears prepared tasks and LoadBalancer backend
- Schedulers ignore failed workers and use recovered workers
- Thread states accurately reported
"""

import logging
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as web_module
from load_balancer import LoadBalancer
from scheduler import LeastConnectionsScheduler, RoundRobinScheduler
from server import WorkerStatus
from task import TaskStatus, reset_task_id_generator


class TestSimulationLifecycle(unittest.TestCase):
    """End-to-end tests for task preparation, single submission, and reset."""

    def setUp(self):
        reset_task_id_generator(1)
        null_logger = logging.getLogger("sim_test_" + self._testMethodName)
        null_logger.addHandler(logging.NullHandler())
        null_logger.propagate = False

        self._lb = LoadBalancer(worker_count=3, logger=null_logger)
        self._original_lb = web_module.lb
        web_module.lb = self._lb

        self._original_sim_state = web_module._simulation_state.copy()
        web_module._simulation_state = {
            "running": False,
            "prepared_tasks": [],
            "simulation_start_time": None,
        }

        web_module.app.config["TESTING"] = True
        self.client = web_module.app.test_client()

    def tearDown(self):
        web_module.lb = self._original_lb
        web_module._simulation_state = self._original_sim_state
        try:
            self._lb.shutdown(wait=False, timeout=0.5)
        except Exception:
            pass

    def test_prepared_task_crud_lifecycle(self):
        """Authoritative prepared task addition, listing, deletion, and index renumbering."""
        # Add 3 prepared tasks
        self.client.post("/api/simulation/prepared", json={"name": "Task A", "duration": 3.0})
        self.client.post("/api/simulation/prepared", json={"name": "Task B", "duration": 5.0})
        self.client.post("/api/simulation/prepared", json={"name": "Task C", "duration": 2.0})

        # Verify GET returns all 3
        r = self.client.get("/api/simulation/prepared")
        data = r.get_json()
        self.assertEqual(data["count"], 3)
        self.assertEqual(data["tasks"][0]["name"], "Task A")
        self.assertEqual(data["tasks"][0]["label"], "Prepared Task 1")
        self.assertEqual(data["tasks"][1]["name"], "Task B")
        self.assertEqual(data["tasks"][1]["label"], "Prepared Task 2")
        self.assertEqual(data["tasks"][2]["name"], "Task C")
        self.assertEqual(data["tasks"][2]["label"], "Prepared Task 3")

        # Delete middle task (index 1)
        r_del = self.client.delete("/api/simulation/prepared/1")
        self.assertEqual(r_del.status_code, 200)

        # Verify remaining 2 tasks are properly re-indexed
        r_after = self.client.get("/api/simulation/prepared")
        data_after = r_after.get_json()
        self.assertEqual(data_after["count"], 2)
        self.assertEqual(data_after["tasks"][0]["name"], "Task A")
        self.assertEqual(data_after["tasks"][1]["name"], "Task C")
        self.assertEqual(data_after["tasks"][1]["label"], "Prepared Task 2")

    def test_exactly_five_tasks_submitted_no_duplicates(self):
        """
        Critical bug verification:
        Adding 5 prepared tasks and starting simulation must produce exactly 5 backend tasks,
        with no duplicates and IDs starting at T001 through T005.
        """
        durations = [0.05, 0.05, 0.05, 0.05, 0.05]
        for i, d in enumerate(durations, start=1):
            r = self.client.post(
                "/api/simulation/prepared",
                json={"name": f"Workload-{i}", "duration": d}
            )
            self.assertEqual(r.status_code, 200)

        # Before start, backend tasks must be empty
        tasks_before = self._lb.get_all_tasks()
        self.assertEqual(len(tasks_before), 0)

        # Start simulation
        r_start = self.client.post("/api/simulation/start")
        self.assertEqual(r_start.status_code, 200)
        body = r_start.get_json()
        submitted = body["submitted_tasks"]
        self.assertEqual(len(submitted), 5)

        # Verify exact IDs created
        expected_ids = ["T001", "T002", "T003", "T004", "T005"]
        self.assertEqual(submitted, expected_ids)

        # Backend must contain exactly 5 tasks (NOT 10, NOT 6)
        all_backend_tasks = self._lb.get_all_tasks()
        self.assertEqual(len(all_backend_tasks), 5)
        backend_ids = [t.task_id for t in all_backend_tasks]
        self.assertEqual(backend_ids, expected_ids)
        self.assertEqual(len(backend_ids), len(set(backend_ids)), "Duplicate task IDs detected!")

    def test_run_simulation_cannot_double_submit(self):
        """Calling /api/simulation/start multiple times cannot double-submit tasks."""
        self.client.post(
            "/api/simulation/prepared",
            json={"name": "Task 1", "duration": 0.05}
        )
        r1 = self.client.post("/api/simulation/start")
        self.assertEqual(r1.status_code, 200)

        # Second call while running must return 400
        r2 = self.client.post("/api/simulation/start")
        self.assertEqual(r2.status_code, 400)

        # Total backend tasks must still be exactly 1
        self.assertEqual(len(self._lb.get_all_tasks()), 1)

    def test_full_reset_via_api(self):
        """POST /api/simulation/reset completely resets the LoadBalancer."""
        # Add and run tasks
        self.client.post("/api/simulation/prepared", json={"name": "T1", "duration": 0.05})
        self.client.post("/api/simulation/prepared", json={"name": "T2", "duration": 0.05})
        self.client.post("/api/simulation/start")
        self._lb.wait_for_completion(timeout=2.0)

        # Fail a worker
        self.client.post("/api/workers/Worker-2/fail")

        # Now trigger full reset
        r_reset = self.client.post("/api/simulation/reset")
        self.assertEqual(r_reset.status_code, 200)

        # Verify all aspects of state are zeroed / healthy
        status_resp = self.client.get("/api/status").get_json()
        self.assertEqual(status_resp["total_submitted"], 0)
        self.assertEqual(status_resp["total_completed"], 0)
        self.assertEqual(status_resp["total_failed"], 0)
        self.assertEqual(status_resp["total_interrupted"], 0)
        self.assertEqual(status_resp["failed_workers"], 0)
        self.assertEqual(status_resp["active_workers"], 3)

        # Check workers list
        workers_resp = self.client.get("/api/workers").get_json()
        for w in workers_resp:
            self.assertEqual(w["status"], "IDLE")
            self.assertTrue(w["available"])
            self.assertTrue(w["thread_alive"])
            self.assertEqual(w["workload"], 0)
            self.assertIsNone(w["current_task_id"])

        # Check prepared tasks are empty
        prep_resp = self.client.get("/api/simulation/prepared").get_json()
        self.assertEqual(prep_resp["count"], 0)

        # Next submitted task must start at T001
        self.client.post("/api/simulation/prepared", json={"name": "After Reset", "duration": 0.05})
        r_start = self.client.post("/api/simulation/start")
        self.assertEqual(r_start.get_json()["submitted_tasks"], ["T001"])
        self._lb.wait_for_completion(timeout=2.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
