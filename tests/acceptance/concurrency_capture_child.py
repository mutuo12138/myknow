from __future__ import annotations

import json
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
import main  # noqa: E402


def run() -> None:
    producer = int(os.environ["MUSE_CONCURRENCY_PRODUCER"])
    count = int(os.environ["MUSE_CONCURRENCY_COUNT"])
    main.init_db()
    ids = []
    for index in range(count):
        result = main.capture(main.CaptureRequest(
            source_url=f"https://concurrency.muse-vault.test/article?producer={producer}&item={index}",
            title=f"并发采集 {producer}-{index}",
            material_type="page" if index % 2 == 0 else "link",
            text_content=f"并发数据库写入验收 producer={producer} item={index}",
        ))
        ids.append(result["id"])
    print(json.dumps({"producer": producer, "count": len(ids)}))


if __name__ == "__main__":
    run()
