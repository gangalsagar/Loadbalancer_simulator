"""
tests/test_web.py - Flask API tests for Phase 4 Web Dashboard.

Uses Flask's built-in test client. Each test creates its own LoadBalancer
instance so tests are fully isolated and don't pollute shared state.
"""

import logging
import sys
import os
import time
import unittest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as web_module          # Import the Flask app module
from flask import Flask
from load_balancer import LoadBalancer


# --------------------------------------------------------------------------
# Helper: build a fresh Flask app with an isolated LoadBalancer
# --------------------------------------------------------------------------

def make_test_app():
    """
    Create a fresh Flask test client backed by a new LoadBalancer.
    This isolates each test from side effects of others.
    """
    flask_app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"),
        static_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "static"),
    )
    flask_app.config["TESTING"] = True

    # Silence the LoadBalancer logger in tests
    null_logger = logging.getLogger("lb_test")
    null_logger.addHandler(logging.NullHandler())
    null_logger.propagate = False

    lb = LoadBalancer(worker_count=3, logger=null_logger)

    # Register all routes from web_module but bound to this lb
    # We monkey-patch web_module.lb for each test class.
    return flask_app, lb


class TestWebAPI(unittest.TestCase):
    """Integration tests for all Flask REST API endpoints."""

    def setUp(self):
        """Set up a fresh Flask test client and LoadBalancer for each test."""
        null_logger = logging.getLogger("lb_test_" + self._testMethodName)
        null_logger.addHandler(logging.NullHandler())
        null_logger.propagate = False

        self._lb = LoadBalancer(worker_count=3, logger=null_logger)

        # Temporarily replace the module-level lb with our isolated one
        self._original_lb = web_module.lb
        web_module.lb = self._lb

        # Reset simulation state
        self._original_sim_state = web_module._simulation_state.copy()
        web_module._simulation_state = {
            "running": False,
            "prepared_tasks": [],
            "simulation_start_time": None,
        }

        web_module.app.config["TESTING"] = True
        self.client = web_module.app.test_client()

    def tearDown(self):
        """Restore the original lb and shut down the test lb."""
        web_module.lb = self._original_lb
        web_module._simulation_state = self._original_sim_state
        try:
            self._lb.shutdown(wait=False, timeout=0.5)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 1. GET / — landing page
    # ------------------------------------------------------------------

    def test_01_index_returns_200(self):
        """GET / should return 200 and the landing page HTML."""
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        # Check that the response contains the landing page title
        data = r.data.decode("utf-8")
        self.assertIn("Distributed Load Balancer Simulator", data)

    # ------------------------------------------------------------------
    # 2. GET /api/status
    # ------------------------------------------------------------------

    def test_02_api_status_returns_200(self):
        """GET /api/status should return 200 and required keys."""
        r = self.client.get("/api/status")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        required_keys = [
            "total_workers", "active_workers", "failed_workers",
            "total_submitted", "total_completed", "total_running",
            "total_queued", "scheduler_name", "throughput", "elapsed_time"
        ]
        for key in required_keys:
            self.assertIn(key, body, f"Missing key in /api/status: {key}")

    def test_03_api_status_worker_count(self):
        """GET /api/status should report 3 total workers."""
        r = self.client.get("/api/status")
        body = r.get_json()
        self.assertEqual(body["total_workers"], 3)

    # ------------------------------------------------------------------
    # 3. GET /api/workers
    # ------------------------------------------------------------------

    def test_04_api_workers_returns_list_of_3(self):
        """GET /api/workers should return a list of 3 worker dicts."""
        r = self.client.get("/api/workers")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIsInstance(body, list)
        self.assertEqual(len(body), 3)

    def test_05_api_workers_have_required_fields(self):
        """Each worker dict must contain expected fields."""
        r = self.client.get("/api/workers")
        body = r.get_json()
        required = ["worker_id", "status", "workload", "queue_size", "completed"]
        for w in body:
            for key in required:
                self.assertIn(key, w, f"Worker dict missing key: {key}")

    # ------------------------------------------------------------------
    # 4. GET /api/tasks
    # ------------------------------------------------------------------

    def test_06_api_tasks_initially_empty(self):
        """GET /api/tasks should return an empty list initially."""
        r = self.client.get("/api/tasks")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIsInstance(body, list)
        self.assertEqual(len(body), 0)

    # ------------------------------------------------------------------
    # 5. GET /api/metrics
    # ------------------------------------------------------------------

    def test_07_api_metrics_returns_200(self):
        """GET /api/metrics should return 200 with key metrics."""
        r = self.client.get("/api/metrics")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn("throughput", body)
        self.assertIn("total_completed", body)
        self.assertIn("scheduler_name", body)

    # ------------------------------------------------------------------
    # 6. POST /api/tasks — valid submission
    # ------------------------------------------------------------------

    def test_08_submit_task_valid(self):
        """POST /api/tasks with valid duration should return 200 and task_id."""
        r = self.client.post(
            "/api/tasks",
            json={"duration": 0.05, "name": "Test Task"}
        )
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn("task_id", body)
        self.assertTrue(body["task_id"].startswith("T"), "task_id should start with 'T'")
        self.assertIn("worker", body)

    def test_09_submit_task_appears_in_task_list(self):
        """A submitted task should appear in GET /api/tasks."""
        self.client.post("/api/tasks", json={"duration": 0.05, "name": "Tracked Task"})
        time.sleep(0.05)
        r = self.client.get("/api/tasks")
        body = r.get_json()
        self.assertGreater(len(body), 0)

    # ------------------------------------------------------------------
    # 7. POST /api/tasks — invalid inputs
    # ------------------------------------------------------------------

    def test_10_submit_task_negative_duration(self):
        """POST /api/tasks with negative duration should return 400."""
        r = self.client.post("/api/tasks", json={"duration": -1})
        self.assertEqual(r.status_code, 400)
        body = r.get_json()
        self.assertIn("error", body)

    def test_11_submit_task_zero_duration(self):
        """POST /api/tasks with duration=0 should return 400."""
        r = self.client.post("/api/tasks", json={"duration": 0})
        self.assertEqual(r.status_code, 400)

    def test_12_submit_task_string_duration(self):
        """POST /api/tasks with non-numeric duration should return 400."""
        r = self.client.post("/api/tasks", json={"duration": "fast"})
        self.assertEqual(r.status_code, 400)

    def test_13_submit_task_missing_duration(self):
        """POST /api/tasks with no duration field should return 400."""
        r = self.client.post("/api/tasks", json={"name": "No Duration"})
        self.assertEqual(r.status_code, 400)

    # ------------------------------------------------------------------
    # 8. POST /api/algorithm
    # ------------------------------------------------------------------

    def test_14_set_algorithm_least_connections(self):
        """POST /api/algorithm with 'least_connections' should succeed."""
        r = self.client.post("/api/algorithm", json={"algorithm": "least_connections"})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn("algorithm", body)
        self.assertEqual(body["algorithm"], "Least Connections")

    def test_15_set_algorithm_round_robin(self):
        """POST /api/algorithm with 'round_robin' should succeed."""
        r = self.client.post("/api/algorithm", json={"algorithm": "round_robin"})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["algorithm"], "Round Robin")

    def test_16_set_algorithm_invalid(self):
        """POST /api/algorithm with unknown name should return 400."""
        r = self.client.post("/api/algorithm", json={"algorithm": "magic_algo"})
        self.assertEqual(r.status_code, 400)
        body = r.get_json()
        self.assertIn("error", body)

    def test_17_set_algorithm_missing_field(self):
        """POST /api/algorithm with no 'algorithm' key should return 400."""
        r = self.client.post("/api/algorithm", json={})
        self.assertEqual(r.status_code, 400)

    # ------------------------------------------------------------------
    # 9. POST /api/workers/<id>/fail
    # ------------------------------------------------------------------

    def test_18_fail_worker_valid(self):
        """POST /api/workers/Worker-2/fail should succeed."""
        r = self.client.post("/api/workers/Worker-2/fail")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["worker_id"], "Worker-2")
        self.assertEqual(body["status"], "FAILED")

    def test_19_fail_worker_nonexistent(self):
        """POST /api/workers/NonExistent/fail should return 404."""
        r = self.client.post("/api/workers/NonExistent/fail")
        self.assertEqual(r.status_code, 404)
        body = r.get_json()
        self.assertIn("error", body)

    def test_20_failed_worker_appears_in_failed_list(self):
        """After failing a worker, GET /api/workers/failed should include it."""
        self.client.post("/api/workers/Worker-3/fail")
        r = self.client.get("/api/workers/failed")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        ids = [w["worker_id"] for w in body]
        self.assertIn("Worker-3", ids)

    # ------------------------------------------------------------------
    # 10. POST /api/workers/<id>/recover
    # ------------------------------------------------------------------

    def test_21_recover_worker_valid(self):
        """POST /api/workers/Worker-2/recover after failing should succeed."""
        self.client.post("/api/workers/Worker-2/fail")
        time.sleep(0.05)
        r = self.client.post("/api/workers/Worker-2/recover")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn(body["status"], ("IDLE", "BUSY"))

    def test_22_recover_worker_not_failed(self):
        """POST /api/workers/Worker-1/recover when IDLE should return 400."""
        r = self.client.post("/api/workers/Worker-1/recover")
        self.assertEqual(r.status_code, 400)
        body = r.get_json()
        self.assertIn("error", body)

    def test_23_recover_worker_nonexistent(self):
        """POST /api/workers/NoWorker/recover should return 404."""
        r = self.client.post("/api/workers/NoWorker/recover")
        self.assertEqual(r.status_code, 404)

    # ------------------------------------------------------------------
    # 11. GET /api/workers/failed
    # ------------------------------------------------------------------

    def test_24_failed_workers_initially_empty(self):
        """GET /api/workers/failed should return empty list initially."""
        r = self.client.get("/api/workers/failed")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIsInstance(body, list)
        self.assertEqual(len(body), 0)

    # ------------------------------------------------------------------
    # 12. POST /api/tasks/batch
    # ------------------------------------------------------------------

    def test_25_batch_submit_valid(self):
        """POST /api/tasks/batch with valid params should return submitted list."""
        r = self.client.post(
            "/api/tasks/batch",
            json={"count": 3, "duration": 0.05}
        )
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn("tasks", body)
        self.assertEqual(len(body["tasks"]), 3)

    def test_26_batch_submit_too_many(self):
        """POST /api/tasks/batch with count > 20 should return 400."""
        r = self.client.post(
            "/api/tasks/batch",
            json={"count": 25, "duration": 0.1}
        )
        self.assertEqual(r.status_code, 400)

    # ------------------------------------------------------------------
    # 13. Algorithm reflected in status after switch
    # ------------------------------------------------------------------

    def test_27_algorithm_change_reflected_in_status(self):
        """After switching to LC, /api/status should reflect the new algorithm."""
        self.client.post("/api/algorithm", json={"algorithm": "least_connections"})
        r = self.client.get("/api/status")
        body = r.get_json()
        self.assertEqual(body["scheduler_name"], "Least Connections")

    # ------------------------------------------------------------------
    # 14. Task serialization completeness
    # ------------------------------------------------------------------

    def test_28_task_has_all_fields(self):
        """A submitted task dict should contain the expected fields."""
        self.client.post("/api/tasks", json={"duration": 0.05, "name": "Field Check"})
        time.sleep(0.05)
        r = self.client.get("/api/tasks")
        body = r.get_json()
        self.assertGreater(len(body), 0)
        task = body[0]
        expected = ["id", "name", "status", "duration", "worker", "algorithm", "rerouted"]
        for key in expected:
            self.assertIn(key, task, f"Task dict missing key: {key}")

    # ------------------------------------------------------------------
    # 15. Landing page and simulator routes
    # ------------------------------------------------------------------

    def test_29_landing_page_returns_200(self):
        """GET / should return 200 and landing page HTML."""
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        data = r.data.decode("utf-8")
        self.assertIn("Distributed Load Balancer Simulator", data)
        self.assertIn("Launch Simulator", data)

    def test_30_simulator_page_returns_200(self):
        """GET /simulator should return 200 and simulator HTML."""
        r = self.client.get("/simulator")
        self.assertEqual(r.status_code, 200)
        data = r.data.decode("utf-8")
        self.assertIn("Simulation Configuration", data)
        self.assertIn("Add Task", data)

    def test_31_dashboard_page_returns_200(self):
        """GET /dashboard should return 200 and legacy dashboard HTML."""
        r = self.client.get("/dashboard")
        self.assertEqual(r.status_code, 200)
        data = r.data.decode("utf-8")
        self.assertIn("Load Balancer", data)

    # ------------------------------------------------------------------
    # 16. Worker queues API
    # ------------------------------------------------------------------

    def test_32_worker_queues_returns_200(self):
        """GET /api/workers/queues should return 200 with queue data."""
        r = self.client.get("/api/workers/queues")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIsInstance(body, dict)
        self.assertIn("Worker-1", body)
        self.assertIn("Worker-2", body)
        self.assertIn("Worker-3", body)

    def test_33_worker_queues_structure(self):
        """Each worker queue should be a list with task data."""
        r = self.client.get("/api/workers/queues")
        body = r.get_json()
        for worker_id, queue in body.items():
            self.assertIsInstance(queue, list)

    # ------------------------------------------------------------------
    # 17. Worker thread state in status
    # ------------------------------------------------------------------

    def test_34_worker_status_includes_thread_state(self):
        """Worker status dict should include thread_state and thread_alive."""
        r = self.client.get("/api/workers")
        body = r.get_json()
        for w in body:
            self.assertIn("thread_state", w)
            self.assertIn("thread_alive", w)

    # ------------------------------------------------------------------
    # 18. Prepared tasks API
    # ------------------------------------------------------------------

    def test_35_prepared_tasks_initially_empty(self):
        """GET /api/simulation/prepared should return empty list initially."""
        r = self.client.get("/api/simulation/prepared")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["count"], 0)
        self.assertEqual(len(body["tasks"]), 0)

    def test_36_add_prepared_task_valid(self):
        """POST /api/simulation/prepared with valid data should succeed."""
        r = self.client.post(
            "/api/simulation/prepared",
            json={"name": "Test Task", "duration": 5.0}
        )
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn("prepared_count", body)
        self.assertGreater(body["prepared_count"], 0)

    def test_37_add_prepared_task_missing_name(self):
        """POST /api/simulation/prepared without name should return 400."""
        r = self.client.post(
            "/api/simulation/prepared",
            json={"duration": 5.0}
        )
        self.assertEqual(r.status_code, 400)

    def test_38_add_prepared_task_missing_duration(self):
        """POST /api/simulation/prepared without duration should return 400."""
        r = self.client.post(
            "/api/simulation/prepared",
            json={"name": "Test Task"}
        )
        self.assertEqual(r.status_code, 400)

    def test_39_add_prepared_task_invalid_duration(self):
        """POST /api/simulation/prepared with invalid duration should return 400."""
        r = self.client.post(
            "/api/simulation/prepared",
            json={"name": "Test Task", "duration": -1}
        )
        self.assertEqual(r.status_code, 400)

    # ------------------------------------------------------------------
    # 19. Simulation status API
    # ------------------------------------------------------------------

    def test_40_simulation_status_returns_200(self):
        """GET /api/simulation/status should return 200 with status data."""
        r = self.client.get("/api/simulation/status")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn("running", body)
        self.assertIn("prepared_count", body)
        self.assertIn("elapsed_time", body)

    # ------------------------------------------------------------------
    # 20. Simulation start API
    # ------------------------------------------------------------------

    def test_41_simulation_start_without_tasks_fails(self):
        """POST /api/simulation/start without prepared tasks should return 400."""
        r = self.client.post("/api/simulation/start")
        self.assertEqual(r.status_code, 400)
        body = r.get_json()
        self.assertIn("error", body)

    def test_42_simulation_start_with_tasks_succeeds(self):
        """POST /api/simulation/start with prepared tasks should succeed."""
        self.client.post(
            "/api/simulation/prepared",
            json={"name": "Test Task", "duration": 0.05}
        )
        r = self.client.post("/api/simulation/start")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn("submitted_tasks", body)
        self.assertGreater(len(body["submitted_tasks"]), 0)

    def test_43_simulation_start_twice_fails(self):
        """POST /api/simulation/start when already running should return 400."""
        self.client.post(
            "/api/simulation/prepared",
            json={"name": "Test Task", "duration": 0.05}
        )
        self.client.post("/api/simulation/start")
        r = self.client.post("/api/simulation/start")
        self.assertEqual(r.status_code, 400)

    # ------------------------------------------------------------------
    # 21. Simulation reset API
    # ------------------------------------------------------------------

    def test_44_simulation_reset_succeeds(self):
        """POST /api/simulation/reset should clear prepared tasks."""
        self.client.post(
            "/api/simulation/prepared",
            json={"name": "Test Task", "duration": 5.0}
        )
        r = self.client.post("/api/simulation/reset")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["prepared_count"], 0)

    def test_45_simulation_reset_clears_prepared_tasks(self):
        """After reset, GET /api/simulation/prepared should be empty."""
        self.client.post(
            "/api/simulation/prepared",
            json={"name": "Test Task", "duration": 5.0}
        )
        self.client.post("/api/simulation/reset")
        r = self.client.get("/api/simulation/prepared")
        body = r.get_json()
        self.assertEqual(body["count"], 0)

    # ------------------------------------------------------------------
    # 22. Prepared tasks do not execute before simulation
    # ------------------------------------------------------------------

    def test_46_prepared_tasks_do_not_execute_before_start(self):
        """Prepared tasks should not appear in task list before simulation starts."""
        self.client.post(
            "/api/simulation/prepared",
            json={"name": "Test Task", "duration": 5.0}
        )
        r = self.client.get("/api/tasks")
        body = r.get_json()
        # Tasks should not be submitted to LoadBalancer yet
        self.assertEqual(len(body), 0)

    # ------------------------------------------------------------------
    # 23. Simulation start submits tasks to LoadBalancer
    # ------------------------------------------------------------------

    def test_47_simulation_start_submits_tasks_to_loadbalancer(self):
        """After simulation start, tasks should appear in LoadBalancer task list."""
        self.client.post(
            "/api/simulation/prepared",
            json={"name": "Test Task", "duration": 0.05}
        )
        self.client.post("/api/simulation/start")
        time.sleep(0.05)
        r = self.client.get("/api/tasks")
        body = r.get_json()
        # Tasks should now be submitted to LoadBalancer
        self.assertGreater(len(body), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

