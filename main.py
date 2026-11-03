"""
main.py - Interactive CLI interface for Python Load Balancer (Phase 1).

Provides an interactive menu for:
1. Submitting individual tasks
2. Submitting batch tasks
3. Inspecting worker states
4. Inspecting individual task details
5. Viewing all submitted tasks
6. Performing clean shutdown
"""

import argparse
from datetime import datetime
import sys
import time
from typing import Optional

from load_balancer import LoadBalancer
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

        task = lb.create_and_submit_task(name=name, duration=duration)
        print("\nTask created:", task.task_id)
        print("Assigned to:", task.assigned_worker)
        print("Status:", task.status.value)
    except (KeyboardInterrupt, EOFError):
        print("\n[!] Task submission cancelled.")


def handle_submit_multiple(lb: LoadBalancer) -> None:
    """Prompt user for batch count and submit tasks distributed via Round Robin."""
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

        print("\nSubmitting tasks...")
        for i in range(1, count + 1):
            task_name = f"Batch-Task-{i}"
            task = lb.create_and_submit_task(name=task_name, duration=duration)
            print(f"{task.task_id} -> {task.assigned_worker}")
        print(f"\n[OK] Successfully submitted {count} tasks.")
    except (KeyboardInterrupt, EOFError):
        print("\n[!] Batch submission cancelled.")


def handle_worker_status(lb: LoadBalancer) -> None:
    """Display real-time state of all workers."""
    print_header("WORKER STATUS")
    statuses = lb.get_worker_status()
    for ws in statuses:
        print(f"\n{ws['worker_id']}")
        print(f"Status: {ws['status']}")
        current = ws["current_task_id"]
        print(f"Current Task: {current if current else 'None'}")
        print(f"Queue Size: {ws['queue_size']}")
        print(f"Completed: {ws['completed']}")
    print("=" * 40)

    # Show basic metrics summary
    metrics = lb.get_metrics()
    print(f"\nSystem Summary: {metrics['total_submitted']} Submitted | "
          f"{metrics['total_running']} Running | "
          f"{metrics['total_queued']} Queued | "
          f"{metrics['total_completed']} Completed")


def handle_task_status(lb: LoadBalancer) -> None:
    """Prompt for a task ID and display detailed status."""
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

    print("\n" + "=" * 76)
    print(f"{'ID':<8} {'NAME':<20} {'WORKER':<14} {'STATUS':<14} {'DURATION':<10} {'EXEC TIME':<10}")
    print("-" * 76)
    for t in tasks:
        exec_str = f"{t.execution_time:.2f}s" if t.execution_time is not None else "--"
        print(f"{t.task_id:<8} {t.name[:19]:<20} {(t.assigned_worker or 'None'):<14} "
              f"{t.status.value:<14} {f'{t.duration:.1f}s':<10} {exec_str:<10}")
    print("=" * 76)


def run_demo(lb: LoadBalancer) -> None:
    """Automated demonstration showing Round Robin distribution and concurrency."""
    print_header("AUTOMATED DEMONSTRATION")
    print("Submitting 6 tasks to demonstrate Round Robin across 3 workers...")
    durations = [2.0, 2.0, 2.0, 1.5, 1.5, 1.5]
    for i, dur in enumerate(durations, start=1):
        lb.create_and_submit_task(name=f"DemoTask-{i}", duration=dur)
        time.sleep(0.05)

    print("\nTasks submitted. Inspecting worker status during concurrent execution:")
    time.sleep(0.5)
    handle_worker_status(lb)

    print("\nWaiting for all tasks to complete...")
    # Wait until all tasks are completed
    while True:
        metrics = lb.get_metrics()
        if metrics["total_completed"] == metrics["total_submitted"]:
            break
        time.sleep(0.5)

    print("\nAll tasks completed! Final worker status:")
    handle_worker_status(lb)

    print("\nAll tasks table:")
    handle_all_tasks(lb)


def main() -> None:
    """CLI Entry point."""
    parser = argparse.ArgumentParser(description="Functional Python Load Balancer (Phase 1)")
    parser.add_argument("--workers", type=int, default=3, help="Number of backend workers (default: 3)")
    parser.add_argument("--demo", action="store_true", help="Run automated demonstration and exit")
    args = parser.parse_args()

    lb = LoadBalancer(worker_count=args.workers)

    if args.demo:
        try:
            run_demo(lb)
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
            print("Algorithm: Round Robin")
            print()
            print("1. Submit Task")
            print("2. Submit Multiple Tasks")
            print("3. View Worker Status")
            print("4. View Task Status")
            print("5. View All Tasks")
            print("6. Exit")
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
                print("\nInitiating graceful shutdown of backend workers...")
                break
            else:
                print("\n[!] Invalid choice. Please enter a number between 1 and 6.")
    finally:
        lb.shutdown()
        print("[OK] All backend worker threads stopped cleanly.")
        print("Goodbye!")


if __name__ == "__main__":
    main()
