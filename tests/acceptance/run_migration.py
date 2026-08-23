from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parents[1]
RUN_ID = time.strftime("%Y%m%d-%H%M%S")
RUN_ROOT = ROOT / "migration-runs" / RUN_ID
DATA_ROOT = RUN_ROOT / "data"
DATA_ROOT.mkdir(parents=True, exist_ok=True)
for folder_name in ("assets", "recovery"):
    source_folder = PROJECT_ROOT / "data" / folder_name
    if source_folder.exists():
        shutil.copytree(source_folder, DATA_ROOT / folder_name)
source_database = sqlite3.connect(PROJECT_ROOT / "data" / "muse-vault.db")
target_database = sqlite3.connect(DATA_ROOT / "muse-vault.db")
source_database.backup(target_database)
target_database.close()
source_database.close()
source_prefix = str((PROJECT_ROOT / "data").resolve())
target_prefix = str(DATA_ROOT.resolve())
remap_connection = sqlite3.connect(DATA_ROOT / "muse-vault.db")
for table, columns in {
    "materials": ("local_path", "snapshot_path"),
    "offline_exports": ("html_path", "pdf_path", "docx_path"),
    "capture_operations": ("local_staged_path", "local_final_path", "snapshot_staged_path", "snapshot_final_path"),
}.items():
    for column in columns:
        remap_connection.execute(
            f"UPDATE {table} SET {column}=REPLACE({column}, ?, ?) WHERE {column} LIKE ?",
            (source_prefix, target_prefix, source_prefix + "%"),
        )
remap_connection.commit()
remap_connection.close()

before_connection = sqlite3.connect(DATA_ROOT / "muse-vault.db")
before = {
    "materials": before_connection.execute("SELECT COUNT(*) FROM materials").fetchone()[0],
    "fts": before_connection.execute("SELECT COUNT(*) FROM materials_fts").fetchone()[0],
    "fts_sql": before_connection.execute("SELECT sql FROM sqlite_master WHERE name='materials_fts'").fetchone()[0],
}
before_connection.close()

os.environ["MUSE_VAULT_HOME"] = str(DATA_ROOT)
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
import main  # noqa: E402


def run() -> None:
    main.init_db()
    integrity = main.scan_integrity(repair=False)
    with main.db() as connection:
        after = {
            "materials": connection.execute("SELECT COUNT(*) FROM materials").fetchone()[0],
            "fts": connection.execute("SELECT COUNT(*) FROM materials_fts").fetchone()[0],
            "fts_sql": connection.execute("SELECT sql FROM sqlite_master WHERE name='materials_fts'").fetchone()[0],
            "integrity_check": connection.execute("PRAGMA integrity_check").fetchone()[0],
            "journal_mode": connection.execute("PRAGMA journal_mode").fetchone()[0],
        }
    passed = (
        before["materials"] == after["materials"] == 3 and after["fts"] == 3
        and "trigram" in after["fts_sql"].lower() and after["integrity_check"] == "ok"
        and after["journal_mode"] == "wal" and not integrity["missing_files"]
        and not integrity["orphan_files"] and not integrity["duplicate_fts"] and not integrity["stale_fts"]
    )
    summary = {"run_id": RUN_ID, "source": str(PROJECT_ROOT / "data"), "copy": str(DATA_ROOT), "before": before, "after": after, "integrity": integrity, "pass": passed}
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    (RUN_ROOT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (RUN_ROOT / "summary.md").write_text("# Muse Vault 正式库复制迁移验收\n\n" + json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"run_id": RUN_ID, "pass": passed, "before": before["materials"], "after": after["materials"], "fts": after["fts"]}, ensure_ascii=False))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    run()
