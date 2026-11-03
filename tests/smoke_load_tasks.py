"""
Smoke test: verify the bulk-load-tasks flow works correctly via the backend API.
Simulates what the JS loadBulkTasks() does: POSTs N tasks with random durations
in range [minDur, maxDur], then starts the simulation.
"""
import json
import math
import random
import time
import sys
import urllib.request

BASE = "http://127.0.0.1:5000"


def get(path):
    r = urllib.request.urlopen(BASE + path)
    return json.loads(r.read())


def post(path, data=None):
    body = json.dumps(data or {}).encode()
    req = urllib.request.Request(
        BASE + path,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    r = urllib.request.urlopen(req)
    return json.loads(r.read())


def delete(path):
    req = urllib.request.Request(BASE + path, method="DELETE")
    r = urllib.request.urlopen(req)
    return json.loads(r.read())


print("=== Resetting server to clean state ===")
post("/api/simulation/reset")
m = get("/api/metrics")
assert m["total_submitted"] == 0, "Server should be clean after reset"
print("  Clean. Task counter starts at T001 again.")

# ── Bulk-add 10 tasks ─────────────────────────────────────────────────────────
COUNT = 10
MIN_DUR = 10
MAX_DUR = 20
PREFIX = "Task"

print("\n=== Bulk-adding %d tasks (durations %d–%d s) ===" % (COUNT, MIN_DUR, MAX_DUR))
added_tasks = []
for i in range(1, COUNT + 1):
    dur = round(MIN_DUR + random.random() * (MAX_DUR - MIN_DUR), 1)
    name = "%s %d" % (PREFIX, i)
    r = post("/api/simulation/prepared", {"name": name, "duration": dur})
    entry = r["task"]
    added_tasks.append(entry)
    print("  %s | %s | %ss" % (entry["label"], entry["name"], entry["duration"]))

assert len(added_tasks) == COUNT, "Expected %d prepared tasks" % COUNT

r = get("/api/simulation/prepared")
assert r["count"] == COUNT, "Backend count mismatch"

# Verify durations are in range
for t in r["tasks"]:
    d = t["duration"]
    assert MIN_DUR <= d <= MAX_DUR, "Duration %s out of range [%s, %s]" % (d, MIN_DUR, MAX_DUR)

print("\n  All durations verified in range [%d, %d] s" % (MIN_DUR, MAX_DUR))

# ── Start simulation (backend assigns T001 … T010) ────────────────────────────
print("\n=== Starting simulation ===")
r = post("/api/simulation/start")
submitted = r.get("submitted_tasks", [])
print("  Submitted IDs:", submitted)
assert len(submitted) == COUNT, "Expected %d submitted tasks, got %d" % (COUNT, len(submitted))
assert submitted[0] == "T001", "First ID must be T001, got " + submitted[0]
assert submitted[-1] == "T%03d" % COUNT, "Last ID must be T%03d" % COUNT

print("\n=== Tasks are running — NOT waiting for completion (10–20 s each) ===")
print("  Workers:")
workers = get("/api/workers")
for w in workers:
    print("  %s  status=%s  queue=%d  thread_alive=%s" % (
        w["worker_id"], w["status"], w["queue_size"], w["thread_alive"]))

m = get("/api/metrics")
print("\n  Metrics snapshot:")
print("  submitted=%d  running=%d  queued=%d  completed=%d" % (
    m["total_submitted"], m["total_running"], m["total_queued"], m["total_completed"]))
assert m["total_submitted"] == COUNT

print("\n=== ALL LOAD-TASKS SMOKE TESTS PASSED ===")
print("  (Simulation is still running — visit http://127.0.0.1:5000/simulator)")

