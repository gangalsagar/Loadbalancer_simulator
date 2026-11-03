# Python-based Functional Load Balancer

An Operating Systems (OS) mini-project implementing a real, concurrent, thread-based functional load balancer in Python.

---

## 1. Project Objective

The primary objective of this project is to model and implement the fundamental Operating Systems concepts of **concurrency, thread-safe queuing, process/thread scheduling, and resource distribution** through a real functional load balancer.

Unlike UI simulations or static mocks, this system actually spawns independent backend worker threads, ingests tasks through a centralized load balancer, schedules them across workers using scheduling policies, and executes workloads concurrently.

> **Scope Note:** This repository currently implements **ONLY PHASE 1 (Core Load Balancer)**.  
> Phases 2, 3, and 4 are strictly deferred to future milestones.

---

## 2. What the Load Balancer Does

1. **Ingests Tasks:** Accepts tasks submitted individually or in batches from clients/users.
2. **Assigns via Scheduling Algorithm:** Distributes tasks across backend workers using the **Round Robin** algorithm.
3. **Executes Concurrently:** Dispatches tasks to backend worker threads, each maintaining an isolated, thread-safe task queue (`queue.Queue`). Multiple workers execute their assigned tasks simultaneously in parallel threads.
4. **Tracks Lifecycle States:** Monitors each task through its full lifecycle: `PENDING` -> `QUEUED` -> `RUNNING` -> `COMPLETED` / `FAILED`.
5. **Provides Monitoring & Metrics:** Exposes worker status, current queue lengths, completed task counts, and turnaround/execution timing via a clean interactive CLI.
6. **Graceful Shutdown:** Implements clean thread termination without abruptly aborting execution.

---

## 3. Architecture

```text
CLIENT / TASK GENERATOR
        │
        ▼
+───────────────────────────+
│       LOAD BALANCER       │
│                           │
│   Round Robin Scheduler   │
+─────────────┬─────────────+
              │
    ┌─────────┼─────────┐
    │         │         │
    ▼         ▼         ▼
+─────────+ +─────────+ +─────────+
│Worker-1 │ │Worker-2 │ │Worker-3 │
│  Queue  │ │  Queue  │ │  Queue  │
+────┬────+ +────┬────+ +────┬────+
     │           │           │
     ▼           ▼           ▼
[Thread 1]  [Thread 2]  [Thread 3]
  Execute     Execute     Execute
  Tasks       Tasks       Tasks
(Concurrent Execution Across Workers)
```

### Producer-Consumer Flow
1. **Producer:** The client or task generator produces tasks and submits them to the `LoadBalancer`.
2. **Scheduler:** The `RoundRobinScheduler` atomically determines the target worker (`Worker-1 -> Worker-2 -> Worker-3 -> ...`).
3. **Queue:** The task is pushed to the target worker's FIFO queue (`queue.Queue`).
4. **Consumer:** Each `Worker` thread independently consumes tasks from its queue, marks the task `RUNNING`, executes the workload, and marks it `COMPLETED`.

---

## 4. Phase 1 Features

* **Task Model (`task.py`):**
  - Unique task identification (`T001`, `T002`, ...).
  - Explicit states: `PENDING`, `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`.
  - Timing metrics: creation time, start time, completion time, waiting time, execution time, and turnaround time.
* **Backend Workers (`server.py`):**
  - Independent `Worker` instances (3 workers by default).
  - Thread-safe FIFO task queues (`queue.Queue`).
  - Dedicated background thread per worker (`threading.Thread`).
  - Real worker states: `IDLE`, `BUSY`, `STOPPED`.
  - Task completion counters and current task tracking.
* **Round Robin Scheduler (`scheduler.py`):**
  - Circular round-robin scheduling algorithm.
  - Thread-safe index increment and wraparound.
  - Decoupled from CLI and load balancer logic for extensibility.
* **Load Balancer Coordinator (`load_balancer.py`):**
  - Central manager for workers and scheduler.
  - Thread-safe task repository and lookup.
  - Real-time metrics collection: submitted, running, queued, completed counts.
  - Graceful worker shutdown mechanism.
* **Interactive CLI (`main.py`):**
  - Option 1: Submit individual task.
  - Option 2: Submit batch tasks.
  - Option 3: View real-time worker status and queue sizes.
  - Option 4: Query specific task status and execution metrics.
  - Option 5: View all submitted tasks in a formatted table.
  - Option 6: Gracefully exit and terminate threads.
  - Automated demonstration flag: `--demo`.
* **Testing & Verification (`tests/`):**
  - 18 comprehensive unit and concurrency tests covering task models, workers, round-robin distribution, and concurrent execution speedup.

---

## 5. Technologies Used

* **Language:** Python 3.10+ (tested on Python 3.10.11)
* **Standard Library Primitives:**
  - `threading` (Worker threads, thread safety via `threading.Lock`, coordination via `threading.Event`)
  - `queue` (Thread-safe FIFO task queues)
  - `time` (Timestamping and simulated workload execution)
  - `dataclasses` (Task model)
  - `enum` (TaskStatus, WorkerStatus)
  - `typing` (Type annotations)
  - `argparse` (CLI argument parsing)
  - `logging` (Timestamped event logging)
  - `unittest` (Test suite)
* **External Dependencies:** **None** (Phase 1 intentionally uses 100% standard library).

---

## 6. Project Structure

```text
loadbalancer/
├── main.py                  # CLI entry point and interactive user interface
├── load_balancer.py         # Core LoadBalancer coordinator class
├── server.py                # Worker thread and server abstraction
├── scheduler.py             # Round Robin scheduling implementation
├── task.py                  # Task abstraction, lifecycle states, and ID generator
├── requirements.txt         # Dependency documentation (standard library only)
├── README.md                # Project documentation and guide
└── tests/
    ├── __init__.py          # Test package indicator
    ├── test_task.py         # Unit tests for task creation, state, and ID generation
    ├── test_server.py       # Unit tests for worker threads, queues, and execution
    ├── test_scheduler.py    # Unit tests verifying exact Round Robin rotation
    ├── test_load_balancer.py# Unit tests for submission, tracking, and metrics
    └── test_concurrency.py  # Concurrency benchmark and execution window overlap test
```

---

## 7. How to Install

Phase 1 requires Python 3.10 or higher. No external pip packages are required.

### 1. Clone or navigate to the directory:
```bash
cd loadbalancer
```

### 2. (Optional) Create and activate a virtual environment:
**Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**Linux / macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

---

## 8. How to Run

### Interactive CLI Mode
```bash
python main.py
```
*(Or `.\venv\Scripts\python.exe main.py` on Windows)*

You will be greeted with the interactive menu:
```text
========================================
PYTHON LOAD BALANCER
====================
Workers: 3
Algorithm: Round Robin

1. Submit Task
2. Submit Multiple Tasks
3. View Worker Status
4. View Task Status
5. View All Tasks
6. Exit
========================================
Choose option:
```

### Automated Demonstration Mode
To run an automated end-to-end demonstration showing batch task distribution, real-time concurrency, and clean shutdown:
```bash
python main.py --demo
```

To run with a custom number of workers (e.g., 5 workers):
```bash
python main.py --workers 5
```

---

## 9. How to Run Tests

Run the complete test suite using Python's built-in `unittest` runner:

```bash
python -m unittest discover -s tests -v
```
*(Or `.\venv\Scripts\python.exe -m unittest discover -s tests -v` on Windows)*

All 18 tests will execute and verify task lifecycle transitions, exact Round Robin order, worker threads, and concurrent execution speedup.

---

## 10. Example Output

### Submitting Batch Tasks (Option 2):
```text
Choose option: 2
Number of tasks: 6
Enter processing duration per task (seconds, default 2.0): 2.0

Submitting tasks...
T001 -> Worker-1
T002 -> Worker-2
T003 -> Worker-3
T004 -> Worker-1
T005 -> Worker-2
T006 -> Worker-3

[OK] Successfully submitted 6 tasks.
```

### Real-Time Logging Output:
```text
[14:28:16] Task T001 created
[14:28:16] Task T001 assigned to Worker-1
[14:28:16] Worker-1 started Task T001
[14:28:16] Task T002 created
[14:28:16] Task T002 assigned to Worker-2
[14:28:16] Worker-2 started Task T002
[14:28:16] Task T003 created
[14:28:16] Task T003 assigned to Worker-3
[14:28:16] Worker-3 started Task T003
[14:28:16] Task T004 created
[14:28:16] Task T004 assigned to Worker-1
[14:28:16] Task T005 created
[14:28:16] Task T005 assigned to Worker-2
[14:28:16] Task T006 created
[14:28:16] Task T006 assigned to Worker-3
[14:28:18] Worker-1 completed Task T001
[14:28:18] Worker-1 started Task T004
[14:28:18] Worker-2 completed Task T002
[14:28:18] Worker-2 started Task T005
[14:28:18] Worker-3 completed Task T003
[14:28:18] Worker-3 started Task T006
```

### Worker Status (Option 3):
```text
========================================
WORKER STATUS
========================================

Worker-1
Status: BUSY
Current Task: T001
Queue Size: 1
Completed: 0

Worker-2
Status: BUSY
Current Task: T002
Queue Size: 1
Completed: 0

Worker-3
Status: BUSY
Current Task: T003
Queue Size: 1
Completed: 0
========================================

System Summary: 6 Submitted | 3 Running | 3 Queued | 0 Completed
```

### All Tasks Table (Option 5):
```text
============================================================================
ID       NAME                 WORKER         STATUS         DURATION   EXEC TIME 
----------------------------------------------------------------------------
T001     Batch-Task-1         Worker-1       COMPLETED      2.0s       2.01s     
T002     Batch-Task-2         Worker-2       COMPLETED      2.0s       2.01s     
T003     Batch-Task-3         Worker-3       COMPLETED      2.0s       2.00s     
T004     Batch-Task-4         Worker-1       COMPLETED      2.0s       2.01s     
T005     Batch-Task-5         Worker-2       COMPLETED      2.0s       2.00s     
T006     Batch-Task-6         Worker-3       COMPLETED      2.0s       2.01s     
============================================================================
```

---

## 11. Operating Systems Concepts Demonstrated

1. **Multithreading & Concurrency:**
   - Multiple backend worker threads (`threading.Thread`) execute concurrently, utilizing OS thread scheduling to overlap task runtimes.
2. **Producer-Consumer Pattern:**
   - The load balancer acts as a producer, enqueueing tasks into thread-safe queues.
   - Worker threads act as consumers, dequeueing and processing tasks asynchronously.
3. **Thread-Safe Queuing:**
   - Employs Python's monitor-based `queue.Queue` with internal condition variables and mutual exclusion to eliminate race conditions during task handover.
4. **Task Scheduling (Round Robin):**
   - Implements a classic OS scheduling algorithm that distributes workloads evenly and cyclically without starvation.
5. **Thread Synchronization & Mutual Exclusion:**
   - Mutex locks (`threading.Lock`) safeguard shared data structures (task status updates, scheduler index increment, completion counters) preventing state corruption.
6. **Graceful Termination & Signaling:**
   - Uses `threading.Event` and sentinel tokens (`None`) to signal worker threads to cleanly finish active workloads and terminate safely.

---

## 12. Limitations of Phase 1

* **Static Round Robin Only:** Tasks are assigned in fixed cyclic order regardless of individual task execution times or current worker load.
* **No Dynamic Load Awareness:** Does not factor in worker queue lengths (Least Connections is not implemented yet).
* **No Worker Failure Handling:** Workers are assumed to remain healthy (worker crash detection and recovery are not implemented yet).
* **CLI-Only Interface:** Interaction is terminal-based; web monitoring and graphical visualization are not included.

---

## 13. Future Roadmap

* **Phase 2 — Intelligent Load Balancing:**
  - Least Connections scheduling algorithm.
  - Dynamic load tracking and queue-depth awareness.
  - Comparative performance evaluation between Round Robin and Least Connections.
* **Phase 3 — Fault Tolerance & Synchronization:**
  - Worker health checks and heartbeat mechanisms.
  - Worker crash simulation and automatic recovery.
  - Task reassignment upon worker failure.
  - Explicit race condition demonstrations and synchronization benchmarks.
* **Phase 4 — Monitoring & Web Dashboard:**
  - Flask web application backend.
  - Responsive web dashboard (HTML/CSS/JavaScript).
  - Real-time charts showing throughput, latency, and worker utilization.
  - Live side-by-side algorithm comparison.

