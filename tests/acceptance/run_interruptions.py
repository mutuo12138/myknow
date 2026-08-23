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
RUN_ROOT = ROOT / "interruption-runs" / RUN_ID
DATA_ROOT = RUN_ROOT / "data"
MARKERS = RUN_ROOT / "markers"
DATA_ROOT.mkdir(parents=True, exist_ok=True)
MARKERS.mkdir(parents=True, exist_ok=True)
os.environ["MUSE_VAULT_HOME"] = str(DATA_ROOT)
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

import main  # noqa: E402
import worker  # noqa: E402


def wait_for_marker(path: Path, process: subprocess.Popen, timeout: float = 15) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.is_file():
            return
        if process.poll() is not None:
            raise RuntimeError(f"child exited before marker: {process.returncode}")
        time.sleep(0.05)
    raise TimeoutError(f"marker timeout: {path}")


def drain_worker() -> None:
    idle = 0
    for _ in range(300):
        if worker.process_one():
            idle = 0
            continue
        idle += 1
        if idle >= 3:
            break
        time.sleep(0.02)


def main_run() -> None:
    main.init_db()
    child = ROOT / "interruption_capture_child.py"
    scenarios = ["before_write", "after_stage", "before_commit"]
    events = []
    for index in range(1, 11):
        scenario = scenarios[(index - 1) % len(scenarios)]
        marker = MARKERS / f"{index:02d}-{scenario}.marker"
        env = os.environ.copy()
        env.update({
            "MUSE_VAULT_HOME": str(DATA_ROOT),
            "MUSE_INTERRUPT_SCENARIO": scenario,
            "MUSE_INTERRUPT_MARKER": str(marker),
            "MUSE_INTERRUPT_INDEX": str(index),
        })
        process = subprocess.Popen(
            [sys.executable, str(child)], cwd=PROJECT_ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        wait_for_marker(marker, process)
        process.kill()
        stdout, stderr = process.communicate(timeout=10)
        recovery = main.scan_integrity(repair=True)
        drain_worker()
        events.append({
            "index": index,
            "scenario": scenario,
            "exit_code": process.returncode,
            "marker": marker.read_text(encoding="utf-8"),
            "recovery": recovery,
            "stdout": stdout[-1000:],
            "stderr": stderr[-2000:],
        })

    final_report = main.scan_integrity(repair=False)
    with main.db() as connection:
        materials = [dict(row) for row in connection.execute("SELECT id, status, status_reason, local_path FROM materials ORDER BY captured_at")]
        operations = [dict(row) for row in connection.execute("SELECT id, state, error FROM capture_operations ORDER BY created_at")]
        false_ready = connection.execute(
            """SELECT COUNT(*) FROM materials m WHERE m.status='ready' AND (
                 (m.local_path IS NOT NULL AND NOT EXISTS (SELECT 1 FROM capture_operations o WHERE o.material_id=m.id AND o.state='committed'))
                 OR EXISTS (SELECT 1 FROM jobs j WHERE j.material_id=m.id AND j.state='dead'))"""
        ).fetchone()[0]
    expected_failed = len([event for event in events if event["scenario"] == "before_write"])
    failed = len([item for item in materials if item["status"] == "failed"])
    ready = len([item for item in materials if item["status"] == "ready"])
    passed = (
        len(events) == 10 and len(materials) == 10 and failed == expected_failed
        and ready == 10 - expected_failed and false_ready == 0
        and not final_report["missing_files"] and not final_report["orphan_files"]
        and not final_report["orphan_staging"] and not final_report["dead_ready"]
        and all(item["state"] in {"committed", "failed"} for item in operations)
    )
    summary = {
        "run_id": RUN_ID,
        "data_root": str(DATA_ROOT),
        "kill_count": 10,
        "expected_failed": expected_failed,
        "failed": failed,
        "ready": ready,
        "false_ready": false_ready,
        "final_integrity": final_report,
        "events": events,
        "pass": passed,
    }
    (RUN_ROOT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_ROOT / "summary.md").write_text("# Muse Vault 进程中断验收\n\n" + json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"run_id": RUN_ID, "pass": passed, "kill_count": 10, "failed": failed, "ready": ready, "false_ready": false_ready}, ensure_ascii=False))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main_run()
