"""
tests/test_fault_tolerance.py - Comprehensive Unit, Integration, and Concurrency
Tests for Phase 3: Fault Tolerance and Synchronization.
"""

import logging
import threading
import time
import unittest

from load_balancer import LoadBalancer
from scheduler import LeastConnectionsScheduler, RoundRobinScheduler
from server import Worker, WorkerStatus
from task import Task, TaskStatus, reset_task_id_generator


class TestWorkerFaultTolerance(unittest.TestCase):
    def test_worker_failure_state(self) -> None:
        worker = Worker("Worker-Fail-Test")
        worker.start()
        try:
            self.assertEqual(worker.status, WorkerStatus.IDLE)
            self.assertTrue(worker.is_available)
            self.assertEqual(worker.failure_count, 0)

            worker.fail()
            self.assertEqual(worker.status, WorkerStatus.FAILED)
            self.assertFalse(worker.is_available)
            self.assertEqual(worker.failure_count, 1)

            # Calling fail again should be idempotent
            worker.fail()
            self.assertEqual(worker.failure_count, 1)
        finally:
            worker.stop()

    def test_failed_worker_rejects_new_tasks(self) -> None:
        worker = Worker("Worker-Reject-Test")
        worker.start()
        try:
            worker.fail()
            t = Task("Rejected Task", duration=0.1)
            with self.assertRaises(RuntimeError):
                worker.add_task(t)
        finally:
            worker.stop()

    def test_active_task_interrupted_on_failure(self) -> None:
        worker = Worker("Worker-Interrupt-Test")
        worker.start()
        try:
            task = Task("Long Task", duration=1.0)
            worker.add_task(task)

            # Allow worker thread to pick up and start task
            time.sleep(0.05)
            self.assertEqual(task.status, TaskStatus.RUNNING)

            # Fail the worker while task is actively executing
            worker.fail()

            # Worker thread should detect failure and mark task INTERRUPTED
            time.sleep(0.1)
            self.assertEqual(task.status, TaskStatus.INTERRUPTED)
            self.assertIsNotNone(task.interrupted_at)
            self.assertIn("failure", task.failure_reason.lower())
            self.assertEqual(worker.interrupted_task_count, 1)
            self.assertEqual(worker.completed_task_count, 0)
        finally:
            worker.stop()

    def test_drain_queued_tasks(self) -> None:
        worker = Worker("Worker-Drain-Test")
        # Do not start worker thread so tasks stay in queue
        t1 = Task(name="Q1")
        t2 = Task(name="Q2")
        t3 = Task(name="Q3")
        worker.add_task(t1)
        worker.add_task(t2)
        worker.add_task(t3)

        self.assertEqual(worker.task_queue.qsize(), 3)
        drained = worker.drain_queued_tasks()
        self.assertEqual(len(drained), 3)
        self.assertEqual(worker.task_queue.qsize(), 0)
        self.assertEqual([t.name for t in drained], ["Q1", "Q2", "Q3"])

    def test_worker_recovery_lifecycle(self) -> None:
        worker = Worker("Worker-Recovery-Test")
        worker.start()
        try:
            worker.fail()
            self.assertEqual(worker.status, WorkerStatus.FAILED)
            self.assertFalse(worker.is_available)

            worker.recover()
            self.assertEqual(worker.status, WorkerStatus.IDLE)
            self.assertTrue(worker.is_available)
            self.assertEqual(worker.recovery_count, 1)

            # Verify it can execute tasks again after recovery
            task = Task("Post-Recovery-Task", duration=0.05)
            worker.add_task(task)
            worker.task_queue.join()

            self.assertEqual(task.status, TaskStatus.COMPLETED)
            self.assertEqual(worker.completed_task_count, 1)
        finally:
            worker.stop()

    def test_cannot_recover_non_failed_worker(self) -> None:
        worker = Worker("Worker-NonFailed")
        worker.start()
        try:
            with self.assertRaises(RuntimeError):
                worker.recover()
        finally:
            worker.stop()


class TestSchedulerFaultTolerance(unittest.TestCase):
    def setUp(self) -> None:
        self.w1 = Worker("Worker-1")
        self.w2 = Worker("Worker-2")
        self.w3 = Worker("Worker-3")
        self.workers = [self.w1, self.w2, self.w3]
        for w in self.workers:
            w.start()

    def tearDown(self) -> None:
        for w in self.workers:
            w.stop()

    def test_round_robin_skips_failed_workers(self) -> None:
        scheduler = RoundRobinScheduler()

        # Fail Worker-2
        self.w2.fail()
        self.assertFalse(self.w2.is_available)

        # Submit 4 selections
        selected = [scheduler.select_worker(self.workers).worker_id for _ in range(4)]

        # Must strictly alternate between Worker-1 and Worker-3, never Worker-2
        self.assertEqual(selected, ["Worker-1", "Worker-3", "Worker-1", "Worker-3"])
        self.assertNotIn("Worker-2", selected)

    def test_least_connections_skips_failed_workers(self) -> None:
        scheduler = LeastConnectionsScheduler()

        # Worker-1 has 1 queued task
        self.w1.task_queue.put(Task("W1-Q"))
        # Worker-2 has 0 queued tasks, but is FAILED
        self.w2.fail()
        # Worker-3 has 2 queued tasks
        self.w3.task_queue.put(Task("W3-Q1"))
        self.w3.task_queue.put(Task("W3-Q2"))

        # Worker-2 has the lowest workload (0) but is FAILED!
        # Scheduler must skip Worker-2 and choose Worker-1 (workload 1)
        selected = scheduler.select_worker(self.workers)
        self.assertEqual(selected.worker_id, "Worker-1")

    def test_all_workers_failed_raises_error(self) -> None:
        rr = RoundRobinScheduler()
        lc = LeastConnectionsScheduler()

        for w in self.workers:
            w.fail()

        with self.assertRaises(RuntimeError):
            rr.select_worker(self.workers)

        with self.assertRaises(RuntimeError):
            lc.select_worker(self.workers)


class TestLoadBalancerFaultTolerance(unittest.TestCase):
    def setUp(self) -> None:
        reset_task_id_generator(1)
        null_logger = logging.getLogger("TestLBFault")
        null_logger.addHandler(logging.NullHandler())
        self.lb = LoadBalancer(worker_count=3, logger=null_logger, auto_start=True)

    def tearDown(self) -> None:
        self.lb.shutdown()

    def test_simulate_worker_failure_and_task_rerouting(self) -> None:
        # Submit tasks: Worker-2 gets a long task (0.6s), plus 2 queued tasks (0.1s each)
        w2 = self.lb.get_worker_by_id("Worker-2")

        # Fill W1, W2, W3 so Round Robin sends next tasks sequentially
        t_w1 = self.lb.create_and_submit_task("W1-1", duration=0.1)
        t_w2_active = self.lb.create_and_submit_task("W2-Active", duration=0.6)
        t_w3 = self.lb.create_and_submit_task("W3-1", duration=0.1)

        # Enqueue more tasks to W2
        t_w2_q1 = self.lb.create_and_submit_task("W2-Q1", duration=0.1)  # goes to W1
        t_w2_q2 = self.lb.create_and_submit_task("W2-Q2", duration=0.1)  # goes to W2
        t_w2_q3 = self.lb.create_and_submit_task("W2-Q3", duration=0.1)  # goes to W3

        time.sleep(0.05)  # Ensure W2 is actively running t_w2_active

        # Fail Worker-2
        failed_worker = self.lb.simulate_worker_failure("Worker-2")
        self.assertEqual(failed_worker.status, WorkerStatus.FAILED)
        self.assertEqual(self.lb.total_worker_failures, 1)

        # Wait for all remaining tasks to settle
        self.assertTrue(self.lb.wait_for_completion(timeout=5.0))

        # Check: active task on Worker-2 must be INTERRUPTED
        self.assertEqual(t_w2_active.status, TaskStatus.INTERRUPTED)

        # Check: queued task on Worker-2 (t_w2_q2) must have been re-routed and COMPLETED
        self.assertTrue(t_w2_q2.was_re_routed)
        self.assertEqual(t_w2_q2.status, TaskStatus.COMPLETED)
        self.assertIn(t_w2_q2.assigned_worker, ["Worker-1", "Worker-3"])

        # Check metrics
        m = self.lb.get_metrics()
        self.assertEqual(m["total_interrupted"], 1)
        self.assertGreaterEqual(m["total_re_routed"], 1)
        self.assertEqual(m["total_worker_failures"], 1)

    def test_recover_worker_restores_scheduling(self) -> None:
        self.lb.simulate_worker_failure("Worker-2")
        self.assertIn("Worker-2", [w.worker_id for w in self.lb.get_failed_workers()])

        # Submit task while Worker-2 is failed
        t1 = self.lb.create_and_submit_task("While-Down-1", duration=0.05)
        self.assertNotEqual(t1.assigned_worker, "Worker-2")

        # Recover Worker-2
        recovered = self.lb.recover_worker("Worker-2")
        self.assertEqual(recovered.status, WorkerStatus.IDLE)
        self.assertTrue(recovered.is_available)
        self.assertEqual(len(self.lb.get_failed_workers()), 0)

        # Submit tasks after recovery: Worker-2 should receive tasks again
        self.lb.set_algorithm("least_connections")
        t2 = self.lb.create_and_submit_task("After-Recovery", duration=0.05)
        self.assertTrue(self.lb.wait_for_completion(timeout=5.0))
        self.assertEqual(t2.status, TaskStatus.COMPLETED)


class TestConcurrencyAndStress(unittest.TestCase):
    def setUp(self) -> None:
        reset_task_id_generator(1)
        null_logger = logging.getLogger("TestStress")
        null_logger.addHandler(logging.NullHandler())
        self.lb = LoadBalancer(worker_count=3, logger=null_logger, auto_start=True)

    def tearDown(self) -> None:
        self.lb.shutdown()

    def test_concurrent_failure_and_submissions(self) -> None:
        """
        Race condition prevention test:
        Multiple threads submit tasks while a background thread triggers
        worker failure and recovery concurrently.
        """
        errors = []

        def client_worker(count: int, thread_id: int):
            for i in range(count):
                try:
                    self.lb.create_and_submit_task(
                        name=f"RaceTask-{thread_id}-{i}",
                        duration=0.02,
                    )
                except Exception as exc:
                    errors.append(exc)
                time.sleep(0.01)

        def chaos_worker():
            time.sleep(0.03)
            try:
                self.lb.simulate_worker_failure("Worker-2")
                time.sleep(0.05)
                self.lb.recover_worker("Worker-2")
            except Exception as exc:
                errors.append(exc)

        # Start 3 client threads and 1 chaos thread
        t1 = threading.Thread(target=client_worker, args=(5, 1))
        t2 = threading.Thread(target=client_worker, args=(5, 2))
        t3 = threading.Thread(target=client_worker, args=(5, 3))
        t_chaos = threading.Thread(target=chaos_worker)

        for t in [t1, t2, t3, t_chaos]:
            t.start()
        for t in [t1, t2, t3, t_chaos]:
            t.join()

        # Wait for all tasks to complete/interrupt
        self.assertTrue(self.lb.wait_for_completion(timeout=10.0))

        # No uncaught exceptions or deadlocks
        self.assertEqual(len(errors), 0, f"Encountered unexpected errors during race: {errors}")

        tasks = self.lb.get_all_tasks()
        self.assertEqual(len(tasks), 15)
        # Every single task must be accounted for in a valid terminal state
        for task in tasks:
            self.assertIn(task.status, [TaskStatus.COMPLETED, TaskStatus.INTERRUPTED])

    def test_stress_fault_tolerance_accounting(self) -> None:
        """
        Submit 30 tasks with varying durations.
        Fail a worker mid-execution, re-route tasks, recover the worker,
        submit more tasks, and verify that 100% of tasks are accounted for
        with zero duplicate completions and zero silent drops.
        """
        # Batch 1: 15 tasks
        for i in range(1, 16):
            self.lb.create_and_submit_task(f"Stress-1-{i}", duration=0.03)

        time.sleep(0.04)

        # Trigger failure on Worker-1
        self.lb.simulate_worker_failure("Worker-1")

        # Batch 2: 10 tasks while Worker-1 is failed
        for i in range(1, 11):
            self.lb.create_and_submit_task(f"Stress-2-{i}", duration=0.02)

        time.sleep(0.05)

        # Recover Worker-1
        self.lb.recover_worker("Worker-1")

        # Batch 3: 5 tasks after recovery
        for i in range(1, 6):
            self.lb.create_and_submit_task(f"Stress-3-{i}", duration=0.02)

        # Wait for completion
        self.assertTrue(self.lb.wait_for_completion(timeout=10.0))

        tasks = self.lb.get_all_tasks()
        self.assertEqual(len(tasks), 30)

        completed_count = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED)
        interrupted_count = sum(1 for t in tasks if t.status == TaskStatus.INTERRUPTED)

        self.assertEqual(completed_count + interrupted_count, 30)
        self.assertGreater(completed_count, 25)

        # Verify no task completed twice
        completed_ids = set()
        for t in tasks:
            if t.status == TaskStatus.COMPLETED:
                self.assertNotIn(t.task_id, completed_ids)
                completed_ids.add(t.task_id)


if __name__ == "__main__":
    unittest.main()
