from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parents[1]
RUN_ID = time.strftime("%Y%m%d-%H%M%S")
RUN_ROOT = ROOT / "concurrency-runs" / RUN_ID
DATA_ROOT = RUN_ROOT / "data"
STOP = RUN_ROOT / "stop.marker"
DATA_ROOT.mkdir(parents=True, exist_ok=True)
os.environ["MUSE_VAULT_HOME"] = str(DATA_ROOT)
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

import main  # noqa: E402
import worker  # noqa: E402


def drain_parent() -> None:
    idle = 0
    for _ in range(1000):
        if worker.process_one():
            idle = 0
            continue
        idle += 1
        if idle >= 5:
            return
        time.sleep(0.01)
    raise TimeoutError("parent worker drain exceeded limit")


def main_run() -> None:
    main.init_db()
    base_env = os.environ.copy()
    base_env["MUSE_VAULT_HOME"] = str(DATA_ROOT)
    base_env["MUSE_CONCURRENCY_STOP"] = str(STOP)
    worker_script = ROOT / "concurrency_worker_child.py"
    capture_script = ROOT / "concurrency_capture_child.py"
    workers = [subprocess.Popen(
        [sys.executable, str(worker_script)], cwd=PROJECT_ROOT, env=base_env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ) for _ in range(2)]
    producers = []
    for producer in range(6):
        env = base_env.copy()
        env["MUSE_CONCURRENCY_PRODUCER"] = str(producer)
        env["MUSE_CONCURRENCY_COUNT"] = "20"
        producers.append(subprocess.Popen(
            [sys.executable, str(capture_script)], cwd=PROJECT_ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        ))
    process_results = []
    for process in producers:
        stdout, stderr = process.communicate(timeout=60)
        process_results.append({"kind": "producer", "exit_code": process.returncode, "stdout": stdout[-1000:], "stderr": stderr[-3000:]})
    STOP.write_text("capture complete", encoding="utf-8")
    for process in workers:
        stdout, stderr = process.communicate(timeout=60)
        process_results.append({"kind": "worker", "exit_code": process.returncode, "stdout": stdout[-1000:], "stderr": stderr[-3000:]})
    drain_parent()
    integrity = main.scan_integrity(repair=False)
    with main.db() as connection:
        material_count = connection.execute("SELECT COUNT(*) FROM materials").fetchone()[0]
        ready_count = connection.execute("SELECT COUNT(*) FROM materials WHERE status='ready'").fetchone()[0]
        unfinished_jobs = connection.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running','dead')").fetchone()[0]
        fts_count = connection.execute("SELECT COUNT(*) FROM materials_fts").fetchone()[0]
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    lock_errors = [item for item in process_results if "database is locked" in item["stderr"].lower()]
    passed = (
        all(item["exit_code"] == 0 for item in process_results)
        and material_count == 120 and ready_count == 120 and unfinished_jobs == 0 and fts_count == 120
        and journal_mode == "wal" and not lock_errors
        and not integrity["missing_files"] and not integrity["orphan_files"] and not integrity["dead_ready"]
        and not integrity["duplicate_fts"] and not integrity["stale_fts"]
    )
    summary = {
        "run_id": RUN_ID,
        "data_root": str(DATA_ROOT),
        "producers": 6,
        "workers": 2,
        "material_count": material_count,
        "ready_count": ready_count,
        "unfinished_jobs": unfinished_jobs,
        "fts_count": fts_count,
        "journal_mode": journal_mode,
        "database_locked_errors": len(lock_errors),
        "integrity": integrity,
        "processes": process_results,
        "pass": passed,
    }
    (RUN_ROOT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_ROOT / "summary.md").write_text("# Muse Vault 并发写验收\n\n" + json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"run_id": RUN_ID, "pass": passed, "material_count": material_count, "ready_count": ready_count, "database_locked_errors": len(lock_errors)}, ensure_ascii=False))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main_run()
