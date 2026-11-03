"""
app.py - Phase 4 Web Dashboard (Flask API layer).

This module wraps the existing LoadBalancer backend with a REST API
and serves the single-page monitoring dashboard. ALL business logic
lives in load_balancer.py, server.py, scheduler.py, and task.py.
Flask is a thin HTTP adapter only -- no logic is duplicated here.

Usage:
    python app.py
    Then open: http://127.0.0.1:5000
"""

import logging
import os
import sys
import time

from flask import Flask, jsonify, render_template, request

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so imports work when running directly
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from load_balancer import LoadBalancer  # noqa: E402

# ---------------------------------------------------------------------------
# Flask application
# ---------------------------------------------------------------------------
app = Flask(__name__)

# ---------------------------------------------------------------------------
# Global LoadBalancer singleton
# Instantiated once at module load; shared across all HTTP requests.
# Uses a NullHandler logger to suppress console noise in web mode.
# ---------------------------------------------------------------------------
_null_logger = logging.getLogger("lb_web")
_null_logger.addHandler(logging.NullHandler())
_null_logger.propagate = False

lb: LoadBalancer = LoadBalancer(worker_count=3, logger=_null_logger)

# Simulation state for task preparation mode
_simulation_state = {
    "running": False,
    "prepared_tasks": [],
    "simulation_start_time": None,
}

# Export for testing
__all__ = ["app", "lb", "_simulation_state"]

# ---------------------------------------------------------------------------
# Helper: task -> JSON-serialisable dict
# ---------------------------------------------------------------------------

def serialize_task(t) -> dict:
    """Convert a Task instance to a plain dictionary for JSON responses."""
    return {
        "id": t.task_id,
        "name": t.name,
        "status": t.status.value,
        "duration": t.duration,
        "arrival_time": t.arrival_time,
        "task_type": t.task_type,
        "worker": t.assigned_worker,
        "original_worker": t.original_worker,
        "rerouted": t.was_re_routed,
        "retry_count": t.retry_count,
        "algorithm": t.scheduling_algorithm,
        "created_at": t.created_at,
        "started_at": t.started_at,
        "completed_at": t.completed_at,
        "execution_time": t.execution_time,
        "waiting_time": t.waiting_time,
        "interrupted_at": t.interrupted_at,
        "failure_reason": t.failure_reason,
        "result": t.result,
        "error": t.error,
        "workload_before": t.workload_before_assignment,
        "workload_after": t.workload_after_assignment,
    }


# ---------------------------------------------------------------------------
# Routes: HTML pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Serve the landing page."""
    return render_template("landing.html")


@app.route("/simulator")
def simulator():
    """Serve the simulator workspace."""
    return render_template("simulator.html")


@app.route("/dashboard")
def dashboard():
    """Serve the legacy dashboard (Phase 4 original)."""
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Routes: System status
# ---------------------------------------------------------------------------

@app.route("/api/status")
def api_status():
    """
    Lightweight system overview.
    Returns a subset of metrics suitable for the header stat cards.
    """
    m = lb.get_metrics()
    return jsonify({
        "total_workers": m["worker_count"],
        "active_workers": m["available_worker_count"],
        "failed_workers": m["failed_worker_count"],
        "total_submitted": m["total_submitted"],
        "total_completed": m["total_completed"],
        "total_running": m["total_running"],
        "total_queued": m["total_queued"],
        "total_failed": m["total_failed"],
        "total_interrupted": m["total_interrupted"],
        "total_re_routed": m["total_re_routed"],
        "scheduler_name": m["scheduler_name"],
        "throughput": round(m["throughput"], 4),
        "elapsed_time": round(m["elapsed_time"], 2),
    })


# ---------------------------------------------------------------------------
# Routes: Workers
# ---------------------------------------------------------------------------

@app.route("/api/workers")
def api_workers():
    """Return full status dictionaries for all workers."""
    return jsonify(lb.get_worker_status())


@app.route("/api/workers/queues")
def api_worker_queues():
    """Return queue snapshots for all workers."""
    return jsonify(lb.get_worker_queues())


@app.route("/api/workers/failed")
def api_workers_failed():
    """Return status dictionaries for workers currently in FAILED state."""
    failed = [w.get_status_dict() for w in lb.get_failed_workers()]
    return jsonify(failed)


@app.route("/api/workers/<worker_id>/fail", methods=["POST"])
def api_worker_fail(worker_id):
    """Simulate an unexpected failure of the specified worker."""
    try:
        worker = lb.simulate_worker_failure(worker_id)
        return jsonify({
            "message": "Worker failed successfully",
            "worker_id": worker.worker_id,
            "status": worker.status.value,
        })
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        return jsonify({"error": f"Unexpected error: {exc}"}), 500


@app.route("/api/workers/<worker_id>/recover", methods=["POST"])
def api_worker_recover(worker_id):
    """Recover a previously failed worker."""
    try:
        worker = lb.recover_worker(worker_id)
        return jsonify({
            "message": "Worker recovered successfully",
            "worker_id": worker.worker_id,
            "status": worker.status.value,
        })
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Unexpected error: {exc}"}), 500


# ---------------------------------------------------------------------------
# Routes: Tasks
# ---------------------------------------------------------------------------

@app.route("/api/tasks")
def api_tasks():
    """Return all submitted tasks, newest first."""
    tasks = lb.get_all_tasks()
    return jsonify([serialize_task(t) for t in reversed(tasks)])


@app.route("/api/tasks", methods=["POST"])
def api_submit_task():
    """
    Submit a single task.

    Request body (JSON):
        duration (float, required): Simulated processing time in seconds.
                                    Must be 0.05 <= duration <= 30.
        name (str, optional): Human-readable task name.
        task_type (str, optional): Task classification string.
        arrival_time (float, optional): Time when task becomes available (default: now).
    """
    data = request.get_json(silent=True) or {}

    # Validate duration
    raw_duration = data.get("duration")
    if raw_duration is None:
        return jsonify({"error": "Missing required field: duration"}), 400
    try:
        duration = float(raw_duration)
    except (TypeError, ValueError):
        return jsonify({"error": "duration must be a number"}), 400
    if duration <= 0:
        return jsonify({"error": "duration must be greater than 0"}), 400
    if duration > 30:
        return jsonify({"error": "duration must be <= 30 seconds"}), 400

    name = str(data.get("name", "Web Task"))
    task_type = str(data.get("task_type", "CPU_TASK"))
    arrival_time = float(data.get("arrival_time", time.time()))

    try:
        task = lb.create_and_submit_task(
            name=name,
            duration=duration,
            task_type=task_type,
            arrival_time=arrival_time
        )
        return jsonify({
            "message": "Task submitted successfully",
            "task_id": task.task_id,
            "worker": task.assigned_worker,
            "algorithm": task.scheduling_algorithm,
        })
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:
        return jsonify({"error": f"Unexpected error: {exc}"}), 500


@app.route("/api/tasks/batch", methods=["POST"])
def api_submit_batch():
    """
    Submit multiple tasks at once.

    Request body (JSON):
        count (int, optional): Number of tasks to submit (default 5, max 20).
        duration (float, optional): Duration for each task (default 1.0).
        name_prefix (str, optional): Prefix for task names (default 'Batch').
        arrival_interval (float, optional): Time interval between task arrivals (default 0).
    """
    data = request.get_json(silent=True) or {}

    try:
        count = int(data.get("count", 5))
        if count < 1 or count > 20:
            return jsonify({"error": "count must be between 1 and 20"}), 400
    except (TypeError, ValueError):
        return jsonify({"error": "count must be an integer"}), 400

    try:
        duration = float(data.get("duration", 1.0))
        if duration <= 0 or duration > 30:
            return jsonify({"error": "duration must be between 0 and 30"}), 400
    except (TypeError, ValueError):
        return jsonify({"error": "duration must be a number"}), 400

    try:
        arrival_interval = float(data.get("arrival_interval", 0))
        if arrival_interval < 0:
            return jsonify({"error": "arrival_interval must be >= 0"}), 400
    except (TypeError, ValueError):
        return jsonify({"error": "arrival_interval must be a number"}), 400

    name_prefix = str(data.get("name_prefix", "Batch"))
    submitted = []
    base_time = time.time()

    for i in range(1, count + 1):
        try:
            arrival_time = base_time + (i * arrival_interval)
            task = lb.create_and_submit_task(
                name=f"{name_prefix}-{i}",
                duration=duration,
                task_type="CPU_TASK",
                arrival_time=arrival_time,
            )
            submitted.append({"task_id": task.task_id, "worker": task.assigned_worker})
        except RuntimeError as exc:
            return jsonify({
                "error": str(exc),
                "submitted_so_far": submitted,
            }), 503

    return jsonify({
        "message": f"{count} tasks submitted",
        "tasks": submitted,
    })


# ---------------------------------------------------------------------------
# Routes: Metrics
# ---------------------------------------------------------------------------

@app.route("/api/metrics")
def api_metrics():
    """Full real-time metrics from the LoadBalancer."""
    return jsonify(lb.get_metrics())


# ---------------------------------------------------------------------------
# Routes: Algorithm
# ---------------------------------------------------------------------------

@app.route("/api/algorithm", methods=["POST"])
def api_set_algorithm():
    """
    Switch the scheduling algorithm.

    Request body (JSON):
        algorithm (str, required): 'round_robin', 'rr', '1',
                                   'least_connections', 'lc', '2'
    """
    data = request.get_json(silent=True) or {}
    algorithm = data.get("algorithm")
    if not algorithm:
        return jsonify({"error": "Missing required field: algorithm"}), 400

    try:
        new_sched = lb.set_algorithm(algorithm)
        return jsonify({
            "message": "Algorithm updated",
            "algorithm": new_sched.name,
        })
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Unexpected error: {exc}"}), 500


# ---------------------------------------------------------------------------
# Routes: Simulation (task preparation mode)
# ---------------------------------------------------------------------------


@app.route("/api/simulation/prepared", methods=["POST"])
def api_add_prepared_task():
    """
    Add a task to the prepared task list (does not execute yet).

    Request body (JSON):
        name (str, required): Task name.
        duration (float, required): Task duration in seconds.
        arrival_time (float, optional): Task arrival time offset in seconds (default: 0).
    """
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    duration = data.get("duration")
    arrival_offset = data.get("arrival_time", 0)

    if not name:
        return jsonify({"error": "Missing required field: name"}), 400
    if duration is None:
        return jsonify({"error": "Missing required field: duration"}), 400

    try:
        duration = float(duration)
        if duration <= 0 or duration > 30:
            return jsonify({"error": "duration must be between 0 and 30 seconds"}), 400
    except (TypeError, ValueError):
        return jsonify({"error": "duration must be a number"}), 400

    try:
        arrival_offset = float(arrival_offset)
        if arrival_offset < 0:
            return jsonify({"error": "arrival_time must be >= 0"}), 400
    except (TypeError, ValueError):
        return jsonify({"error": "arrival_time must be a number"}), 400

    _simulation_state["prepared_tasks"].append({
        "name": name,
        "duration": duration,
        "arrival_time": arrival_offset,
        "status": "READY",
    })

    return jsonify({
        "message": "Task added to prepared list",
        "prepared_count": len(_simulation_state["prepared_tasks"]),
    })


@app.route("/api/simulation/prepared", methods=["GET"])
def api_get_prepared_tasks():
    """Return the list of prepared tasks."""
    return jsonify({
        "tasks": _simulation_state["prepared_tasks"],
        "count": len(_simulation_state["prepared_tasks"]),
    })


@app.route("/api/simulation/prepared/<int:index>", methods=["DELETE"])
def api_remove_prepared_task(index):
    """Remove a prepared task by index."""
    if 0 <= index < len(_simulation_state["prepared_tasks"]):
        _simulation_state["prepared_tasks"].pop(index)
        return jsonify({
            "message": "Task removed",
            "prepared_count": len(_simulation_state["prepared_tasks"]),
        })
    return jsonify({"error": "Invalid index"}), 400


@app.route("/api/simulation/start", methods=["POST"])
def api_start_simulation():
    """
    Start the simulation by submitting all prepared tasks to the LoadBalancer.

    Requires at least one prepared task.
    """
    if _simulation_state["running"]:
        return jsonify({"error": "Simulation is already running"}), 400

    if not _simulation_state["prepared_tasks"]:
        return jsonify({"error": "No prepared tasks to submit"}), 400

    _simulation_state["running"] = True
    _simulation_state["simulation_start_time"] = time.time()

    # Submit all prepared tasks
    submitted = []
    base_time = time.time()
    for task_data in _simulation_state["prepared_tasks"]:
        try:
            arrival_time = base_time + task_data.get("arrival_time", 0)
            task = lb.create_and_submit_task(
                name=task_data["name"],
                duration=task_data["duration"],
                task_type="CPU_TASK",
                arrival_time=arrival_time,
            )
            submitted.append(task.task_id)
        except RuntimeError as exc:
            _simulation_state["running"] = False
            return jsonify({"error": str(exc)}), 503

    return jsonify({
        "message": f"Simulation started with {len(submitted)} tasks",
        "submitted_tasks": submitted,
    })


@app.route("/api/simulation/status", methods=["GET"])
def api_simulation_status():
    """Return the current simulation status."""
    return jsonify({
        "running": _simulation_state["running"],
        "prepared_count": len(_simulation_state["prepared_tasks"]),
        "elapsed_time": (
            time.time() - _simulation_state["simulation_start_time"]
            if _simulation_state["simulation_start_time"]
            else 0
        ),
    })


@app.route("/api/simulation/reset", methods=["POST"])
def api_reset_simulation():
    """
    Reset the simulation state.
    Clears prepared tasks and allows new simulation setup.
    """
    _simulation_state["running"] = False
    _simulation_state["prepared_tasks"] = []
    _simulation_state["simulation_start_time"] = None

    return jsonify({
        "message": "Simulation reset",
        "prepared_count": 0,
    })


# ---------------------------------------------------------------------------
# Application entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("  Distributed Load Balancer - Web Dashboard (Phase 4)")
    print("  Single-machine simulation | OS Mini-Project")
    print("=" * 60)
    print("  Dashboard: http://127.0.0.1:5000")
    print("  Press Ctrl+C to stop the server.")
    print("=" * 60)
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        threaded=True,
        use_reloader=False,
    )

