"""
manual_e2e_verify.py - Programmatic execution of the Step 1-13 manual verification workflow.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as web_module

def run_workflow():
    client = web_module.app.test_client()

    print("=== STEP 1 & 2: Landing & Simulator ===")
    r_home = client.get("/")
    assert r_home.status_code == 200, f"Home failed {r_home.status_code}"
    r_sim = client.get("/simulator")
    assert r_sim.status_code == 200, f"Simulator failed {r_sim.status_code}"
    print("[OK] Landing and Simulator pages load successfully.")

    print("=== STEP 3: Select Round Robin ===")
    r_algo = client.post("/api/algorithm", json={"algorithm": "round_robin"})
    assert r_algo.status_code == 200
    assert web_module.lb.scheduler_name == "Round Robin"
    print("[OK] Algorithm set to Round Robin.")

    print("=== STEP 4: Add Tasks Individually ===")
    tasks_to_add = [
        ("Task A", 5.0),
        ("Task B", 3.0),
        ("Task C", 7.0),
        ("Task D", 4.0),
        ("Task E", 6.0),
        ("Task F", 2.0),
    ]
    for name, dur in tasks_to_add:
        r = client.post("/api/simulation/prepared", json={"name": name, "duration": dur})
        assert r.status_code == 200

    print("=== STEP 5: Verify 6 prepared tasks, NOT 12 ===")
    r_prep = client.get("/api/simulation/prepared")
    prep_data = r_prep.get_json()
    assert prep_data["count"] == 6, f"Expected 6 prepared tasks, got {prep_data['count']}"
    print(f"[OK] Exactly {prep_data['count']} prepared tasks present.")

    print("=== STEP 6 & 7: Run Simulation & Verify Real Task IDs ===")
    r_start = client.post("/api/simulation/start")
    assert r_start.status_code == 200
    start_data = r_start.get_json()
    submitted = start_data["submitted_tasks"]
    expected_ids = ["T001", "T002", "T003", "T004", "T005", "T006"]
    assert submitted == expected_ids, f"Expected {expected_ids}, got {submitted}"
    print(f"[OK] Backend assigned exact IDs: {submitted}")

    print("=== STEP 8: Verify Worker Queues, Threads, Workload ===")
    r_workers = client.get("/api/workers")
    workers = r_workers.get_json()
    for w in workers:
        assert w["thread_alive"] is True
        assert w["thread_state"] in ("RUNNING", "WAITING", "IDLE")
        print(f"  {w['worker_id']}: status={w['status']}, thread_state={w['thread_state']}, workload={w['workload']}")

    print("=== STEP 10: Fail Worker-2 ===")
    r_fail = client.post("/api/workers/Worker-2/fail")
    assert r_fail.status_code == 200
    w2_status = [w for w in client.get("/api/workers").get_json() if w["worker_id"] == "Worker-2"][0]
    assert w2_status["status"] == "FAILED"
    assert w2_status["available"] is False
    print(f"[OK] Worker-2 failed successfully: {w2_status['status']}, available={w2_status['available']}")

    print("=== STEP 11: Recover Worker-2 ===")
    r_rec = client.post("/api/workers/Worker-2/recover")
    assert r_rec.status_code == 200
    w2_rec = [w for w in client.get("/api/workers").get_json() if w["worker_id"] == "Worker-2"][0]
    assert w2_rec["status"] == "IDLE"
    assert w2_rec["available"] is True
    assert w2_rec["thread_alive"] is True
    print(f"[OK] Worker-2 recovered successfully: {w2_rec['status']}, thread_alive={w2_rec['thread_alive']}")

    print("=== STEP 12: Reset Simulator ===")
    r_reset = client.post("/api/simulation/reset")
    assert r_reset.status_code == 200
    m = client.get("/api/metrics").get_json()
    assert m["total_submitted"] == 0
    assert m["total_completed"] == 0
    prep_after = client.get("/api/simulation/prepared").get_json()
    assert prep_after["count"] == 0
    for w in client.get("/api/workers").get_json():
        assert w["status"] == "IDLE"
        assert w["workload"] == 0
        assert w["queue_size"] == 0
        assert w["available"] is True
        assert w["thread_alive"] is True
    print("[OK] Complete reset verified: 0 tasks, all workers IDLE, all queues empty.")

    print("\nALL WORKFLOW CHECKS PASSED PERFECTLY!")

if __name__ == "__main__":
    run_workflow()
