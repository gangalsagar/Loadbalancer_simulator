"""
Unit tests for Task model and TaskIdGenerator.
"""

import time
import unittest

from task import (
    Task,
    TaskIdGenerator,
    TaskStatus,
    generate_task_id,
    reset_task_id_generator,
)


class TestTaskIdGenerator(unittest.TestCase):
    def setUp(self) -> None:
        reset_task_id_generator(1)

    def test_sequential_ids(self) -> None:
        gen = TaskIdGenerator(prefix="T", start=1)
        self.assertEqual(gen.next_id(), "T001")
        self.assertEqual(gen.next_id(), "T002")
        self.assertEqual(gen.next_id(), "T003")

    def test_reset_generator(self) -> None:
        gen = TaskIdGenerator(prefix="T", start=1)
        gen.next_id()
        gen.next_id()
        gen.reset(1)
        self.assertEqual(gen.next_id(), "T001")


class TestTaskModel(unittest.TestCase):
    def setUp(self) -> None:
        reset_task_id_generator(1)

    def test_default_task_creation(self) -> None:
        t = Task()
        self.assertTrue(t.task_id.startswith("T"))
        self.assertEqual(t.name, "Default Task")
        self.assertEqual(t.duration, 1.0)
        self.assertEqual(t.task_type, "CPU_TASK")
        self.assertEqual(t.status, TaskStatus.PENDING)
        self.assertIsNone(t.started_at)
        self.assertIsNone(t.completed_at)
        self.assertIsNone(t.assigned_worker)
        self.assertIsNone(t.execution_time)

    def test_unique_task_ids(self) -> None:
        t1 = Task(name="Task 1")
        t2 = Task(name="Task 2")
        t3 = Task(name="Task 3")
        self.assertNotEqual(t1.task_id, t2.task_id)
        self.assertNotEqual(t2.task_id, t3.task_id)
        self.assertNotEqual(t1.task_id, t3.task_id)

    def test_task_lifecycle_transitions(self) -> None:
        t = Task(name="Lifecycle Test", duration=0.2)
        self.assertEqual(t.status, TaskStatus.PENDING)

        t.mark_queued("Worker-1")
        self.assertEqual(t.status, TaskStatus.QUEUED)
        self.assertEqual(t.assigned_worker, "Worker-1")

        t.mark_running()
        self.assertEqual(t.status, TaskStatus.RUNNING)
        self.assertIsNotNone(t.started_at)

        time.sleep(0.05)
        t.mark_completed(result="Success")
        self.assertEqual(t.status, TaskStatus.COMPLETED)
        self.assertIsNotNone(t.completed_at)
        self.assertEqual(t.result, "Success")
        self.assertIsNotNone(t.execution_time)
        self.assertGreater(t.execution_time, 0.0)
        self.assertIsNotNone(t.turnaround_time)
        self.assertGreaterEqual(t.turnaround_time, t.execution_time)

    def test_task_failure(self) -> None:
        t = Task(name="Fail Test")
        t.mark_running()
        t.mark_failed("Test error")
        self.assertEqual(t.status, TaskStatus.FAILED)
        self.assertEqual(t.error, "Test error")
        self.assertIsNotNone(t.completed_at)


if __name__ == "__main__":
    unittest.main()

