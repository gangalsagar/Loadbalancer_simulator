"""
main.py - Interactive CLI interface for Python Load Balancer (Phase 3).

Provides an interactive menu for:
1. Submitting individual tasks
2. Submitting batch tasks
3. Inspecting worker states, workloads, and failure statistics
4. Inspecting individual task details (including interruption and re-routing history)
5. Viewing all submitted tasks
6. Changing the active scheduling algorithm (Round Robin / Least Connections)
7. Viewing operational metrics and running head-to-head comparison benchmarks
8. Simulating worker failure (with active task interruption and queued task re-routing)
9. Recovering a failed worker
10. Viewing failed workers
11. Performing clean shutdown
"""

import argparse
from datetime import datetime
import sys
import time
from typing import Optional

from comparison import compare_algorithms, format_comparison_table
from load_balancer import LoadBalancer
from scheduler import create_scheduler
from task import Task, TaskStatus


def format_timestamp(ts: Optional[float]) -> str:
    """Format an epoch timestamp to human-readable string."""
    if ts is None:
        return "N/A"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def print_header(title: str) -> None:
    """Print a clean section banner."""
    print("\n" + "=" * 40)
    print(title)
    print("=" * 40)


def handle_submit_task(lb: LoadBalancer) -> None:
    """Prompt user for task details and submit to load balancer."""
    try:
        raw_name = input("Enter task name: ").strip()
        name = raw_name if raw_name else "User Task"

        raw_duration = input("Enter duration (seconds): ").strip()
        try:
            duration = float(raw_duration)
            if duration <= 0:
                print("[!] Error: Duration must be greater than 0.")
                return
        except ValueError:
            print("[!] Error: Duration must be a valid number.")
            return

        try:
            task = lb.create_and_submit_task(name=name, duration=duration)
        except RuntimeError as exc:
            print(f"\n[!] Submission failed: {exc}")
            return

        print("\nTask created:", task.task_id)
        print("Assigned to:", task.assigned_worker)
        print("Algorithm:", task.scheduling_algorithm or lb.scheduler_name)
        if task.workload_before_assignment is not None:
            print(f"{task.assigned_worker} workload before assignment: {task.workload_before_assignment}")
            print(f"{task.assigned_worker} workload after assignment: {task.workload_after_assignment}")
        print("Status:", task.status.value)
    except (KeyboardInterrupt, EOFError):
        print("\n[!] Task submission cancelled.")


def handle_submit_multiple(lb: LoadBalancer) -> None:
    """Prompt user for batch count and submit tasks distributed via the active algorithm."""
    try:
        raw_count = input("Number of tasks: ").strip()
        try:
            count = int(raw_count)
            if count <= 0:
                print("[!] Error: Task count must be at least 1.")
                return
        except ValueError:
            print("[!] Error: Task count must be an integer.")
            return

        raw_dur = input("Enter processing duration per task (seconds, default 2.0): ").strip()
        duration = 2.0
        if raw_dur:
            try:
                duration = float(raw_dur)
                if duration <= 0:
                    print("[!] Error: Duration must be greater than 0.")
                    return
            except ValueError:
                print("[!] Error: Duration must be a valid number.")
                return

        print(f"\nSubmitting {count} tasks using {lb.scheduler_name}...")
        submitted_count = 0
        for i in range(1, count + 1):
            task_name = f"Batch-Task-{i}"
            try:
                task = lb.create_and_submit_task(name=task_name, duration=duration)
                submitted_count += 1
                if lb.scheduler_name == "Least Connections":
                    print(f"{task.task_id} -> {task.assigned_worker} (Workload: {task.workload_before_assignment} -> {task.workload_after_assignment})")
                else:
                    print(f"{task.task_id} -> {task.assigned_worker}")
            except RuntimeError as exc:
                print(f"[!] Could not schedule {task_name}: {exc}")
                break

        print(f"\n[OK] Successfully submitted {submitted_count} of {count} tasks.")
    except (KeyboardInterrupt, EOFError):
        print("\n[!] Batch submission cancelled.")


def handle_worker_status(lb: LoadBalancer) -> None:
    """Display real-time state, workload, and failure statistics of all workers."""
    print_header("WORKER STATUS")
    statuses = lb.get_worker_status()
    for ws in statuses:
        avail_str = "YES" if ws.get("available", True) else "NO"
        print(f"\n{ws['worker_id']}")
        print(f"State: {ws['status']}")
        print(f"Available: {avail_str}")
        current = ws["current_task_id"]
        print(f"Current Task: {current if current else 'None'}")
        print(f"Queued Tasks: {ws['queue_size']}")
        print(f"Current Workload: {ws['workload']}")
        print(f"Completed: {ws['completed']} | Failed: {ws['failed']} | Interrupted: {ws.get('interrupted', 0)}")
        print(f"Failures: {ws.get('failures', 0)} | Recoveries: {ws.get('recoveries', 0)}")
        if ws.get("avg_execution_time", 0.0) > 0:
            print(f"Avg Execution Time: {ws['avg_execution_time']:.2f}s")
    print("=" * 40)

    # Show basic metrics summary
    metrics = lb.get_metrics()
    print(f"\nSystem Summary: {metrics['total_submitted']} Submitted | "
          f"{metrics['total_running']} Running | "
          f"{metrics['total_queued']} Queued | "
          f"{metrics['total_completed']} Completed | "
          f"{metrics.get('total_interrupted', 0)} Interrupted | "
          f"Healthy Workers: {metrics['available_worker_count']}/{metrics['worker_count']}")


def handle_task_status(lb: LoadBalancer) -> None:
    """Prompt for a task ID and display detailed status and failure/re-routing history."""
    try:
        task_id = input("Enter Task ID: ").strip()
        if not task_id:
            print("[!] Error: Task ID cannot be empty.")
            return

        task = lb.get_task(task_id)
        if not task:
            print(f"[!] Task '{task_id}' not found.")
            return

        print_header(f"TASK DETAILS - {task.task_id}")
        print(f"Task ID: {task.task_id}")
        print(f"Name: {task.name}")
        print(f"Type: {task.task_type}")
        print(f"Assigned Worker: {task.assigned_worker or 'Unassigned'}")
        if task.was_re_routed:
            print(f"Original Worker: {task.original_worker} (Re-routed after failure, Retries: {task.retry_count})")
        print(f"Scheduling Algorithm: {task.scheduling_algorithm or 'N/A'}")
        if task.workload_before_assignment is not None:
            print(f"Workload at Assignment: {task.workload_before_assignment} (increased to {task.workload_after_assignment})")
        print(f"Status: {task.status.value}")
        print(f"Configured Duration: {task.duration:.2f} seconds")
        print(f"Created: {format_timestamp(task.created_at)}")

        if task.started_at:
            print(f"Started: {format_timestamp(task.started_at)}")
            print(f"Waiting Time: {task.waiting_time:.2f}s")

        if task.status == TaskStatus.COMPLETED:
            print(f"Completed: {format_timestamp(task.completed_at)}")
            exec_time = task.execution_time
            print(f"Execution Time: {exec_time:.2f}s" if exec_time is not None else "Execution Time: N/A")
            turnaround = task.turnaround_time
            print(f"Turnaround Time: {turnaround:.2f}s" if turnaround is not None else "Turnaround Time: N/A")
            if task.result:
                print(f"Result: {task.result}")
        elif task.status == TaskStatus.INTERRUPTED:
            print(f"Interrupted At: {format_timestamp(task.completed_at)}")
            print(f"Interruption Reason: {task.failure_reason or task.error}")
        elif task.status == TaskStatus.FAILED:
            print(f"Failed At: {format_timestamp(task.completed_at)}")
            print(f"Error: {task.error}")
        print("=" * 40)
    except (KeyboardInterrupt, EOFError):
        print("\n[!] Task status query cancelled.")


def handle_all_tasks(lb: LoadBalancer) -> None:
    """Display tabular list of all submitted tasks."""
    tasks = lb.get_all_tasks()
    if not tasks:
        print("\nNo tasks have been submitted yet.")
        return

    print("\n" + "=" * 80)
    print(f"{'ID':<8} {'NAME':<20} {'WORKER':<12} {'STATUS':<14} {'DURATION':<10} {'EXEC TIME':<10}")
    print("-" * 80)
    for t in tasks:
        exec_str = f"{t.execution_time:.2f}s" if t.execution_time is not None else "--"
        print(f"{t.task_id:<8} {t.name[:19]:<20} {(t.assigned_worker or 'None'):<12} "
              f"{t.status.value:<14} {f'{t.duration:.1f}s':<10} {exec_str:<10}")
    print("=" * 80)


def handle_change_algorithm(lb: LoadBalancer) -> None:
    """Allow user to switch the active load balancing algorithm dynamically."""
    print_header("CHANGE SCHEDULING ALGORITHM")
    print(f"Current Algorithm: {lb.scheduler_name}\n")
    print("Available Algorithms:")
    print("  1. Round Robin")
    print("  2. Least Connections (Least Workload)")
    print()

    try:
        choice = input("Select algorithm [1-2]: ").strip()
        if choice in ("1", "round_robin", "rr"):
            new_sched = lb.set_algorithm("round_robin")
            print(f"\n[OK] Scheduling algorithm switched to: {new_sched.name}")
        elif choice in ("2", "least_connections", "lc"):
            new_sched = lb.set_algorithm("least_connections")
            print(f"\n[OK] Scheduling algorithm switched to: {new_sched.name}")
        else:
            print("\n[!] Invalid choice. Algorithm unchanged.")
    except (KeyboardInterrupt, EOFError):
        print("\n[!] Algorithm change cancelled.")


def handle_metrics_and_comparison(lb: LoadBalancer) -> None:
    """Display operational metrics and provide option to run controlled comparison."""
    print_header("SYSTEM METRICS & ALGORITHM EVALUATION")
    m = lb.get_metrics()
    print(f"Active Algorithm:       {m['scheduler_name']}")
    print(f"Total Tasks Submitted:  {m['total_submitted']}")
    print(f"Total Tasks Completed:  {m['total_completed']}")
    print(f"Total Tasks Failed:     {m['total_failed']}")
    print(f"Total Interrupted:      {m.get('total_interrupted', 0)}")
    print(f"Total Re-routed:        {m.get('total_re_routed', 0)}")
    print(f"Worker Failures:        {m.get('total_worker_failures', 0)}")
    print(f"Worker Recoveries:      {m.get('total_worker_recoveries', 0)}")
    print(f"Tasks Currently Running:{m['total_running']}")
    print(f"Tasks Currently Queued: {m['total_queued']}")
    print(f"Total Execution Time:   {m['total_execution_time']:.2f}s")
    print(f"Average Execution Time: {m['avg_execution_time']:.2f}s")
    print(f"Average Waiting Time:   {m['avg_waiting_time']:.2f}s")
    print(f"Throughput:             {m['throughput']:.2f} tasks/s")
    print(f"Healthy Workers:        {m['available_worker_count']} / {m['worker_count']}")
    print("\nWorker Details:")
    for ws in m["worker_statuses"]:
        print(f"  {ws['worker_id']:<10} State: {ws['status']:<8} Available: {'YES' if ws.get('available') else 'NO':<4} "
              f"Workload: {ws['workload']:<3} Completed: {ws['completed']:<3} Failures: {ws.get('failures', 0)}")
    print("=" * 40)

    try:
        run_comp = input("\nRun head-to-head algorithm comparison benchmark? (y/n, default n): ").strip().lower()
        if run_comp in ("y", "yes"):
            print("\nRunning controlled comparison benchmark (Round Robin vs Least Connections)...")
            print("Executing identical workloads across both algorithms...")
            rr_res, lc_res = compare_algorithms(worker_count=len(lb.workers))
            print("\n" + format_comparison_table(rr_res, lc_res))
    except (KeyboardInterrupt, EOFError):
        pass


def handle_simulate_failure(lb: LoadBalancer) -> None:
    """Prompt user to intentionally fail a healthy worker."""
    print_header("SIMULATE WORKER FAILURE")
    available_workers = lb.get_available_workers()
    if not available_workers:
        print("[!] All workers are already in FAILED or STOPPED state.")
        return

    print("Active/Healthy Workers:")
    for i, w in enumerate(available_workers, start=1):
        task_str = f"Task: {w.current_task.task_id}" if w.current_task else "Task: None"
        print(f"  {i}. {w.worker_id} (State: {w.status.value}, Workload: {w.get_workload()}, {task_str})")

    try:
        choice = input("\nEnter worker ID or number to fail (e.g. Worker-2 or 2): ").strip()
        if not choice:
            print("[!] Operation cancelled.")
            return

        target_id = None
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(available_workers):
                target_id = available_workers[idx].worker_id
        else:
            for w in available_workers:
                if w.worker_id.lower() == choice.lower():
                    target_id = w.worker_id
                    break

        if not target_id:
            print(f"[!] Invalid worker selection: '{choice}'.")
            return

        print(f"\nTriggering failure on {target_id}...")
        lb.simulate_worker_failure(target_id)
        print(f"[OK] {target_id} has been marked as FAILED.")
        print(f"Active task on {target_id} (if any) was marked INTERRUPTED.")
        print(f"All queued unexecuted tasks on {target_id} were drained and re-routed to healthy workers.")
    except (KeyboardInterrupt, EOFError):
        print("\n[!] Worker failure simulation cancelled.")


def handle_recover_worker(lb: LoadBalancer) -> None:
    """Prompt user to recover a failed worker."""
    print_header("RECOVER FAILED WORKER")
    failed_workers = lb.get_failed_workers()
    if not failed_workers:
        print("No workers are currently in FAILED state.")
        return

    print("Failed Workers Available for Recovery:")
    for i, w in enumerate(failed_workers, start=1):
        print(f"  {i}. {w.worker_id} (Failures: {w.failure_count}, Recoveries: {w.recovery_count})")

    try:
        choice = input("\nEnter worker ID or number to recover (e.g. Worker-2 or 1): ").strip()
        if not choice:
            print("[!] Operation cancelled.")
            return

        target_id = None
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(failed_workers):
                target_id = failed_workers[idx].worker_id
        else:
            for w in failed_workers:
                if w.worker_id.lower() == choice.lower():
                    target_id = w.worker_id
                    break

        if not target_id:
            print(f"[!] Invalid worker selection: '{choice}'.")
            return

        print(f"\nRestoring {target_id}...")
        lb.recover_worker(target_id)
        print(f"[OK] {target_id} has been restored to IDLE state and is accepting new tasks.")
    except (KeyboardInterrupt, EOFError):
        print("\n[!] Worker recovery cancelled.")


def handle_view_failed_workers(lb: LoadBalancer) -> None:
    """Display list of workers currently in FAILED state."""
    print_header("FAILED WORKERS")
    failed = lb.get_failed_workers()
    if not failed:
        print("No workers are currently in FAILED state. All workers are healthy.")
        return

    for w in failed:
        info = w.get_status_dict()
        print(f"\n{info['worker_id']}")
        print(f"State: {info['status']}")
        print(f"Available: {'YES' if info['available'] else 'NO'}")
        print(f"Failure Count: {info['failures']}")
        print(f"Recovery Count: {info['recoveries']}")
        print(f"Interrupted Tasks: {info['interrupted']}")
    print("=" * 40)


def run_demo(lb: LoadBalancer) -> None:
    """Automated demonstration showing Round Robin and Least Connections in action."""
    print_header("AUTOMATED DEMONSTRATION - PHASE 2")

    # 1. Round Robin demo
    print("\n--- Part 1: Round Robin Distribution ---")
    lb.set_algorithm("round_robin")
    print(f"Active Algorithm: {lb.scheduler_name}")
    print("Submitting 6 tasks with mixed durations...")
    durations = [1.2, 0.3, 0.3, 0.3, 0.3, 0.3]
    for i, dur in enumerate(durations, start=1):
        lb.create_and_submit_task(name=f"RR-Task-{i}", duration=dur)
        time.sleep(0.05)

    print("\nInspecting worker workloads during execution:")
    time.sleep(0.15)
    handle_worker_status(lb)

    print("\nWaiting for Part 1 tasks to finish...")
    lb.wait_for_completion()

    # 2. Least Connections demo
    print("\n--- Part 2: Least Connections Distribution ---")
    lb.set_algorithm("least_connections")
    print(f"Active Algorithm: {lb.scheduler_name}")
    print("Submitting identical mixed duration pattern...")
    for i, dur in enumerate(durations, start=1):
        lb.create_and_submit_task(name=f"LC-Task-{i}", duration=dur)
        time.sleep(0.05)

    print("\nInspecting worker workloads during execution:")
    time.sleep(0.15)
    handle_worker_status(lb)

    print("\nWaiting for Part 2 tasks to finish...")
    lb.wait_for_completion()

    print("\n--- Final Summary Table ---")
    handle_all_tasks(lb)

    print("\n--- Controlled Head-to-Head Comparison Benchmark ---")
    rr_res, lc_res = compare_algorithms(worker_count=len(lb.workers))
    print("\n" + format_comparison_table(rr_res, lc_res))


def run_failure_demo(lb: LoadBalancer) -> None:
    """
    Automated Phase 3 demonstration showing real worker failure, task interruption,
    queued task re-routing, scheduler exclusion, and successful recovery.
    """
    print_header("AUTOMATED FAULT TOLERANCE DEMONSTRATION - PHASE 3")
    print("Scenario: Submitting tasks, failing Worker-2 mid-run, re-routing tasks,")
    print("submitting new tasks avoiding Worker-2, and recovering Worker-2.\n")

    # 1. Submit batch tasks
    print("1. Submitting 5 tasks to 3 workers...")
    t1 = lb.create_and_submit_task("Task-W1", duration=0.8)
    t2 = lb.create_and_submit_task("Task-W2-Long", duration=1.5)
    t3 = lb.create_and_submit_task("Task-W3", duration=0.8)
    t4 = lb.create_and_submit_task("Task-Queued-W1", duration=0.4)
    t5 = lb.create_and_submit_task("Task-Queued-W2", duration=0.4)

    time.sleep(0.1)
    print("\nInitial Worker Status before failure:")
    handle_worker_status(lb)

    # 2. Simulate failure on Worker-2
    print("\n2. Failing Worker-2 while it is actively processing Task-W2-Long...")
    lb.simulate_worker_failure("Worker-2")

    print("\nWorker Status immediately after failure of Worker-2:")
    handle_worker_status(lb)

    # 3. Submit additional tasks while Worker-2 is failed
    print("\n3. Submitting 3 new tasks while Worker-2 is FAILED...")
    for i in range(1, 4):
        t = lb.create_and_submit_task(f"NewTask-{i}", duration=0.3)
        print(f"  {t.task_id} -> assigned to {t.assigned_worker} (skipping failed Worker-2)")

    # 4. Recover Worker-2
    time.sleep(0.2)
    print("\n4. Recovering Worker-2...")
    lb.recover_worker("Worker-2")
    print("Worker-2 recovered. Status after recovery:")
    handle_worker_status(lb)

    # 5. Submit task after recovery
    print("\n5. Submitting task after Worker-2 recovery...")
    t_after = lb.create_and_submit_task("Post-Recovery-Task", duration=0.3)
    print(f"  {t_after.task_id} -> assigned to {t_after.assigned_worker}")

    print("\nWaiting for all tasks to complete...")
    lb.wait_for_completion()

    print("\nFinal Task Summary Table:")
    handle_all_tasks(lb)

    print("\nFinal System Metrics:")
    m = lb.get_metrics()
    print(f"Total Submitted:     {m['total_submitted']}")
    print(f"Total Completed:     {m['total_completed']}")
    print(f"Total Interrupted:   {m['total_interrupted']}")
    print(f"Tasks Re-routed:     {m['total_re_routed']}")
    print(f"Worker Failures:     {m['total_worker_failures']}")
    print(f"Worker Recoveries:   {m['total_worker_recoveries']}")
    print("\n[OK] Phase 3 Fault Tolerance Demo completed successfully.")


def main() -> None:
    """CLI Entry point."""
    parser = argparse.ArgumentParser(description="Functional Python Load Balancer (Phase 3)")
    parser.add_argument("--workers", type=int, default=3, help="Number of backend workers (default: 3)")
    parser.add_argument(
        "--algorithm",
        type=str,
        default="round_robin",
        choices=["round_robin", "least_connections", "rr", "lc"],
        help="Initial load balancing algorithm (default: round_robin)",
    )
    parser.add_argument("--demo", action="store_true", help="Run automated demonstration and exit")
    parser.add_argument("--demo-failure", action="store_true", help="Run automated Phase 3 fault tolerance demonstration and exit")
    parser.add_argument("--compare", action="store_true", help="Run head-to-head algorithm comparison benchmark and exit")
    args = parser.parse_args()

    if args.compare:
        print("\nExecuting controlled algorithm comparison benchmark...")
        rr_res, lc_res = compare_algorithms(worker_count=args.workers)
        print("\n" + format_comparison_table(rr_res, lc_res))
        return

    initial_scheduler = create_scheduler(args.algorithm)
    lb = LoadBalancer(worker_count=args.workers, scheduler=initial_scheduler)

    if args.demo:
        try:
            run_demo(lb)
        finally:
            print("\nShutting down workers...")
            lb.shutdown()
            print("Done.")
        return

    if args.demo_failure:
        try:
            run_failure_demo(lb)
        finally:
            print("\nShutting down workers...")
            lb.shutdown()
            print("Done.")
        return

    try:
        while True:
            print("\n========================================")
            print("PYTHON LOAD BALANCER")
            print("====================")
            print(f"Workers: {len(lb.workers)}")
            print(f"Current Scheduling Algorithm: {lb.scheduler_name.upper()}")
            print(f"Healthy Workers: {len(lb.get_available_workers())}/{len(lb.workers)}")
            print()
            print("1. Submit Task")
            print("2. Submit Multiple Tasks")
            print("3. View Worker Status")
            print("4. View Task Status")
            print("5. View All Tasks")
            print("6. Change Scheduling Algorithm")
            print("7. View Metrics & Compare Algorithms")
            print("8. Simulate Worker Failure")
            print("9. Recover Worker")
            print("10. View Failed Workers")
            print("11. Exit")
            print("========================================")

            try:
                choice = input("Choose option: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nExiting...")
                break

            if choice == "1":
                handle_submit_task(lb)
            elif choice == "2":
                handle_submit_multiple(lb)
            elif choice == "3":
                handle_worker_status(lb)
            elif choice == "4":
                handle_task_status(lb)
            elif choice == "5":
                handle_all_tasks(lb)
            elif choice == "6":
                handle_change_algorithm(lb)
            elif choice == "7":
                handle_metrics_and_comparison(lb)
            elif choice == "8":
                handle_simulate_failure(lb)
            elif choice == "9":
                handle_recover_worker(lb)
            elif choice == "10":
                handle_view_failed_workers(lb)
            elif choice == "11":
                print("\nInitiating graceful shutdown of backend workers...")
                break
            else:
                print("\n[!] Invalid choice. Please enter a number between 1 and 11.")
    finally:
        lb.shutdown()
        print("[OK] All backend worker threads stopped cleanly.")
        print("Goodbye!")


if __name__ == "__main__":
    main()
