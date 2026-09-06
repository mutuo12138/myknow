"""Safe Windows clipboard bridge for local material files.

The desktop UI uses this instead of starting a blocking OLE drag session.  It
places an Explorer-compatible file list on the clipboard and, for images, also
adds bitmap pixels so Ctrl+V works in both file destinations and image-aware
editors.
"""

from __future__ import annotations

import ctypes
import io
import os
import time
from ctypes import wintypes
from pathlib import Path


_CF_DIB = 8
_CF_UNICODETEXT = 13
_CF_HDROP = 15
_DROPEFFECT_COPY = 1
_GMEM_MOVEABLE = 0x0002
_GMEM_ZEROINIT = 0x0040


class _DROPFILES(ctypes.Structure):
    _fields_ = [
        ("pFiles", wintypes.DWORD),
        ("pt", wintypes.POINT),
        ("fNC", wintypes.BOOL),
        ("fWide", wintypes.BOOL),
    ]


def build_hdrop_bytes(path: str) -> bytes:
    """Build a CF_HDROP payload containing one absolute Windows path."""
    header = _DROPFILES()
    header.pFiles = ctypes.sizeof(_DROPFILES)
    header.fWide = 1
    names = (path + "\0\0").encode("utf-16le")
    return ctypes.string_at(ctypes.byref(header), ctypes.sizeof(header)) + names


def build_dib_bytes(path: Path) -> bytes:
    """Build CF_DIB bytes from an image without the BMP file header."""
    from PIL import Image

    with Image.open(path) as source:
        image = source.convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="BMP")
    return buffer.getvalue()[14:]


def build_png_bytes(path: Path) -> bytes:
    """Build a registered PNG clipboard payload for Chromium-style targets."""
    from PIL import Image

    with Image.open(path) as source:
        image = source.convert("RGBA")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
    return buffer.getvalue()


def build_preferred_drop_effect_bytes() -> bytes:
    """Tell file-aware paste targets that this is a copy, never a move."""
    return _DROPEFFECT_COPY.to_bytes(4, "little")


def _allocate_global(data: bytes) -> int:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    handle = kernel32.GlobalAlloc(_GMEM_MOVEABLE | _GMEM_ZEROINIT, len(data))
    if not handle:
        raise OSError(ctypes.get_last_error(), "无法分配剪贴板内存")
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        kernel32.GlobalFree(handle)
        raise OSError(ctypes.get_last_error(), "无法写入剪贴板内存")
    ctypes.memmove(pointer, data, len(data))
    kernel32.GlobalUnlock(handle)
    return int(handle)


def copy_file_to_clipboard(path: str) -> dict[str, object]:
    """Copy one verified local file to the Windows clipboard without dragging."""
    candidate = Path(str(path or "")).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return {"ok": False, "error": "素材文件不存在，无法复制"}
    if not resolved.is_file():
        return {"ok": False, "error": "只能复制本地文件"}
    if os.name != "nt":
        return {"ok": False, "error": "仅 Windows 桌面版支持文件剪贴板"}

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterClipboardFormatW.restype = wintypes.UINT
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]

    preferred_drop_effect_format = user32.RegisterClipboardFormatW("Preferred DropEffect")
    png_format = user32.RegisterClipboardFormatW("PNG")
    payloads: list[tuple[int, bytes, str]] = [
        (_CF_HDROP, build_hdrop_bytes(str(resolved)), "file"),
    ]
    if preferred_drop_effect_format:
        payloads.append((preferred_drop_effect_format, build_preferred_drop_effect_bytes(), "copy-effect"))
    try:
        png_bytes = build_png_bytes(resolved)
        dib_bytes = build_dib_bytes(resolved)
        if png_format:
            payloads.append((png_format, png_bytes, "png"))
        payloads.append((_CF_DIB, dib_bytes, "image"))
    except Exception:
        # Non-image files still remain fully usable through CF_HDROP.
        pass
    payloads.append((_CF_UNICODETEXT, (str(resolved) + "\0").encode("utf-16le"), "text"))

    opened = False
    for _ in range(12):
        if user32.OpenClipboard(None):
            opened = True
            break
        time.sleep(0.025)
    if not opened:
        return {"ok": False, "error": "剪贴板正被其他程序占用，请稍后再试"}

    formats: list[str] = []
    try:
        if not user32.EmptyClipboard():
            raise OSError(ctypes.get_last_error(), "无法清空剪贴板")

        for clipboard_format, data, label in payloads:
            handle = _allocate_global(data)
            if not user32.SetClipboardData(clipboard_format, handle):
                kernel32.GlobalFree(handle)
                if clipboard_format == _CF_HDROP:
                    raise OSError(ctypes.get_last_error(), "无法把文件写入剪贴板")
                continue
            # Ownership transfers to Windows after SetClipboardData succeeds.
            formats.append(label)
        return {"ok": True, "path": str(resolved), "formats": formats}
    except OSError as error:
        return {"ok": False, "error": str(error)}
    finally:
        user32.CloseClipboard()
