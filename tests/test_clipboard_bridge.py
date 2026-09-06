from __future__ import annotations

import ctypes
import io
from pathlib import Path

from PIL import Image

from clipboard_bridge import (
    _DROPFILES,
    build_dib_bytes,
    build_hdrop_bytes,
    build_png_bytes,
    build_preferred_drop_effect_bytes,
    copy_file_to_clipboard,
)


def test_hdrop_payload_is_wide_and_contains_the_file_path() -> None:
    path = r"E:\素材库\测试图片.png"
    payload = build_hdrop_bytes(path)
    header = _DROPFILES.from_buffer_copy(payload[: ctypes.sizeof(_DROPFILES)])
    assert header.pFiles == ctypes.sizeof(_DROPFILES)
    assert header.fWide == 1
    assert payload[header.pFiles :].decode("utf-16le").rstrip("\0") == path


def test_dib_payload_has_bitmap_info_header_without_file_header(tmp_path: Path) -> None:
    image_path = tmp_path / "clipboard.png"
    Image.new("RGB", (8, 6), (40, 120, 200)).save(image_path)
    dib = build_dib_bytes(image_path)
    assert int.from_bytes(dib[:4], "little") == 40
    assert int.from_bytes(dib[4:8], "little", signed=True) == 8
    assert int.from_bytes(dib[8:12], "little", signed=True) == 6


def test_png_payload_is_valid_and_preserves_dimensions(tmp_path: Path) -> None:
    image_path = tmp_path / "clipboard.jpg"
    Image.new("RGB", (9, 7), (80, 30, 180)).save(image_path)
    png = build_png_bytes(image_path)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(io.BytesIO(png)) as copied:
        assert copied.size == (9, 7)
        assert copied.mode == "RGBA"


def test_preferred_drop_effect_is_copy() -> None:
    assert build_preferred_drop_effect_bytes() == (1).to_bytes(4, "little")


def test_missing_file_is_rejected_without_touching_clipboard(tmp_path: Path) -> None:
    result = copy_file_to_clipboard(str(tmp_path / "missing.png"))
    assert result["ok"] is False
    assert "不存在" in result["error"]
