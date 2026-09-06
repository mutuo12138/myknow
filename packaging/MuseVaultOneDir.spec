from pathlib import Path

project_root = Path.cwd()
backend_sources = [(str(path), "backend") for path in (project_root / "backend").glob("*.py")]
datas = [
    *backend_sources,
    (str(project_root / "desktop-ui" / "dist"), "desktop-ui/dist"),
    (str(project_root / "extension"), "extension"),
    (str(project_root / "packaging" / "assets" / "myknow.ico"), "assets"),
]
hiddenimports = [
    "main",
    "worker",
    "ai_adapter",
    "clipboard_bridge",
    "a2wsgi",
    "webview",
    "pystray",
    "pystray._win32",
    "docx",
    "reportlab",
]

a = Analysis(
    [str(project_root / "desktop.py")],
    pathex=[str(project_root / "backend")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tests"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="myknow",
    icon=str(project_root / "packaging" / "assets" / "myknow.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="myknow",
)
