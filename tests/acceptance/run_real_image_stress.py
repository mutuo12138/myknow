from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import sqlite3
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

from fastapi import UploadFile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an isolated, zero-AI real-image stress test.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--runtime-root", type=Path)
    return parser.parse_args()


def percentile(values: list[float], percentage: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentage))))
    return ordered[index]


def benchmark(callback, repetitions: int = 20) -> dict:
    durations: list[float] = []
    last_value = None
    for _ in range(repetitions):
        started = time.perf_counter()
        last_value = callback()
        durations.append((time.perf_counter() - started) * 1000)
    return {
        "runs": repetitions,
        "median_ms": round(statistics.median(durations), 3),
        "p95_ms": round(percentile(durations, 0.95), 3),
        "max_ms": round(max(durations), 3),
        "last_result_count": len(last_value.get("items", [])) if isinstance(last_value, dict) else None,
    }


def directory_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def safe_print(value: str) -> None:
    try:
        print(value, flush=True)
    except BrokenPipeError:
        # A detached command wrapper must not terminate the actual stress run.
        sys.stdout = open(os.devnull, "w", encoding="utf-8")


def write_checkpoint(runtime_root: Path, payload: dict) -> None:
    path = runtime_root / "stress-checkpoint.json"
    temporary = path.with_suffix(".json.writing")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


async def import_batch(main, source_root: Path, paths: list[Path]) -> dict:
    uploads: list[UploadFile] = []
    relative_paths: list[str] = []
    try:
        for path in paths:
            uploads.append(UploadFile(file=path.open("rb"), filename=path.name))
            relative_paths.append(path.relative_to(source_root).as_posix())
        return await main.import_local_images(files=uploads, folder_id="inbox", relative_paths=relative_paths)
    finally:
        for upload in uploads:
            if not upload.file.closed:
                await upload.close()


def main() -> int:
    args = parse_args()
    source = args.source.resolve()
    if not source.is_dir():
        raise SystemExit(f"Source directory does not exist: {source}")
    target_count = max(1, min(args.count, 10_000))
    batch_size = max(1, min(args.batch_size, 50))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    runtime_root = (args.runtime_root or PROJECT_ROOT / "tests" / "runtime-data" / f"real-image-stress-{stamp}").resolve()
    if runtime_root.exists():
        raise SystemExit(f"Runtime root already exists: {runtime_root}")
    runtime_root.mkdir(parents=True)

    os.environ["MUSE_VAULT_HOME"] = str(runtime_root)
    os.environ["MUSE_VAULT_LOG_DIR"] = str(runtime_root / "logs")
    sys.path.insert(0, str(BACKEND_ROOT))
    import main as app_main
    import worker

    app_main.init_db()
    with app_main.db() as connection:
        settings = dict(app_main.DEFAULT_PROCESSING_SETTINGS)
        settings["ai_mode"] = "off"
        app_main.set_processing_settings(connection, settings)

    all_files = [path for path in source.rglob("*") if path.is_file()]
    supported = [path for path in all_files if path.suffix.lower() in SUPPORTED_EXTENSIONS]
    unsupported = [path for path in all_files if path.suffix.lower() not in SUPPORTED_EXTENSIONS]
    # Hashing relative path names gives a deterministic distribution across folders and formats
    # without reading source bytes before the actual import benchmark begins.
    candidates = sorted(
        supported,
        key=lambda path: hashlib.sha1(path.relative_to(source).as_posix().encode("utf-8")).hexdigest(),
    )

    import_started = time.perf_counter()
    imported = deduplicated = skipped = failed = attempted = imported_bytes = 0
    failure_samples: list[dict] = []
    cursor = 0
    batch_number = 0
    while imported < target_count and cursor < len(candidates):
        remaining = target_count - imported
        batch = candidates[cursor:cursor + min(batch_size, remaining)]
        cursor += len(batch)
        if not batch:
            break
        batch_number += 1
        result = asyncio.run(import_batch(app_main, source, batch))
        attempted += len(batch)
        imported += result["imported"]
        deduplicated += result["deduplicated"]
        skipped += result["skipped"]
        failed += result["failed"]
        imported_bytes += sum(item.get("size", 0) for item in result["items"])
        failure_samples.extend(result["failed_items"][: max(0, 20 - len(failure_samples))])
        safe_print(
            f"IMPORT batch={batch_number} attempted={attempted} imported={imported}/{target_count} "
            f"duplicates={deduplicated} failed={failed}"
        )
    import_seconds = time.perf_counter() - import_started
    write_checkpoint(runtime_root, {
        "phase": "import_complete", "source": str(source), "target_count": target_count,
        "attempted": attempted, "imported": imported, "deduplicated": deduplicated,
        "skipped": skipped, "failed": failed, "import_seconds": round(import_seconds, 3),
        "imported_bytes": imported_bytes,
    })

    worker_started = time.perf_counter()
    processed_jobs = 0
    forced_retry_rounds = 0
    maximum_jobs = max(100, imported * 10)
    while processed_jobs < maximum_jobs:
        if worker.process_one():
            processed_jobs += 1
            if processed_jobs % 250 == 0:
                safe_print(f"WORKER processed={processed_jobs}")
            continue
        with app_main.db() as connection:
            delayed = connection.execute("SELECT COUNT(*) FROM jobs WHERE state='queued'").fetchone()[0]
            if delayed:
                connection.execute("UPDATE jobs SET next_run_at=? WHERE state='queued'", (app_main.now(),))
                forced_retry_rounds += 1
                continue
        break
    worker_seconds = time.perf_counter() - worker_started
    write_checkpoint(runtime_root, {
        "phase": "worker_complete", "source": str(source), "target_count": target_count,
        "attempted": attempted, "imported": imported, "deduplicated": deduplicated,
        "skipped": skipped, "failed": failed, "import_seconds": round(import_seconds, 3),
        "imported_bytes": imported_bytes, "processed_jobs": processed_jobs,
        "worker_seconds": round(worker_seconds, 3), "forced_retry_rounds": forced_retry_rounds,
    })

    with app_main.db() as connection:
        material_count = connection.execute("SELECT COUNT(*) FROM materials WHERE deleted_at IS NULL").fetchone()[0]
        status_counts = {row[0]: row[1] for row in connection.execute("SELECT status, COUNT(*) FROM materials GROUP BY status")}
        job_counts = {row[0]: row[1] for row in connection.execute("SELECT state, COUNT(*) FROM jobs GROUP BY state")}
        stage_counts = {
            row[0]: {"total": row[1], "done": row[2], "dead": row[3]}
            for row in connection.execute(
                """SELECT stage, COUNT(*), SUM(state='done'), SUM(state='dead')
                   FROM jobs GROUP BY stage ORDER BY stage"""
            )
        }
        derivative_counts = {row[0]: row[1] for row in connection.execute("SELECT state, COUNT(*) FROM material_derivatives GROUP BY state")}
        ai_requests = connection.execute("SELECT COALESCE(SUM(request_count), 0) FROM ai_usage").fetchone()[0]
        first_title = connection.execute("SELECT title FROM materials ORDER BY captured_at LIMIT 1").fetchone()
        db_page_count = connection.execute("PRAGMA page_count").fetchone()[0]
        db_page_size = connection.execute("PRAGMA page_size").fetchone()[0]
    search_text = (first_title[0][:6] if first_title and first_title[0] else "图片")

    queries = {
        "first_page_60": benchmark(lambda: app_main.list_materials(None, None, None, None, [], None, None, 60, 0)),
        "last_page_60": benchmark(lambda: app_main.list_materials(None, None, None, None, [], None, None, 60, max(0, material_count - 60))),
        "title_search": benchmark(lambda: app_main.list_materials(search_text, None, None, None, [], None, None, 60, 0)),
        "image_filter": benchmark(lambda: app_main.list_materials(None, "image", None, None, [], None, None, 60, 0)),
    }
    integrity_started = time.perf_counter()
    integrity = app_main.scan_integrity(repair=False)
    integrity_seconds = time.perf_counter() - integrity_started
    integrity_counts = {
        key: len(value) if isinstance(value, list) else value
        for key, value in integrity.items()
    }

    report = {
        "started_at": stamp,
        "source": str(source),
        "runtime_root": str(runtime_root),
        "system": {"platform": platform.platform(), "python": platform.python_version()},
        "configuration": {"target_count": target_count, "batch_size": batch_size, "ai_mode": "off"},
        "source_inventory": {
            "all_files": len(all_files),
            "supported_images": len(supported),
            "unsupported_files": len(unsupported),
            "unsupported_extensions": sorted({path.suffix.lower() for path in unsupported}),
        },
        "import": {
            "attempted": attempted,
            "imported": imported,
            "deduplicated": deduplicated,
            "skipped": skipped,
            "failed": failed,
            "seconds": round(import_seconds, 3),
            "items_per_second": round(imported / import_seconds, 3) if import_seconds else None,
            "copied_bytes": imported_bytes,
            "failure_samples": failure_samples,
        },
        "worker": {
            "processed_jobs": processed_jobs,
            "seconds": round(worker_seconds, 3),
            "jobs_per_second": round(processed_jobs / worker_seconds, 3) if worker_seconds else None,
            "forced_retry_rounds": forced_retry_rounds,
            "status_counts": status_counts,
            "job_counts": job_counts,
            "stage_counts": stage_counts,
            "derivative_counts": derivative_counts,
        },
        "queries": queries,
        "search_probe": search_text,
        "integrity": {"seconds": round(integrity_seconds, 3), "counts": integrity_counts},
        "storage": {
            "database_bytes": db_page_count * db_page_size,
            "runtime_bytes": directory_bytes(runtime_root),
        },
        "final": {
            "material_count": material_count,
            "ai_requests": ai_requests,
            "target_reached": material_count >= target_count,
            "zero_ai_cost": ai_requests == 0,
        },
    }
    report_path = runtime_root / "stress-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    safe_print(f"REPORT {report_path}")
    safe_print(json.dumps(report["final"], ensure_ascii=False))
    return 0 if report["final"]["target_reached"] and report["final"]["zero_ai_cost"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
