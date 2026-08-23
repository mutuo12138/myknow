from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, cwd: Path | None = None) -> None:
    print("$", " ".join(command))
    subprocess.run(command, cwd=cwd, check=True)


def copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, dirs_exist_ok=True)


def main() -> int:
    python = Path(sys.executable)
    release_root = ROOT / "releases"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    package_name = f"MuseVault-Portable-{stamp}"
    package_root = release_root / package_name
    build_root = release_root / f"_build-{stamp}"
    zip_path = release_root / f"{package_name}.zip"
    package_root.mkdir(parents=True, exist_ok=False)
    build_root.mkdir(parents=True, exist_ok=False)

    print("1/5 Build frontend production files...")
    run(["npm.cmd", "run", "build"], cwd=ROOT / "desktop-ui")

    print("2/5 Check and install packaging dependencies...")
    run(
        [str(python), "-m", "pip", "install", "-r", "packaging\\requirements-packaging.txt"],
        cwd=ROOT,
    )

    print("3/5 Build myknow.exe...")
    run(
        [
            str(python),
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(Path("releases") / package_name),
            "--workpath",
            str(Path("releases") / f"_build-{stamp}"),
            "packaging\\MuseVault.spec",
        ],
        cwd=ROOT,
    )
    exe_path = package_root / "myknow.exe"
    if not exe_path.is_file():
        raise RuntimeError("PyInstaller did not generate myknow.exe")

    print("4/5 Add browser extension and sanitized instructions...")
    copy_tree(ROOT / "extension", package_root / "extension")
    shutil.copy2(ROOT / "packaging" / "RELEASE_README.md", package_root / "README.md")
    shutil.copy2(ROOT / "packaging" / "INSTALL_BROWSER_EXTENSION.md", package_root / "INSTALL_BROWSER_EXTENSION.md")

    print("5/5 Create sanitized ZIP...")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package_root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(package_root).as_posix())

    print(f"Release ZIP: {zip_path}")
    print(f"Unpacked test directory: {package_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
