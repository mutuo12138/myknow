# -*- mode: python ; coding: utf-8 -*-
"""myknow macOS (Apple Silicon) application bundle spec.

Built from the Windows working-tree snapshot; mac adaptation items in
macos/PORTING.md still apply. Produces dist/MyKnow.app (onedir BUNDLE).
Ad-hoc sign after build for local use:
    codesign --deep --force -s - dist/MyKnow.app
"""
from pathlib import Path

project_root = Path.cwd()
backend_sources = [(str(path), "backend") for path in (project_root / "backend").glob("*.py")]
datas = [
    *backend_sources,
    (str(project_root / "desktop-ui" / "dist"), "desktop-ui/dist"),
    (str(project_root / "extension"), "extension"),
    (str(project_root / "packaging" / "assets" / "myknow.ico"), "assets"),
    (str(project_root / "packaging" / "assets" / "myknow.icns"), "assets"),
]
hiddenimports = [
    "main",
    "worker",
    "ai_adapter",
    "a2wsgi",
    "webview",
    "pystray",
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
    name="MyKnow",
    icon=str(project_root / "packaging" / "assets" / "myknow.icns"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MyKnow",
)

app = BUNDLE(
    coll,
    name="MyKnow.app",
    icon=str(project_root / "packaging" / "assets" / "myknow.icns"),
    bundle_identifier="com.myknow.desktop",
    version="0.1.1",
    info_plist={
        "CFBundleDisplayName": "myknow",
        "CFBundleShortVersionString": "0.1.1",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "13.0",
    },
)
