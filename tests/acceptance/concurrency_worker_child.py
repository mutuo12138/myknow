from __future__ import annotations

import os
from pathlib import Path
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
import main  # noqa: E402
import worker  # noqa: E402


def run() -> None:
    stop = Path(os.environ["MUSE_CONCURRENCY_STOP"])
    main.init_db()
    idle = 0
    deadline = time.time() + 45
    while time.time() < deadline:
        if worker.process_one():
            idle = 0
            continue
        idle += 1
        if stop.exists() and idle >= 10:
            return
        time.sleep(0.02)
    raise TimeoutError("concurrency worker did not drain before deadline")


if __name__ == "__main__":
    run()
