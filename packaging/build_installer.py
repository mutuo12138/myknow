from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_VERSION = "0.1.1"


def run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print("$", " ".join(command))
    subprocess.run(command, cwd=cwd, env=env, check=True)


def remove_release_temp(path: Path, release_root: Path) -> None:
    resolved = path.resolve()
    root = release_root.resolve()
    if not resolved.is_relative_to(root) or not path.name.startswith(("_installer-", "_packaging-venv-")):
        raise RuntimeError(f"Refusing to remove unexpected build path: {resolved}")
    shutil.rmtree(resolved, ignore_errors=True)


def run_in_isolated_environment() -> int:
    release_root = ROOT / "releases"
    release_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    venv_root = release_root / f"_packaging-venv-{stamp}"
    venv_python = venv_root / "Scripts" / "python.exe"
    venv_root.mkdir(parents=True, exist_ok=False)
    try:
        run([sys.executable, "-m", "venv", str(venv_root)], cwd=ROOT)
        environment = os.environ.copy()
        environment["MYKNOW_BUILD_ISOLATED"] = "1"
        # Do not touch the user's global pip cache. This keeps builds
        # reproducible on locked-down Windows profiles and CI runners.
        environment["PIP_NO_CACHE_DIR"] = "1"
        environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        run([str(venv_python), str(Path(__file__).resolve())], cwd=ROOT, env=environment)
        return 0
    finally:
        remove_release_temp(venv_root, release_root)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_release_manifest(app_stage: Path) -> None:
    files = []
    for path in sorted(item for item in app_stage.rglob("*") if item.is_file() and item.name != "RELEASE-MANIFEST.json"):
        files.append({
            "path": path.relative_to(app_stage).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    manifest = {
        "product": "myknow",
        "version": APP_VERSION,
        "files": files,
    }
    (app_stage / "RELEASE-MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def sensitive_markers() -> list[tuple[str, bytes]]:
    values = {
        "home-path": str(Path.home()),
        "source-root": str(ROOT),
        "ai-api-key-environment": os.getenv("MUSE_AI_API_KEY", ""),
        "ai-api-url-environment": os.getenv("MUSE_AI_BASE_URL", ""),
    }
    markers: list[tuple[str, bytes]] = []
    for label, value in values.items():
        if len(value) < 5:
            continue
        markers.append((label, value.encode("utf-8")))
        markers.append((label + "-utf16", value.encode("utf-16-le")))
    return markers


def verify_release_is_sanitized(paths: list[Path]) -> None:
    markers = sensitive_markers()
    for root in paths:
        candidates = [root] if root.is_file() else [item for item in root.rglob("*") if item.is_file()]
        for path in candidates:
            data = path.read_bytes()
            for label, marker in markers:
                if marker in data:
                    raise RuntimeError(f"Release sanitization failed ({label}) in {path.name}")


def smoke_test_frozen_app(app_stage: Path) -> None:
    """Boot the exact frozen API from the staging folder with disposable data."""
    temp_root = Path(tempfile.mkdtemp(prefix="myknow-frozen-smoke-"))
    temp_base = Path(tempfile.gettempdir()).resolve()
    if not temp_root.resolve().is_relative_to(temp_base):
        raise RuntimeError("Frozen smoke directory escaped TEMP")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    environment = os.environ.copy()
    environment.update({
        "MUSE_VAULT_HOME": str(temp_root / "data"),
        "MUSE_VAULT_LOG_DIR": str(temp_root / "logs"),
        "MUSE_VAULT_UI_DIST": str(app_stage / "_internal" / "desktop-ui" / "dist"),
        "MUSE_VAULT_EXTENSION_ROOT": str(app_stage / "extension"),
        "MUSE_VAULT_API_PORT": str(port),
    })
    process = subprocess.Popen(
        [str(app_stage / "myknow.exe"), "--service", "api"],
        cwd=app_stage,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        deadline = time.monotonic() + 25
        health = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Frozen API exited during smoke test: {process.returncode}")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
                    health = json.loads(response.read().decode("utf-8"))
                break
            except (OSError, ValueError, urllib.error.URLError):
                time.sleep(0.25)
        if health != {"ok": True, "service": "myknow-local-api", "version": APP_VERSION}:
            raise RuntimeError(f"Frozen health contract failed: {health!r}")
        hostile = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/materials",
            headers={"Origin": "https://malicious.example"},
        )
        try:
            urllib.request.urlopen(hostile, timeout=2)
        except urllib.error.HTTPError as error:
            if error.code != 403:
                raise RuntimeError(f"Frozen origin guard returned {error.code}") from error
        else:
            raise RuntimeError("Frozen origin guard accepted an untrusted website")
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
            if b"<!doctype html" not in response.read(4096).lower():
                raise RuntimeError("Frozen desktop UI did not load")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        shutil.rmtree(temp_root, ignore_errors=True)


def main() -> int:
    if os.getenv("MYKNOW_BUILD_ISOLATED") != "1":
        return run_in_isolated_environment()
    python = Path(sys.executable)
    release_root = ROOT / "releases"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stage_name = f"_installer-stage-{stamp}"
    build_name = f"_installer-build-{stamp}"
    stage_root = release_root / stage_name
    build_root = release_root / build_name
    installer_name = f"myknow-Setup-{stamp}"
    installer_path = release_root / f"{installer_name}.exe"
    stage_root.mkdir(parents=True, exist_ok=False)
    build_root.mkdir(parents=True, exist_ok=False)
    try:
        print("1/5 Build frontend production files...")
        run(["npm.cmd", "run", "build"], cwd=ROOT / "desktop-ui")

        print("2/5 Check and install runtime and packaging dependencies...")
        run([str(python), "-m", "pip", "install", "-r", "packaging\\requirements-packaging.txt"], cwd=ROOT)

        print("3/5 Build onedir application files...")
        run(
            [
                str(python),
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--distpath",
                str(Path("releases") / stage_name),
                "--workpath",
                str(Path("releases") / build_name),
                "packaging\\MuseVaultOneDir.spec",
            ],
            cwd=ROOT,
        )
        app_stage = stage_root / "myknow"
        exe_path = app_stage / "myknow.exe"
        if not exe_path.is_file():
            raise RuntimeError("PyInstaller did not generate the onedir application")
        shutil.copytree(ROOT / "extension", app_stage / "extension", dirs_exist_ok=True)
        shutil.copy2(ROOT / "packaging" / "RELEASE_README.md", stage_root / "README.md")
        shutil.copy2(ROOT / "packaging" / "INSTALL_BROWSER_EXTENSION.md", stage_root / "INSTALL_BROWSER_EXTENSION.md")
        smoke_test_frozen_app(app_stage)
        write_release_manifest(app_stage)
        verify_release_is_sanitized([app_stage, stage_root / "README.md", stage_root / "INSTALL_BROWSER_EXTENSION.md"])

        print("4/5 Compile Windows installer...")
        iscc = Path.home() / "AppData" / "Local" / "Programs" / "Inno Setup 6" / "ISCC.exe"
        if not iscc.is_file():
            raise RuntimeError(f"Inno Setup compiler not found: {iscc}")
        run(
            [
                str(iscc),
                f"/DSourceDir=..\\releases\\{stage_name}",
                "/DOutputDir=..\\releases",
                f"/DOutputBaseName={installer_name}",
                "packaging\\MuseVault.iss",
            ],
            cwd=ROOT,
        )
        if not installer_path.is_file():
            raise RuntimeError("Inno Setup did not generate the installer")
        verify_release_is_sanitized([installer_path])
        print("5/5 Installer ready:", installer_path)
        print("SHA256:", sha256_file(installer_path))
        return 0
    finally:
        remove_release_temp(stage_root, release_root)
        remove_release_temp(build_root, release_root)


if __name__ == "__main__":
    raise SystemExit(main())
