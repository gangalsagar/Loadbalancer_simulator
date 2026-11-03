# Python-based Functional Load Balancer

An Operating Systems (OS) mini-project implementing a real, concurrent, thread-based functional load balancer in Python with dynamic scheduling, fault tolerance, and synchronization.

---

## 1. Project Objective

The primary objective of this project is to model and implement the fundamental Operating Systems concepts of **concurrency, thread-safe queuing, process/thread scheduling, workload tracking, mutual exclusion, race-condition prevention, fault tolerance, and failure recovery** through a real functional load balancer.

Unlike UI simulations or static mocks, this system actually spawns independent backend worker threads, ingests tasks through a centralized load balancer, schedules them across workers using scheduling policies, and executes workloads concurrently.

> **Scope Note:** This repository currently implements:
> - **PHASE 1 (Core Load Balancer)**
> - **PHASE 2 (Intelligent Load Balancing)**
> - **PHASE 3 (Fault Tolerance & Synchronization)**
>
> Phase 4 (Flask Web Dashboard, Charts) is **now complete** — see Section 15 below.
>
> **Logical/Virtual Worker Clarification:** The backend workers are logical/virtual workers implemented as Python threads (`threading.Thread`) running concurrently on a single physical machine. This simulates distributed server nodes within a shared-memory environment.

---

## 2. What the Load Balancer Does

1. **Ingests Tasks:** Accepts tasks submitted individually or in batches from clients/users.
2. **Selects Scheduling Algorithms:** Supports dynamic switching between **Round Robin** and **Least Connections (Least Workload)**.
3. **Tracks Real-Time Workloads:** Monitors each worker's active workload defined as:
   $$\text{Current Workload} = (\text{1 if currently executing a task else 0}) + \text{Queued Tasks}$$
4. **Executes Concurrently:** Dispatches tasks to backend worker threads, each maintaining an isolated, thread-safe task queue (`queue.Queue`). Multiple workers execute their assigned tasks simultaneously in parallel threads.
5. **Tracks Task Lifecycle States:** Monitors each task through its full lifecycle: `PENDING` -> `QUEUED` -> `RUNNING` -> `COMPLETED` / `FAILED` / `INTERRUPTED`.
6. **Simulates Worker Failure (Phase 3):** Simulates unexpected worker crashes. Actively executing tasks are cleanly caught and marked `INTERRUPTED`, and unexecuted queued tasks are atomically drained and re-routed to healthy workers.
7. **Recovers Failed Workers (Phase 3):** Restores failed workers to `IDLE` state, restarts clean worker threads without duplicate thread leaks, and re-enables them for scheduling.
8. **Fault-Tolerant Schedulers (Phase 3):** Both Round Robin and Least Connections strictly filter out failed workers, ensuring no tasks are assigned to unavailable nodes.
9. **Provides Monitoring & Metrics:** Exposes worker states, available/failed status, workloads, queue lengths, failure/recovery counts, execution time, waiting time, and throughput via a clean interactive CLI.
10. **Benchmarking & Comparison:** Runs controlled head-to-head performance benchmarks under identical workloads to compare Round Robin against Least Connections using measured empirical data.
11. **Graceful Shutdown:** Implements clean thread termination using sentinels and termination events without abruptly aborting execution.

---

## 3. Architecture

```text
CLIENT / TASK GENERATOR
        |
        v
+------------------------------------+
|           LOAD BALANCER            |
|                                    |
|   Active Scheduler Selection:      |
|   - Round Robin (Fault-Tolerant)   |
|   - Least Connections (Workload)   |
|                                    |
|   Fault Tolerance Coordinator:     |
|   - Worker Failure Simulation      |
|   - Task Interruption & Draining   |
|   - Re-routing Engine              |
|   - Worker Thread Recovery         |
+-----------------+------------------+
                  |
        +---------+---------+
        |         |         |
        v         v         v
    +---------+ +---------+ +---------+
    |Worker-1 | |Worker-2 | |Worker-3 |
    |  Queue  | |  Queue  | |  Queue  |
    +----+----+ +----+----+ +----+----+
         |           |           |
         v           v           v
    [Thread 1]  [Thread 2]  [Thread 3]
      Execute     Execute     Execute
      Tasks       Tasks       Tasks
    (Concurrent Execution Across Workers)
```

---

## 4. Phase 3: Fault Tolerance & Synchronization

### 1. Worker Failure Model
Workers distinguish strictly between four lifecycle states:
* `IDLE`: Worker is active, healthy, and waiting for tasks.
* `BUSY`: Worker is actively executing a task.
* `FAILED`: Worker unexpectedly became unavailable during operation. It cannot accept new tasks and is excluded by schedulers.
* `STOPPED`: Worker was intentionally terminated during application shutdown.

### 2. Failure Simulation
When a worker failure is triggered (`simulate_worker_failure(worker_id)` or CLI Option 8):
1. The worker's state transitions to `FAILED`.
2. A failure event (`_fail_event`) is set.
3. If a task was actively executing:
   - The worker thread waiting on `_fail_event.wait(timeout=task.duration)` is immediately interrupted.
   - The executing task is marked `INTERRUPTED` with an interruption timestamp and failure reason.
   - The task is **never** silently marked as completed.
4. The worker thread terminates cleanly.

### 3. Handling Queued Tasks (Re-routing)
When a worker fails while tasks are waiting in its queue:
1. `worker.drain_queued_tasks()` atomically removes all unexecuted tasks from the queue under a reentrant lock (`threading.RLock`).
2. The `LoadBalancer` re-routes each recovered task through the active scheduler to healthy available workers.
3. The task's `was_re_routed` flag is set to `True`, `retry_count` is incremented, and its `original_worker` is recorded.
4. **No recoverable tasks are silently lost or duplicated.**

### 4. Scheduler Fault Tolerance
Both schedulers strictly filter candidate workers using `worker.is_available`:
* **Round Robin:** Automatically skips failed workers:
  If `Worker-2` is `FAILED`, scheduling cycles strictly across healthy workers:
  $$\text{Worker-1} \rightarrow \text{Worker-3} \rightarrow \text{Worker-1} \rightarrow \text{Worker-3}$$
* **Least Connections:** Evaluates workload only among healthy, running workers.
* **All-Workers-Failed Handling:** If all workers are failed, schedulers raise a `RuntimeError`, and the LoadBalancer holds tasks in a safe `PENDING` backlog rather than silently dropping them.

### 5. Worker Recovery
When a failed worker is restored (`recover_worker(worker_id)` or CLI Option 9):
1. Validates that the worker is currently `FAILED`.
2. Verifies that the previous thread has fully terminated (`_thread.join(timeout=3.0)`) to prevent duplicate thread leaks.
3. Clears internal failure events (`_fail_event.clear()`) and increments `recovery_count`.
4. Spawns a fresh worker thread and transitions state to `IDLE`.
5. Dispatches any backlogged tasks that were waiting for an available worker.
6. The worker is immediately available for new task assignments.

---

## 5. Synchronization & Race-Condition Prevention

This project demonstrates rigorous OS synchronization:

| Shared State | Synchronization Mechanism | Race Condition Prevented |
| :--- | :--- | :--- |
| Worker State & Workload | `threading.RLock` | Prevents reads of inconsistent workload during state transitions. |
| Task Queues | `queue.Queue` (Monitors) | Eliminates race conditions during concurrent enqueue/dequeue. |
| Worker Execution / Interruption | `threading.Event` (`_fail_event`) | Allows immediate thread interruption without dangerous thread kills. |
| Task Recovery / Draining | Atomic drain under `_lock` | Prevents tasks from being drained or re-routed twice. |
| Thread Re-creation | `_thread.join()` before new spawn | Prevents multiple concurrent threads operating on one Worker object. |
| Simultaneous Submit & Fail | Retry loop in `submit_task` | Catches workers failing in the split-second between selection and enqueue. |

> **Critical Locking Rule:** Mutex locks are held only for momentary memory updates. Workload execution (`time.sleep` / event wait) is performed **outside** locks, completely eliminating lock contention and priority inversion.

---

## 6. Task State Machine

```text
               [Submit]
                  |
                  v
              (PENDING)
                  |
            [Queue Task]
                  |
                  v
              (QUEUED) <------------------+
                  |                       |
            [Worker Starts]               | [Drained & Re-routed]
                  |                       |
                  v                       |
              (RUNNING)                   |
             /    |    \                  |
    [Success]/    |     \[Worker Crash]   |
           v      |      v                |
(COMPLETED)       |   (INTERRUPTED)       |
                  |                       |
            [Exception]                   |
                  |                       |
                  v                       |
               (FAILED)                   |
                                          |
      [Worker Fails While Task in Queue]--+
```

---

## 7. Scheduling Algorithms

### 1. Round Robin
* Cycles sequentially through available workers:
  $$\text{Worker-1} \rightarrow \text{Worker-2} \rightarrow \text{Worker-3} \rightarrow \text{Worker-1} \dots$$
* Simple, predictable, $O(1)$ selection overhead.
* Oblivious to worker queue depths.

### 2. Least Connections / Least Workload
* Evaluates active workload across healthy workers:
  $$\text{Current Workload} = (\text{1 if executing else 0}) + \text{Queued Tasks}$$
* Routes tasks to the worker with the lowest workload.
* Deterministic tie-breaking: selects the first worker in sequence when workloads are equal.
* Prevents head-of-line blocking under non-uniform task durations.

---

## 8. Technologies Used

* **Language:** Python 3.10+ (tested on Python 3.10.11)
* **Standard Library Primitives:**
  - `threading` (`threading.Thread`, `threading.RLock`, `threading.Event`)
  - `queue` (`queue.Queue`)
  - `time` (Timestamping, timing metrics, and simulated execution)
  - `dataclasses` (Task model)
  - `enum` (TaskStatus, WorkerStatus)
  - `typing` (Type hints across all modules)
  - `argparse` (CLI parsing)
  - `logging` (Timestamped event logs)
  - `unittest` (Automated test suite)
* **External Dependencies:** `flask>=2.3.0` (Phase 4 only). All Phase 1–3 logic uses only the Python standard library.

---

## 9. Project Structure

```text
loadbalancer/
├── app.py                   # Phase 4: Flask API + dashboard entry point
├── main.py                  # CLI entry point, interactive menu (1-11), and demo runners
├── load_balancer.py         # Core LoadBalancer coordinator, failure simulation, and metrics
├── server.py                # Worker thread, failure handling, queue draining, and recovery
├── scheduler.py             # Fault-tolerant Round Robin, Least Connections, and factory
├── comparison.py            # Controlled head-to-head algorithm comparison benchmark
├── task.py                  # Task model, lifecycle states (INTERRUPTED), and ID generator
├── requirements.txt         # Dependency documentation (flask for Phase 4)
├── README.md                # Project documentation and Operating Systems guide
├── templates/
│   └── index.html           # Phase 4: Single-page monitoring dashboard
├── static/
│   ├── style.css            # Phase 4: Dark monitoring theme (pure CSS)
│   └── app.js               # Phase 4: Vanilla JS polling, charts, user actions
└── tests/
    ├── __init__.py          # Test package indicator
    ├── test_task.py         # Unit tests for task creation, state, and ID generation
    ├── test_server.py       # Unit tests for worker threads, workload calculation, and execution
    ├── test_scheduler.py    # Unit tests for Round Robin and Least Connections selection
    ├── test_load_balancer.py# Unit tests for submission, dynamic switching, and metrics
    ├── test_concurrency.py  # Concurrency benchmark and execution window overlap test
    ├── test_comparison.py   # Unit tests for comparison benchmark runner and formatter
    ├── test_fault_tolerance.py # Unit, integration, concurrency, and stress tests for Phase 3
    └── test_web.py          # Phase 4: 28 Flask test-client API tests
```

---

## 10. How to Install & Run

### 1. Clone or navigate to the directory:
```bash
cd loadbalancer
```

### 2. (Optional) Virtual Environment:
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 3. Run the Interactive CLI:
```bash
python main.py
```
*(Or `.\venv\Scripts\python.exe main.py` on Windows)*

Interactive menu:
```text
========================================
PYTHON LOAD BALANCER
====================
Workers: 3
Current Scheduling Algorithm: ROUND ROBIN
Healthy Workers: 3/3

1. Submit Task
2. Submit Multiple Tasks
3. View Worker Status
4. View Task Status
5. View All Tasks
6. Change Scheduling Algorithm
7. View Metrics & Compare Algorithms
8. Simulate Worker Failure
9. Recover Worker
10. View Failed Workers
11. Exit
========================================
Choose option:
```

### 4. Run Automated Demonstrations:
* **Phase 3 Fault Tolerance Demo:**
  ```bash
  python main.py --demo-failure
  ```
* **Algorithm Comparison Benchmark:**
  ```bash
  python main.py --compare
  ```
* **Phase 2 Concurrency Demo:**
  ```bash
  python main.py --demo
  ```

---

## 11. How to Run Tests

Run the complete test suite using Python's built-in `unittest` runner:

```bash
python -m unittest discover -s tests -v
```
*(Or `.\venv\Scripts\python.exe -m unittest discover -s tests -v` on Windows)*

**All 75 tests pass cleanly** (47 Phase 1–3 + 28 Phase 4 web tests):
* Task lifecycle, unique sequential IDs, state transitions.
* Worker execution, workload calculation, and graceful stop.
* Round Robin and Least Connections fault-tolerant selection.
* Worker failure simulation and active task interruption.
* Queued task draining and automatic re-routing.
* Worker thread recovery without thread leaks.
* Concurrency race-condition prevention under simultaneous submission and failure.
* Full 30-task stress test verifying zero lost recoverable tasks and zero duplicate completions.

---

## 12. Operating Systems Concepts Demonstrated

1. **Thread Lifecycle Management:**
   - Explicit lifecycle states (`STARTED` -> `RUNNING` -> `FAILED` -> `RECOVERED` -> `RUNNING` -> `STOPPED`).
   - Clean thread recreation without orphaned threads.
2. **Mutual Exclusion & Critical Sections:**
   - Synchronizes shared memory (`Worker._lock`, `LoadBalancer._lock`) using reentrant locks (`threading.RLock`).
3. **Condition Synchronization & Signaling:**
   - Uses `threading.Event` to interrupt thread sleep immediately upon failure without using unsafe OS signals.
4. **Producer-Consumer Architecture:**
   - Load balancer enqueues tasks; worker threads consume and process tasks asynchronously via thread-safe monitors (`queue.Queue`).
5. **Static vs. Dynamic CPU/Task Scheduling:**
   - Static cyclic allocation (Round Robin) vs. dynamic state-dependent allocation (Least Connections).
6. **Fault Tolerance & Graceful Recovery:**
   - Backpressure handling, failover, queue draining, task re-routing, and node recovery.
7. **Empirical Benchmarking & Performance Metrics:**
   - Direct measurement of throughput, latency, waiting time, and turnaround time.

---

## 13. Limitations of Phase 3

* **Single-Machine Simulation:** Logical workers run as Python threads on one host machine rather than physical distributed servers over a network.
* **Simulated Execution Duration:** Workloads use simulated execution duration (`time.sleep` / event wait) rather than external CPU-bound C libraries.
* **CLI-Only Interface:** Interaction is terminal-based; web monitoring and charts are strictly deferred to Phase 4.

* **External Dependencies:** `flask>=2.3.0` (Phase 4 only). All Phase 1-3 logic is 100% Python standard library.

---

## 15. Phase 4: Web Dashboard &amp; Real-Time Monitoring

Phase 4 adds a browser-based monitoring and control dashboard **on top of** the existing functional backend. The Flask layer is a thin HTTP adapter only — all load balancing logic remains in the original Python modules.

### Stack

| Layer | Technology |
|---|---|
| Backend API | Python + Flask |
| Frontend | HTML + CSS + Vanilla JavaScript |
| Charts | Chart.js 4.x (via CDN — no npm) |
| Transport | REST over HTTP / JSON |

### Install Flask

```powershell
.\venv\Scripts\pip.exe install flask
```

### Start the Dashboard

```powershell
.\venv\Scripts\python.exe app.py
```

Then open **http://127.0.0.1:5000** in your browser.

### Project Structure (Phase 4 additions)

```text
loadbalancer/
├── app.py               # Flask application — REST API + HTML page serve
├── templates/
│   └── index.html       # Single-page dashboard (HTML)
├── static/
│   ├── style.css        # Dark monitoring theme (pure CSS)
│   └── app.js           # Vanilla JS: polling, charts, user actions
└── tests/
    └── test_web.py      # 28 Flask test-client tests
```

### REST API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/` | Serve the dashboard HTML |
| GET | `/api/status` | System overview (stat cards) |
| GET | `/api/workers` | All worker status dicts |
| GET | `/api/workers/failed` | Workers in FAILED state |
| POST | `/api/workers/<id>/fail` | Simulate worker failure |
| POST | `/api/workers/<id>/recover` | Recover a failed worker |
| GET | `/api/tasks` | All submitted tasks (newest first) |
| POST | `/api/tasks` | Submit a single task |
| POST | `/api/tasks/batch` | Submit N tasks at once |
| GET | `/api/metrics` | Full real-time metrics |
| POST | `/api/algorithm` | Switch scheduling algorithm |

### Dashboard Features

1. **Header stat cards** — Total/Active/Failed workers, Running tasks, Completed tasks, Throughput
2. **Algorithm selector** — Switch between Round Robin and Least Connections live
3. **Task submit form** — Single task with custom duration and name
4. **Batch submit form** — Submit 1–20 tasks at once
5. **Worker monitor** — Per-worker cards showing status badge, workload, queue size, current task, failure/recovery counts, and Fail/Recover action buttons
6. **Performance metrics panel** — Avg exec time, avg wait time, total exec time, re-routed count, failure/recovery counts
7. **Task Status Distribution** — Live-updating doughnut chart
8. **Worker Workload** — Live bar chart coloured by worker state
9. **Throughput History** — Line chart showing last 30 readings
10. **Task Monitor table** — Scrollable table of all tasks with status pills and re-routed tag

### Demonstration Workflow

1. Open http://127.0.0.1:5000
2. Observe 3 workers showing IDLE status
3. Submit a single task (duration = 2 s) — watch it appear in the task table as RUNNING then COMPLETED
4. Submit a batch of 6 tasks — observe Round Robin distribution (2 tasks per worker)
5. Switch algorithm to **Least Connections** — submit another batch and observe workload-aware distribution
6. Click **Fail** on Worker-2 while tasks are running — observe Worker-2 turns FAILED, queued tasks re-route to Workers 1 and 3
7. Click **Recover** on Worker-2 — it returns to IDLE and accepts new tasks again
8. Observe the Throughput History chart accumulate data over time
9. Check the Task Status Distribution doughnut updates as tasks complete

### Limitations (Phase 4)

* **Single-machine simulation:** Workers are Python threads, not real remote servers.
* **No persistence:** All state is in-memory; restarting the server resets all tasks and metrics.
* **No authentication:** Dashboard is intended for local/development use only (bound to 127.0.0.1).
* **No WebSockets:** Dashboard uses HTTP polling (1.5 s interval) rather than push notifications.

---

## 14. Future Roadmap

* **Phase 4 — Monitoring & Web Dashboard:**
  - Flask web application backend.
  - Responsive web dashboard (HTML/CSS/JavaScript).
  - Real-time performance charts showing throughput, latency, and worker utilization.
  - Interactive web UI controls for failure injection and recovery.
