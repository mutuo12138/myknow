from __future__ import annotations

import base64
import importlib
import json
import os
from pathlib import Path
import sys
import time
import uuid


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parents[1]
FIXTURES = ROOT / "fixtures"
RUN_ID = time.strftime("%Y%m%d-%H%M%S")
RUN_ROOT = ROOT / "runs" / RUN_ID
DATA_ROOT = RUN_ROOT / "data"
DATA_ROOT.mkdir(parents=True, exist_ok=True)
os.environ["MUSE_VAULT_HOME"] = str(DATA_ROOT)
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

import main  # noqa: E402
import worker  # noqa: E402


def data_url(path: Path) -> str:
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".pdf": "application/pdf"}[path.suffix.lower()]
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def capture_fixture(item: dict) -> str:
    kwargs = {
        "source_url": f"https://fixtures.muse-vault.test/{item['id']}",
        "title": item["title"],
        "material_type": item["material_type"],
        "source_name": "Muse Vault P0-A 固定样本",
    }
    if item["material_type"] == "image":
        path = FIXTURES / item["file"]
        kwargs.update(media_url=kwargs["source_url"], data_url=data_url(path))
    elif item["material_type"] == "page":
        kwargs.update(
            data_url=data_url(FIXTURES / item["preview"]),
            html_content=(FIXTURES / item["file"]).read_text(encoding="utf-8"),
            text_content=f"蓝色头发的本地测试正文 {item['id']}",
        )
    elif item["material_type"] == "document":
        kwargs.update(data_url=data_url(FIXTURES / item["file"]), text_content=f"本地验收文档正文 {item['id']}")
    else:
        kwargs.update(thumbnail_url=(f"https://fixtures.muse-vault.test/{item['preview']}" if item.get("preview") else None))
    result = main.capture(main.CaptureRequest(**kwargs))
    return result["id"]


def drain_worker(max_steps: int = 500) -> None:
    idle = 0
    for _ in range(max_steps):
        if worker.process_one():
            idle = 0
            continue
        idle += 1
        if idle >= 3:
            break
        time.sleep(0.02)


def build_summary(ids: list[str]) -> dict:
    with main.db() as connection:
        rows = [dict(row) for row in connection.execute(
            "SELECT id, material_type, local_path, snapshot_path, status, status_reason FROM materials ORDER BY captured_at"
        )]
        exports = [dict(row) for row in connection.execute("SELECT * FROM offline_exports")]
        jobs = [dict(row) for row in connection.execute("SELECT material_id, stage, state, attempts, last_error FROM jobs")]
    report = main.scan_integrity(repair=False)
    by_type = {kind: len([row for row in rows if row["material_type"] == kind]) for kind in ("image", "page", "document", "video")}
    page_rows = [row for row in rows if row["material_type"] == "page"]
    result = {
        "run_id": RUN_ID,
        "data_root": str(DATA_ROOT),
        "captured_ids": ids,
        "material_count": len(rows),
        "by_type": by_type,
        "all_statuses": sorted({row["status"] for row in rows}),
        "page_snapshots": sum(bool(row["snapshot_path"]) for row in page_rows),
        "ready_exports": sum(row["state"] == "ready" for row in exports),
        "failed_jobs": [job for job in jobs if job["state"] == "dead"],
        "integrity": report,
        "pass": (
            len(rows) == 20 and by_type == {"image": 5, "page": 5, "document": 5, "video": 5}
            and not report["missing_files"] and not report["orphan_files"] and not report["orphan_staging"]
            and not report["recovery_files"] and not report["dead_ready"] and not report["duplicate_fts"] and not report["stale_fts"]
            and all(row["status"] == "ready" for row in rows)
            and len(page_rows) == 5 and all(row["snapshot_path"] for row in page_rows)
            and sum(row["state"] == "ready" for row in exports) == 5
        ),
    }
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    (RUN_ROOT / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_ROOT / "summary.md").write_text(
        "# Muse Vault P0-A 验收运行\n\n" + json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def main_run() -> None:
    main.init_db()
    manifest = json.loads((ROOT / "fixtures-manifest.json").read_text(encoding="utf-8"))
    ids = [capture_fixture(item) for item in manifest["items"]]
    drain_worker()
    result = build_summary(ids)
    print(json.dumps({"run_id": RUN_ID, "pass": result["pass"], "data_root": str(DATA_ROOT), "material_count": result["material_count"]}, ensure_ascii=False))
    if not result["pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main_run()
