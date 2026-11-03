"""
comparison.py - Benchmark and comparison utility for Load Balancing algorithms.

Runs controlled test scenarios under identical workloads to measure and compare
performance characteristics of Round Robin vs. Least Connections based on
actual execution metrics.
"""

import logging
import time
from typing import Dict, List, Optional, Tuple

from load_balancer import LoadBalancer
from scheduler import LeastConnectionsScheduler, RoundRobinScheduler
from task import Task, reset_task_id_generator


def run_scenario(
    algorithm_name: str,
    worker_count: int,
    durations: List[float],
    inter_arrival_delay: float = 0.05,
    logger: Optional[logging.Logger] = None,
) -> dict:
    """
    Execute a single scenario run for a specified load balancing algorithm.

    Args:
        algorithm_name: 'round_robin' or 'least_connections'.
        worker_count: Number of backend workers to spawn.
        durations: List of task durations to submit sequentially.
        inter_arrival_delay: Delay in seconds between submitting consecutive tasks.
        logger: Logger instance for recording events.

    Returns:
        Dictionary containing measured operational metrics.
    """
    reset_task_id_generator(1)

    scheduler = (
        RoundRobinScheduler()
        if "round" in algorithm_name.lower()
        else LeastConnectionsScheduler()
    )

    lb = LoadBalancer(
        worker_count=worker_count,
        scheduler=scheduler,
        logger=logger,
        auto_start=True,
    )

    start_time = time.time()
    try:
        # Submit tasks with optional inter-arrival delay
        for i, dur in enumerate(durations, start=1):
            lb.create_and_submit_task(
                name=f"BenchTask-{i}",
                duration=dur,
            )
            if inter_arrival_delay > 0:
                time.sleep(inter_arrival_delay)

        # Wait for all workers to complete all tasks
        lb.wait_for_completion(timeout=30.0)
        total_time = max(0.001, time.time() - start_time)

        # Extract real metrics
        tasks = lb.get_all_tasks()
        completed = [t for t in tasks if t.status.value == "COMPLETED"]
        failed = [t for t in tasks if t.status.value == "FAILED"]

        total_exec = sum((t.execution_time or t.duration) for t in completed)
        avg_exec = total_exec / len(completed) if completed else 0.0

        total_wait = sum(t.waiting_time for t in completed)
        avg_wait = total_wait / len(completed) if completed else 0.0

        throughput = len(completed) / total_time if total_time > 0 else 0.0

        worker_stats = lb.get_worker_status()
        distribution = {ws["worker_id"]: ws["assigned"] for ws in worker_stats}
        completed_per_worker = {ws["worker_id"]: ws["completed"] for ws in worker_stats}

        return {
            "algorithm": scheduler.name,
            "tasks_submitted": len(tasks),
            "tasks_completed": len(completed),
            "tasks_failed": len(failed),
            "total_time": total_time,
            "avg_execution_time": avg_exec,
            "avg_waiting_time": avg_wait,
            "throughput": throughput,
            "distribution": distribution,
            "completed_per_worker": completed_per_worker,
        }
    finally:
        lb.shutdown()


def compare_algorithms(
    worker_count: int = 3,
    durations: Optional[List[float]] = None,
    inter_arrival_delay: float = 0.15,
    logger: Optional[logging.Logger] = None,
) -> Tuple[dict, dict]:
    """
    Run a controlled head-to-head comparison between Round Robin and Least Connections.

    Default scenario:
        1 long task (1.2s) followed by 5 quick tasks (0.2s each).
        Demonstrates how Least Connections avoids queue head-of-line blocking
        while Round Robin assigns work cyclically regardless of ongoing processing.

    Returns:
        Tuple of (round_robin_metrics, least_connections_metrics).
    """
    if durations is None:
        # 1 long task + 5 short tasks
        durations = [1.2, 0.2, 0.2, 0.2, 0.2, 0.2]

    # Run Round Robin
    rr_results = run_scenario(
        algorithm_name="round_robin",
        worker_count=worker_count,
        durations=durations,
        inter_arrival_delay=inter_arrival_delay,
        logger=logger,
    )

    # Allow system threads to settle
    time.sleep(0.1)

    # Run Least Connections under identical conditions
    lc_results = run_scenario(
        algorithm_name="least_connections",
        worker_count=worker_count,
        durations=durations,
        inter_arrival_delay=inter_arrival_delay,
        logger=logger,
    )

    return rr_results, lc_results


def format_comparison_table(rr: dict, lc: dict) -> str:
    """Format comparison results into a clean, human-readable ASCII table."""
    rr_time_str = f"{rr['total_time']:.2f} sec"
    lc_time_str = f"{lc['total_time']:.2f} sec"
    rr_exec_str = f"{rr['avg_execution_time']:.2f} sec"
    lc_exec_str = f"{lc['avg_execution_time']:.2f} sec"
    rr_wait_str = f"{rr['avg_waiting_time']:.2f} sec"
    lc_wait_str = f"{lc['avg_waiting_time']:.2f} sec"
    rr_tput_str = f"{rr['throughput']:.2f} tasks/sec"
    lc_tput_str = f"{lc['throughput']:.2f} tasks/sec"

    lines = [
        "=" * 76,
        "ALGORITHM COMPARISON REPORT",
        "=" * 76,
        f"{'METRIC':<28} {'ROUND ROBIN':<22} {'LEAST CONNECTIONS':<22}",
        "-" * 76,
        f"{'Tasks Submitted':<28} {rr['tasks_submitted']:<22} {lc['tasks_submitted']:<22}",
        f"{'Tasks Completed':<28} {rr['tasks_completed']:<22} {lc['tasks_completed']:<22}",
        f"{'Tasks Failed':<28} {rr['tasks_failed']:<22} {lc['tasks_failed']:<22}",
        f"{'Total Elapsed Time':<28} {rr_time_str:<22} {lc_time_str:<22}",
        f"{'Average Execution Time':<28} {rr_exec_str:<22} {lc_exec_str:<22}",
        f"{'Average Waiting Time':<28} {rr_wait_str:<22} {lc_wait_str:<22}",
        f"{'Throughput':<28} {rr_tput_str:<22} {lc_tput_str:<22}",
        "-" * 76,
        "TASK DISTRIBUTION ACROSS WORKERS:",
    ]

    all_workers = sorted(set(list(rr["distribution"].keys()) + list(lc["distribution"].keys())))
    for w in all_workers:
        rr_count = rr["distribution"].get(w, 0)
        lc_count = lc["distribution"].get(w, 0)
        lines.append(f"  {w:<26} {f'{rr_count} tasks':<22} {f'{lc_count} tasks':<22}")

    lines.append("=" * 76)
    lines.append("ANALYSIS:")
    lines.append("- Round Robin distributes cyclically without inspecting current worker queues.")
    lines.append("- Least Connections routes to workers with minimum active workloads (queued + busy).")
    lines.append("- Actual performance depends on task duration variability and arrival patterns.")
    lines.append("=" * 76)
    return "\n".join(lines)
