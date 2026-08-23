from __future__ import annotations

import base64
from io import BytesIO
import os
from pathlib import Path
import sys
import time

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
import main  # noqa: E402


def signal_and_wait(marker: Path, stage: str) -> None:
    marker.write_text(stage, encoding="utf-8")
    time.sleep(120)


def unique_png_data_url(index: int) -> str:
    image = Image.new("RGB", (16, 16), ((index * 37) % 255, (index * 73) % 255, (index * 109) % 255))
    output = BytesIO()
    image.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def run() -> None:
    scenario = os.environ["MUSE_INTERRUPT_SCENARIO"]
    marker = Path(os.environ["MUSE_INTERRUPT_MARKER"])
    index = int(os.environ["MUSE_INTERRUPT_INDEX"])
    main.init_db()

    if scenario == "before_write":
        original = main.write_capture_files

        def pause_before_write(*args, **kwargs):
            signal_and_wait(marker, scenario)
            return original(*args, **kwargs)

        main.write_capture_files = pause_before_write
    elif scenario == "after_stage":
        original = main.write_staged_file

        def pause_after_stage(*args, **kwargs):
            result = original(*args, **kwargs)
            signal_and_wait(marker, scenario)
            return result

        main.write_staged_file = pause_after_stage
    elif scenario == "before_commit":
        original = main.commit_capture_operation

        def pause_before_commit(*args, **kwargs):
            signal_and_wait(marker, scenario)
            return original(*args, **kwargs)

        main.commit_capture_operation = pause_before_commit
    else:
        raise ValueError(f"unknown scenario: {scenario}")

    main.capture(main.CaptureRequest(
        source_url=f"https://interruptions.muse-vault.test/image-{index}",
        title=f"中断验收图片 {index}",
        material_type="image",
        media_url=f"https://interruptions.muse-vault.test/image-{index}.png",
        data_url=unique_png_data_url(index),
    ))


if __name__ == "__main__":
    run()
