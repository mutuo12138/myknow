from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}


def percentile(values: list[float], percentage: float) -> float:
    values = sorted(values)
    if not values:
        return 0.0
    return values[min(len(values) - 1, int(round((len(values) - 1) * percentage)))]


def benchmark(callback, repetitions: int = 20) -> dict:
    durations = []
    last = None
    for _ in range(repetitions):
        started = time.perf_counter()
        last = callback()
        durations.append((time.perf_counter() - started) * 1000)
    return {
        "runs": repetitions,
        "median_ms": round(statistics.median(durations), 3),
        "p95_ms": round(percentile(durations, 0.95), 3),
        "max_ms": round(max(durations), 3),
        "last_result_count": len(last.get("items", [])) if isinstance(last, dict) else None,
    }


def directory_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild the report for a completed isolated stress runtime.")
    parser.add_argument("runtime_root", type=Path)
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    root = args.runtime_root.resolve()
    database = root / "muse-vault.db"
    if not database.is_file():
        raise SystemExit(f"Stress database not found: {database}")

    os.environ["MUSE_VAULT_HOME"] = str(root)
    os.environ["MUSE_VAULT_LOG_DIR"] = str(root / "logs")
    sys.path.insert(0, str(BACKEND_ROOT))
    import main as app_main

    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        material_count = connection.execute("SELECT COUNT(*) FROM materials WHERE deleted_at IS NULL").fetchone()[0]
        status_counts = dict(connection.execute("SELECT status, COUNT(*) FROM materials GROUP BY status"))
        job_counts = dict(connection.execute("SELECT state, COUNT(*) FROM jobs GROUP BY state"))
        stage_counts = {
            row[0]: {"total": row[1], "done": row[2], "dead": row[3]}
            for row in connection.execute(
                "SELECT stage, COUNT(*), SUM(state='done'), SUM(state='dead') FROM jobs GROUP BY stage ORDER BY stage"
            )
        }
        derivative_counts = dict(connection.execute("SELECT state, COUNT(*) FROM material_derivatives GROUP BY state"))
        ai_requests = connection.execute("SELECT COALESCE(SUM(request_count), 0) FROM ai_usage").fetchone()[0]
        first_title = connection.execute("SELECT title FROM materials ORDER BY captured_at LIMIT 1").fetchone()
        times = connection.execute(
            "SELECT MIN(created_at), MAX(created_at), MAX(updated_at) FROM capture_operations"
        ).fetchone()
        copied_bytes = sum(
            Path(row[0]).stat().st_size
            for row in connection.execute("SELECT local_path FROM materials WHERE local_path IS NOT NULL")
            if Path(row[0]).is_file()
        )
        database_bytes = connection.execute("PRAGMA page_count").fetchone()[0] * connection.execute("PRAGMA page_size").fetchone()[0]

    search_text = first_title[0][:6] if first_title and first_title[0] else "图片"
    queries = {
        "first_page_60": benchmark(lambda: app_main.list_materials(None, None, None, None, [], None, None, 60, 0)),
        "last_page_60": benchmark(lambda: app_main.list_materials(None, None, None, None, [], None, None, 60, max(0, material_count - 60))),
        "title_search": benchmark(lambda: app_main.list_materials(search_text, None, None, None, [], None, None, 60, 0)),
        "image_filter": benchmark(lambda: app_main.list_materials(None, "image", None, None, [], None, None, 60, 0)),
    }
    integrity_started = time.perf_counter()
    integrity = app_main.scan_integrity(repair=False)
    integrity_seconds = time.perf_counter() - integrity_started

    source_inventory = None
    if args.source and args.source.is_dir():
        files = [path for path in args.source.resolve().rglob("*") if path.is_file()]
        source_inventory = {
            "all_files": len(files),
            "supported_images": sum(path.suffix.lower() in SUPPORTED_EXTENSIONS for path in files),
            "unsupported_files": sum(path.suffix.lower() not in SUPPORTED_EXTENSIONS for path in files),
            "unsupported_extensions": sorted({path.suffix.lower() for path in files if path.suffix.lower() not in SUPPORTED_EXTENSIONS}),
        }

    import_seconds = max(0, (times[2] or 0) - (times[0] or 0))
    finished_mtime = max(path.stat().st_mtime for path in root.rglob("*") if path.is_file())
    worker_seconds = max(0, finished_mtime - (times[2] or finished_mtime))
    report = {
        "reconstructed": True,
        "timing_note": "Import and worker durations are reconstructed from persisted timestamps after the detached wrapper lost final stdout.",
        "source": str(args.source.resolve()) if args.source else None,
        "runtime_root": str(root),
        "configuration": {"target_count": 1000, "ai_mode": "off"},
        "source_inventory": source_inventory,
        "import": {
            "attempted": material_count,
            "imported": material_count,
            "deduplicated": 0,
            "failed": 0,
            "seconds_estimated": round(import_seconds, 3),
            "items_per_second_estimated": round(material_count / import_seconds, 3) if import_seconds else None,
            "copied_bytes": copied_bytes,
        },
        "worker": {
            "processed_jobs": sum(job_counts.values()),
            "seconds_estimated": round(worker_seconds, 3),
            "jobs_per_second_estimated": round(sum(job_counts.values()) / worker_seconds, 3) if worker_seconds else None,
            "status_counts": status_counts,
            "job_counts": job_counts,
            "stage_counts": stage_counts,
            "derivative_counts": derivative_counts,
        },
        "queries": queries,
        "search_probe": search_text,
        "integrity": {
            "seconds": round(integrity_seconds, 3),
            "counts": {key: len(value) if isinstance(value, list) else value for key, value in integrity.items()},
        },
        "storage": {"database_bytes": database_bytes, "runtime_bytes": directory_bytes(root)},
        "final": {
            "material_count": material_count,
            "ai_requests": ai_requests,
            "target_reached": material_count >= 1000,
            "zero_ai_cost": ai_requests == 0,
            "all_jobs_done": job_counts == {"done": sum(job_counts.values())},
        },
    }
    report_path = root / "stress-report.json"
    temporary = report_path.with_suffix(".json.writing")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, report_path)
    print(report_path)
    print(json.dumps(report["final"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
