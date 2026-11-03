"""
Quick API smoke test — run while Flask server is live on port 5000.
"""
import json
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


errors = []

# ── 1. Status ──────────────────────────────────────────────────────────────────
print("=== 1. Status ===")
status = get("/api/status")
print("  ", status)
assert "total_workers" in status

# ── 2. Add prepared tasks ──────────────────────────────────────────────────────
print("\n=== 2. Add 3 prepared tasks ===")
for name, dur in [("Alpha", 2), ("Beta", 1), ("Gamma", 3)]:
    r = post("/api/simulation/prepared", {"name": name, "duration": dur})
    print("  Added:", r["task"]["label"], "->", r["task"]["name"], str(r["task"]["duration"]) + "s")

# ── 3. GET prepared tasks ──────────────────────────────────────────────────────
print("\n=== 3. GET prepared tasks ===")
r = get("/api/simulation/prepared")
print("  Count:", r["count"])
assert r["count"] == 3, "Expected 3 prepared tasks"
for t in r["tasks"]:
    print("  ", t["label"] + ":", t["name"])

# ── 4. Remove one task ────────────────────────────────────────────────────────
print("\n=== 4. Remove task 0 ===")
r = delete("/api/simulation/prepared/0")
print("  Remaining:", r["prepared_count"])
assert r["prepared_count"] == 2, "Expected 2 remaining"
r = get("/api/simulation/prepared")
for t in r["tasks"]:
    print("  ", t["label"] + ":", t["name"])

# ── 5. Run simulation ─────────────────────────────────────────────────────────
print("\n=== 5. Run simulation ===")
r = post("/api/simulation/start")
submitted = r.get("submitted_tasks", [])
print("  Submitted task IDs:", submitted)
assert len(submitted) == 2, "Expected exactly 2 submitted tasks"
assert all(tid.startswith("T") for tid in submitted), "Task IDs must be backend-generated (T###)"

# ── 6. Poll until done ────────────────────────────────────────────────────────
print("\n=== 6. Waiting for tasks to complete ===")
for _ in range(40):
    m = get("/api/metrics")
    total = m["total_submitted"]
    done = m["total_completed"] + m["total_interrupted"] + m["total_failed"]
    if total > 0 and done >= total:
        print("  DONE — elapsed:", round(m.get("elapsed_time", 0), 2), "s")
        print("  completed=%d failed=%d interrupted=%d" % (
            m["total_completed"], m["total_failed"], m["total_interrupted"]))
        break
    time.sleep(0.5)
else:
    errors.append("Tasks did not complete within 20s")
    print("  TIMEOUT!")

# ── 7. Task IDs ───────────────────────────────────────────────────────────────
print("\n=== 7. Task IDs ===")
tasks = get("/api/tasks")
for t in reversed(tasks):
    print("  %s  %s  status=%s  worker=%s" % (t["id"], t["name"], t["status"], t["worker"]))
assert len(tasks) == 2, "Expected 2 tasks in registry"

# ── 8. Workers ────────────────────────────────────────────────────────────────
print("\n=== 8. Workers ===")
workers = get("/api/workers")
for w in workers:
    print("  %s  status=%s  thread_alive=%s  queue_size=%s  queue=%s" % (
        w["worker_id"], w["status"], w["thread_alive"], w["queue_size"], w.get("queue", [])))

# ── 9. Reset ──────────────────────────────────────────────────────────────────
print("\n=== 9. Reset ===")
r = post("/api/simulation/reset")
print("  Response:", r)
m = get("/api/metrics")
assert m["total_submitted"] == 0, "Metrics should be 0 after reset"
assert m["total_completed"] == 0, "Metrics should be 0 after reset"
workers = get("/api/workers")
for w in workers:
    assert w["status"] == "IDLE", "Worker should be IDLE after reset: " + w["worker_id"]
    assert w["thread_alive"], "Worker thread should be alive after reset: " + w["worker_id"]
print("  All workers IDLE and threads alive — OK")

# ── 10. Run simulation a second time (no leftover state) ─────────────────────
print("\n=== 10. Run second simulation after reset ===")
post("/api/simulation/prepared", {"name": "SecondRun", "duration": 1})
r = post("/api/simulation/start")
submitted2 = r.get("submitted_tasks", [])
print("  Submitted:", submitted2)
assert submitted2[0] == "T001", "After reset, first task must be T001 again; got " + submitted2[0]
for _ in range(20):
    m = get("/api/metrics")
    if m["total_completed"] + m["total_interrupted"] + m["total_failed"] >= m["total_submitted"] > 0:
        print("  DONE")
        break
    time.sleep(0.5)

# ── Summary ───────────────────────────────────────────────────────────────────
print()
if errors:
    print("FAILED:", errors)
    sys.exit(1)
else:
    print("=== ALL SMOKE TESTS PASSED ===")

