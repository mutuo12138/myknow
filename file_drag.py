"""Small Windows file-drag bridge for the desktop webview.

The bridge exposes a real CF_HDROP IDataObject, which is the same payload
Windows Explorer uses when a file is dragged into another application.
"""

from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes
from pathlib import Path


_DRAG_LOCK = threading.Lock()
_S_OK = 0
_E_NOINTERFACE = -2147467262
_E_NOTIMPL = -2147467263
_E_INVALIDARG = -2147024809
_S_FALSE = 1
_DRAGDROP_S_DROP = 0x00040100
_DRAGDROP_S_CANCEL = 0x00040101
_DRAGDROP_S_USEDEFAULTCURSORS = 0x00040102
_MK_LBUTTON = 0x0001
_CF_HDROP = 15
_TYMED_HGLOBAL = 1
_DVASPECT_CONTENT = 1
_GMEM_MOVEABLE = 0x0002
_GMEM_ZEROINIT = 0x0040
_DROPEFFECT_COPY = 1
_DROPEFFECT_MOVE = 2


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]


class _FORMATETC(ctypes.Structure):
    _fields_ = [
        ("cfFormat", wintypes.WORD),
        ("ptd", ctypes.c_void_p),
        ("dwAspect", wintypes.DWORD),
        ("lindex", wintypes.LONG),
        ("tymed", wintypes.DWORD),
    ]


class _STGMEDIUM(ctypes.Structure):
    _fields_ = [
        ("tymed", wintypes.DWORD),
        ("hGlobal", ctypes.c_void_p),
        ("pUnkForRelease", ctypes.c_void_p),
    ]


class _DROPFILES(ctypes.Structure):
    _fields_ = [
        ("pFiles", wintypes.DWORD),
        ("pt", wintypes.POINT),
        ("fNC", wintypes.BOOL),
        ("fWide", wintypes.BOOL),
    ]


_QueryInterface = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))
_AddRef = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)
_Release = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)
_GetData = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_FORMATETC), ctypes.POINTER(_STGMEDIUM))
_GetDataHere = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_FORMATETC), ctypes.POINTER(_STGMEDIUM))
_QueryGetData = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_FORMATETC))
_GetCanonical = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_FORMATETC), ctypes.POINTER(_FORMATETC))
_SetData = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_FORMATETC), ctypes.POINTER(_STGMEDIUM), wintypes.BOOL)
_EnumFormatEtc = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p))
_Advise = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_FORMATETC), wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD))
_Unadvise = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.DWORD)
_EnumAdvise = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
_QueryContinueDrag = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD)
_GiveFeedback = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.DWORD)


class _DataVtbl(ctypes.Structure):
    _fields_ = [
        ("QueryInterface", _QueryInterface), ("AddRef", _AddRef), ("Release", _Release),
        ("GetData", _GetData), ("GetDataHere", _GetDataHere), ("QueryGetData", _QueryGetData),
        ("GetCanonicalFormatEtc", _GetCanonical), ("SetData", _SetData),
        ("EnumFormatEtc", _EnumFormatEtc), ("DAdvise", _Advise), ("DUnadvise", _Unadvise),
        ("EnumDAdvise", _EnumAdvise),
    ]


class _DropVtbl(ctypes.Structure):
    _fields_ = [("QueryInterface", _QueryInterface), ("AddRef", _AddRef), ("Release", _Release),
                ("QueryContinueDrag", _QueryContinueDrag), ("GiveFeedback", _GiveFeedback)]


class _DataObject(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.POINTER(_DataVtbl))]


class _DropSource(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.POINTER(_DropVtbl))]


def _guid(data1: int, data2: int, data3: int, data4: tuple[int, ...]) -> _GUID:
    value = _GUID(data1, data2, data3, (wintypes.BYTE * 8)(*data4))
    return value


_IID_IUNKNOWN = _guid(0x00000000, 0, 0, (0xC0, 0, 0, 0, 0, 0, 0, 0x46))
_IID_IDATAOBJECT = _guid(0x0000010E, 0, 0, (0xC0, 0, 0, 0, 0, 0, 0, 0x46))
_IID_IDROPSOURCE = _guid(0x00000121, 0, 0, (0xC0, 0, 0, 0, 0, 0, 0, 0x46))
_IID_IENUMFORMATETC = _guid(0x00000103, 0, 0, (0xC0, 0, 0, 0, 0, 0, 0, 0x46))


def _same_guid(left: ctypes.POINTER(_GUID), right: _GUID) -> bool:
    return ctypes.string_at(left, ctypes.sizeof(_GUID)) == bytes(right)


_EnumQI = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))
_EnumRef = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)
_EnumNext = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(_FORMATETC), ctypes.POINTER(wintypes.ULONG))
_EnumSkip = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.ULONG)
_EnumReset = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)
_EnumClone = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))


class _EnumVtbl(ctypes.Structure):
    _fields_ = [("QueryInterface", _EnumQI), ("AddRef", _EnumRef), ("Release", _EnumRef),
                ("Next", _EnumNext), ("Skip", _EnumSkip), ("Reset", _EnumReset), ("Clone", _EnumClone)]


class _FormatEnumerator(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.POINTER(_EnumVtbl))]


def start_file_drag(path: str) -> dict[str, object]:
    """Start a blocking native drag for one existing local file."""
    if os.name != "nt":
        return {"ok": False, "error": "仅 Windows 桌面版支持原生文件拖拽"}
    candidate = Path(str(path or "")).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return {"ok": False, "error": "素材文件不存在，无法拖出"}
    if not resolved.is_file():
        return {"ok": False, "error": "只能拖出本地文件"}
    if not _DRAG_LOCK.acquire(blocking=False):
        return {"ok": False, "error": "已有拖拽操作正在进行"}
    try:
        return _do_drag(str(resolved))
    finally:
        _DRAG_LOCK.release()


def _do_drag(path: str) -> dict[str, object]:
    ole32 = ctypes.WinDLL("ole32")
    kernel32 = ctypes.WinDLL("kernel32")
    ole32.OleInitialize.argtypes = [ctypes.c_void_p]
    ole32.OleInitialize.restype = ctypes.c_long
    ole32.OleUninitialize.argtypes = []
    ole32.DoDragDrop.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    ole32.DoDragDrop.restype = ctypes.c_long
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    coinit = ole32.OleInitialize(None)
    if coinit not in (0, 1, 0x80010106):
        return {"ok": False, "error": f"Windows 拖拽初始化失败：0x{coinit & 0xffffffff:08x}"}

    state = {"refs": 1, "drop_refs": 1, "path": path, "hglobal": None}
    data_obj = _DataObject()
    drop_source = _DropSource()
    format_enum = _FormatEnumerator()
    callbacks: list[object] = []
    enum_callbacks: list[object] = []
    enum_state = {"refs": 1, "index": 0}
    drop_format = _FORMATETC(_CF_HDROP, None, _DVASPECT_CONTENT, -1, _TYMED_HGLOBAL)

    def enum_qi(this, riid, out):
        if not out:
            return _E_INVALIDARG
        if _same_guid(riid, _IID_IUNKNOWN) or _same_guid(riid, _IID_IENUMFORMATETC):
            out[0] = ctypes.cast(ctypes.pointer(format_enum), ctypes.c_void_p).value
            enum_state["refs"] += 1
            return _S_OK
        out[0] = None
        return _E_NOINTERFACE

    def enum_add_ref(_this):
        enum_state["refs"] += 1
        return enum_state["refs"]

    def enum_release(_this):
        enum_state["refs"] = max(0, enum_state["refs"] - 1)
        return enum_state["refs"]

    def enum_next(_this, count, values, fetched):
        if not values or count == 0:
            return _E_INVALIDARG
        if enum_state["index"]:
            if fetched:
                fetched[0] = 0
            return _S_FALSE
        values[0] = drop_format
        enum_state["index"] = 1
        if fetched:
            fetched[0] = 1
        return _S_OK if count == 1 else _S_FALSE

    def enum_skip(_this, count):
        enum_state["index"] = min(1, enum_state["index"] + int(count))
        return _S_OK if enum_state["index"] else _S_FALSE

    def enum_reset(_this):
        enum_state["index"] = 0
        return _S_OK

    def enum_clone(_this, out):
        if not out:
            return _E_INVALIDARG
        out[0] = ctypes.cast(ctypes.pointer(format_enum), ctypes.c_void_p).value
        enum_state["refs"] += 1
        return _S_OK

    enum_callbacks.extend([_EnumQI(enum_qi), _EnumRef(enum_add_ref), _EnumRef(enum_release), _EnumNext(enum_next), _EnumSkip(enum_skip), _EnumReset(enum_reset), _EnumClone(enum_clone)])
    enum_vtbl = _EnumVtbl(*enum_callbacks)
    format_enum.lpVtbl = ctypes.pointer(enum_vtbl)

    def qi(this, riid, out):
        if not out:
            return _E_INVALIDARG
        if _same_guid(riid, _IID_IUNKNOWN) or _same_guid(riid, _IID_IDATAOBJECT):
            out[0] = ctypes.cast(ctypes.pointer(data_obj), ctypes.c_void_p).value
            state["refs"] += 1
            return _S_OK
        out[0] = None
        return _E_NOINTERFACE

    def add_ref(_this):
        state["refs"] += 1
        return state["refs"]

    def release(_this):
        state["refs"] = max(0, state["refs"] - 1)
        return state["refs"]

    def query_get_data(_this, fmt):
        return _S_OK if fmt and fmt.contents.cfFormat == _CF_HDROP and fmt.contents.tymed & _TYMED_HGLOBAL else _E_NOINTERFACE

    def get_data(_this, fmt, medium):
        if query_get_data(_this, fmt) != _S_OK or not medium:
            return _E_NOINTERFACE
        name_bytes = (path + "\0\0").encode("utf-16le")
        header = _DROPFILES()
        header.pFiles = ctypes.sizeof(_DROPFILES)
        header.fWide = 1
        size = ctypes.sizeof(_DROPFILES) + len(name_bytes)
        handle = kernel32.GlobalAlloc(_GMEM_MOVEABLE | _GMEM_ZEROINIT, size)
        if not handle:
            return _E_INVALIDARG
        locked = kernel32.GlobalLock(handle)
        if not locked:
            kernel32.GlobalFree(handle)
            return _E_INVALIDARG
        ctypes.memmove(locked, ctypes.byref(header), ctypes.sizeof(header))
        ctypes.memmove(locked + ctypes.sizeof(header), name_bytes, len(name_bytes))
        kernel32.GlobalUnlock(handle)
        medium.contents.tymed = _TYMED_HGLOBAL
        medium.contents.hGlobal = handle
        medium.contents.pUnkForRelease = None
        return _S_OK

    def enum_format_etcs(_this, direction, out):
        if direction != 1 or not out:
            return _E_NOTIMPL
        enum_state["index"] = 0
        out[0] = ctypes.cast(ctypes.pointer(format_enum), ctypes.c_void_p).value
        enum_state["refs"] += 1
        return _S_OK

    def qi_drop(this, riid, out):
        if not out:
            return _E_INVALIDARG
        if _same_guid(riid, _IID_IUNKNOWN) or _same_guid(riid, _IID_IDROPSOURCE):
            out[0] = ctypes.cast(ctypes.pointer(drop_source), ctypes.c_void_p).value
            state["drop_refs"] += 1
            return _S_OK
        out[0] = None
        return _E_NOINTERFACE

    def drop_add_ref(_this):
        state["drop_refs"] += 1
        return state["drop_refs"]

    def drop_release(_this):
        state["drop_refs"] = max(0, state["drop_refs"] - 1)
        return state["drop_refs"]

    def query_continue(_this, escape, key_state):
        if escape:
            return _DRAGDROP_S_CANCEL
        if not (key_state & _MK_LBUTTON):
            return _DRAGDROP_S_DROP
        return _S_OK

    def give_feedback(_this, _effect):
        return _DRAGDROP_S_USEDEFAULTCURSORS

    def not_impl(*_args): return _E_NOTIMPL

    callbacks.extend([_QueryInterface(qi), _AddRef(add_ref), _Release(release), _GetData(get_data),
                     _GetDataHere(not_impl), _QueryGetData(query_get_data), _GetCanonical(not_impl),
                     _SetData(not_impl), _EnumFormatEtc(enum_format_etcs), _Advise(not_impl), _Unadvise(not_impl),
                     _EnumAdvise(not_impl), _QueryInterface(qi_drop), _AddRef(drop_add_ref),
                     _Release(drop_release), _QueryContinueDrag(query_continue), _GiveFeedback(give_feedback)])
    data_vtbl = _DataVtbl(*callbacks[:12])
    drop_vtbl = _DropVtbl(*callbacks[12:])
    data_obj.lpVtbl = ctypes.pointer(data_vtbl)
    drop_source.lpVtbl = ctypes.pointer(drop_vtbl)
    effect = wintypes.DWORD(0)
    try:
        result = ole32.DoDragDrop(ctypes.byref(data_obj), ctypes.byref(drop_source), _DROPEFFECT_COPY | _DROPEFFECT_MOVE, ctypes.byref(effect))
        ok = result in (_DRAGDROP_S_DROP, _S_OK)
        return {"ok": ok, "effect": int(effect.value), "path": path, "cancelled": result == _DRAGDROP_S_CANCEL, "hresult": int(result) & 0xffffffff}
    finally:
        ole32.OleUninitialize()
