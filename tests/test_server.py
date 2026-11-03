"""
Unit tests for Worker / Server backend execution and workload tracking.
"""

import time
import unittest

from server import Worker, WorkerStatus
from task import Task, TaskStatus


class TestWorker(unittest.TestCase):
    def test_worker_initial_state(self) -> None:
        worker = Worker(worker_id="Worker-1")
        self.assertEqual(worker.worker_id, "Worker-1")
        self.assertEqual(worker.status, WorkerStatus.IDLE)
        self.assertIsNone(worker.current_task)
        self.assertEqual(worker.completed_task_count, 0)
        self.assertEqual(worker.failed_task_count, 0)
        self.assertEqual(worker.assigned_task_count, 0)
        self.assertEqual(worker.task_queue.qsize(), 0)
        self.assertEqual(worker.get_workload(), 0)

        info = worker.get_status_dict()
        self.assertEqual(info["worker_id"], "Worker-1")
        self.assertEqual(info["status"], "IDLE")
        self.assertIsNone(info["current_task_id"])
        self.assertEqual(info["queue_size"], 0)
        self.assertEqual(info["workload"], 0)
        self.assertEqual(info["completed"], 0)
        self.assertEqual(info["failed"], 0)
        self.assertEqual(info["assigned"], 0)

    def test_workload_calculation_idle_and_queued(self) -> None:
        worker = Worker(worker_id="Worker-Wkld")
        self.assertEqual(worker.get_workload(), 0)

        # Add 3 tasks without starting worker thread
        t1 = Task("T1")
        t2 = Task("T2")
        t3 = Task("T3")
        worker.add_task(t1)
        worker.add_task(t2)
        worker.add_task(t3)

        # Queued tasks = 3, executing = 0 -> workload = 3
        self.assertEqual(worker.get_workload(), 3)
        self.assertEqual(worker.assigned_task_count, 3)

        # Simulate executing 1 task
        worker.current_task = t1
        # Now 1 executing + 3 in queue = 4
        self.assertEqual(worker.get_workload(), 4)

    def test_worker_task_execution(self) -> None:
        worker = Worker(worker_id="Worker-Test")
        worker.start()
        try:
            task = Task(name="Quick Task", duration=0.1)
            worker.add_task(task)

            # Task should become queued
            self.assertEqual(task.status, TaskStatus.QUEUED)
            self.assertEqual(task.assigned_worker, "Worker-Test")

            # Wait for execution to finish
            worker.task_queue.join()
            time.sleep(0.05)  # Allow finally block to settle

            self.assertEqual(task.status, TaskStatus.COMPLETED)
            self.assertEqual(worker.completed_task_count, 1)
            self.assertEqual(worker.status, WorkerStatus.IDLE)
            self.assertIsNone(worker.current_task)
            self.assertEqual(worker.get_workload(), 0)
            self.assertGreater(worker.total_execution_time, 0.0)
        finally:
            worker.stop()

    def test_worker_multiple_tasks_sequential(self) -> None:
        worker = Worker(worker_id="Worker-Seq")
        worker.start()
        try:
            t1 = Task(name="Task 1", duration=0.05)
            t2 = Task(name="Task 2", duration=0.05)
            worker.add_task(t1)
            worker.add_task(t2)

            worker.task_queue.join()
            time.sleep(0.05)

            self.assertEqual(t1.status, TaskStatus.COMPLETED)
            self.assertEqual(t2.status, TaskStatus.COMPLETED)
            self.assertEqual(worker.completed_task_count, 2)
            self.assertEqual(worker.assigned_task_count, 2)
        finally:
            worker.stop()

    def test_worker_graceful_stop(self) -> None:
        worker = Worker(worker_id="Worker-Stop")
        worker.start()
        self.assertEqual(worker.status, WorkerStatus.IDLE)
        self.assertTrue(worker.is_available)
        worker.stop()
        self.assertEqual(worker.status, WorkerStatus.STOPPED)
        self.assertFalse(worker.is_available)


if __name__ == "__main__":
    unittest.main()
