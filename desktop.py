from __future__ import annotations

import argparse
import ctypes
import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
LOCAL_APP_DATA = Path(os.getenv("LOCALAPPDATA", Path.home())) / "myknow"
LEGACY_LOCAL_APP_DATA = Path(os.getenv("LOCALAPPDATA", Path.home())) / "MuseVault"
SETTINGS_PATH = Path(os.getenv("MUSE_VAULT_DESKTOP_SETTINGS", LOCAL_APP_DATA / "settings.json"))
LEGACY_SETTINGS_PATH = LEGACY_LOCAL_APP_DATA / "settings.json"


def application_icon_path() -> Path:
    if getattr(sys, "frozen", False):
        return ROOT / "assets" / "myknow.ico"
    return Path(__file__).resolve().parent / "packaging" / "assets" / "myknow.ico"


def default_data_root() -> Path:
    if getattr(sys, "frozen", False):
        legacy = Path.home() / "Documents" / "Muse Vault"
        current = Path.home() / "Documents" / "myknow"
        if legacy.exists() and not current.exists():
            return legacy
        return current
    return ROOT / "data"


def load_settings() -> dict:
    candidates = [SETTINGS_PATH]
    if not os.getenv("MUSE_VAULT_DESKTOP_SETTINGS") and LEGACY_SETTINGS_PATH != SETTINGS_PATH:
        candidates.append(LEGACY_SETTINGS_PATH)
    for path in candidates:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return value
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def save_settings(data_root: Path, log_root: Path) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "data_root": str(data_root.resolve()),
        "log_root": str(log_root.resolve()),
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    temporary = SETTINGS_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, SETTINGS_PATH)


def validate_storage_paths(data_root: Path, log_root: Path) -> None:
    """Keep user data outside the installed program directory.

    Inno Setup owns the application directory. Refusing that location prevents
    an uninstall or upgrade from ever being able to remove the material store.
    """
    if not getattr(sys, "frozen", False):
        return
    install_root = Path(sys.executable).resolve().parent
    for label, candidate in (("数据与素材", data_root), ("日志", log_root)):
        resolved = candidate.expanduser().resolve()
        if resolved == install_root or resolved.is_relative_to(install_root):
            raise ValueError(f"{label}目录不能放在 myknow 安装目录内，请选择文档盘或其他素材盘")


def configured_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    settings = load_settings()
    configured_data = args.data_dir or os.getenv("MUSE_VAULT_HOME") or settings.get("data_root")
    data_root = Path(configured_data).expanduser() if configured_data else default_data_root()
    configured_logs = args.log_dir or os.getenv("MUSE_VAULT_LOG_DIR") or settings.get("log_root")
    log_root = Path(configured_logs).expanduser() if configured_logs else data_root / "logs"
    validate_storage_paths(data_root, log_root)
    data_root.mkdir(parents=True, exist_ok=True)
    log_root.mkdir(parents=True, exist_ok=True)
    return data_root.resolve(), log_root.resolve()


def configure_interactively() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox

    settings = load_settings()
    current_data = Path(settings.get("data_root") or default_data_root()).expanduser()
    current_logs = Path(settings.get("log_root") or current_data / "logs").expanduser()
    root = tk.Tk()
    root.withdraw()
    root.update_idletasks()
    try:
        selected_data = filedialog.askdirectory(
            title="选择 myknow 数据与素材存放位置",
            initialdir=str(current_data if current_data.exists() else current_data.parent),
            mustexist=False,
        )
        if not selected_data:
            return 1
        data_root = Path(selected_data)
        selected_logs = filedialog.askdirectory(
            title="选择 myknow 日志存放位置（取消则保存在数据目录的 logs 文件夹）",
            initialdir=str(current_logs if current_logs.exists() else data_root),
            mustexist=False,
        )
        log_root = Path(selected_logs) if selected_logs else data_root / "logs"
        try:
            validate_storage_paths(data_root, log_root)
        except ValueError as error:
            messagebox.showerror("不能使用该目录", str(error))
            return 1
        data_root.mkdir(parents=True, exist_ok=True)
        log_root.mkdir(parents=True, exist_ok=True)
        if current_data.resolve() != data_root.resolve() and (current_data / "muse-vault.db").exists():
            proceed = messagebox.askokcancel(
                "确认切换素材库位置",
                "切换位置不会自动移动旧素材。旧库会保留在原位置，新位置将在下次启动时使用。\n\n"
                "如需迁移旧库，请先取消并备份原数据目录。是否继续保存新路径？",
            )
            if not proceed:
                return 1
        save_settings(data_root, log_root)
        messagebox.showinfo(
            "路径已保存",
            f"数据与素材：{data_root.resolve()}\n日志：{log_root.resolve()}\n\n下次启动 myknow 时生效。",
        )
        return 0
    finally:
        root.destroy()


class DesktopApi:
    def __init__(self) -> None:
        # Keep the native window private. Public attributes on a pywebview
        # js_api object are serialized into JavaScript; exposing the WinForms
        # object here makes pywebview recurse through AccessibilityObject and
        # can hang the native window on Windows.
        self._window = None

    def configure_paths(self) -> dict:
        import webview

        if self._window is None:
            return {"ok": False, "error": "原生窗口尚未就绪"}
        settings = load_settings()
        current_data = Path(settings.get("data_root") or default_data_root()).expanduser()
        current_logs = Path(settings.get("log_root") or current_data / "logs").expanduser()
        selected_data = self._window.create_file_dialog(
            webview.FOLDER_DIALOG,
            directory=str(current_data if current_data.exists() else current_data.parent),
        )
        if not selected_data:
            return {"ok": False, "cancelled": True}
        data_root = Path(selected_data[0])
        selected_logs = self._window.create_file_dialog(
            webview.FOLDER_DIALOG,
            directory=str(current_logs if current_logs.exists() else data_root),
        )
        log_root = Path(selected_logs[0]) if selected_logs else data_root / "logs"
        try:
            validate_storage_paths(data_root, log_root)
        except ValueError as error:
            return {"ok": False, "error": str(error)}
        if current_data.resolve() != data_root.resolve() and (current_data / "muse-vault.db").exists():
            proceed = self._window.create_confirmation_dialog(
                "确认切换素材库位置",
                "切换位置不会自动移动旧素材。旧库会保留在原位置，新位置将在下次启动时使用。是否继续？",
            )
            if not proceed:
                return {"ok": False, "cancelled": True}
        try:
            data_root.mkdir(parents=True, exist_ok=True)
            log_root.mkdir(parents=True, exist_ok=True)
            save_settings(data_root, log_root)
            return {
                "ok": True,
                "data_root": str(data_root.resolve()),
                "log_root": str(log_root.resolve()),
                "restart_required": True,
            }
        except OSError as error:
            return {"ok": False, "error": str(error)}

    def choose_import_folder(self) -> dict:
        """Return a user-approved local folder for reference-mode imports."""
        import webview

        if self._window is None:
            return {"ok": False, "error": "原生窗口尚未就绪"}
        try:
            selected = self._window.create_file_dialog(webview.FOLDER_DIALOG, directory=str(Path.home()))
            if not selected:
                return {"ok": False, "cancelled": True}
            return {"ok": True, "path": str(Path(selected[0]).resolve())}
        except OSError as error:
            return {"ok": False, "error": str(error)}

    def start_file_drag(self, path: str) -> dict:
        """Legacy guard: native OLE dragging is disabled to protect system input."""
        return {
            "ok": False,
            "error": "文件拖出功能已停用，请使用“复制到剪贴板”后按 Ctrl+V",
        }

    def copy_file_to_clipboard(self, path: str) -> dict:
        """Copy one verified local material to the Windows clipboard."""
        from clipboard_bridge import copy_file_to_clipboard

        return copy_file_to_clipboard(path)

    def save_extension(self) -> dict:
        """Save the bundled browser extension through the native file dialog."""
        import webview

        if self._window is None:
            return {"ok": False, "error": "原生窗口尚未就绪"}
        extension_root = ROOT / "extension"
        manifest_path = extension_root / "manifest.json"
        if not extension_root.is_dir() or not manifest_path.is_file():
            return {"ok": False, "error": "当前版本没有找到随产品打包的浏览器扩展"}
        downloads = Path.home() / "Downloads"
        dialog_type = getattr(getattr(webview, "FileDialog", None), "SAVE", getattr(webview, "SAVE_DIALOG", 30))
        try:
            selected = self._window.create_file_dialog(
                dialog_type,
                directory=str(downloads if downloads.is_dir() else Path.home()),
                save_filename="myknow-extension.zip",
                file_types=("ZIP 文件 (*.zip)",),
            )
            if not selected:
                return {"ok": False, "cancelled": True}
            target = Path(selected[0]).expanduser()
            if target.suffix.lower() != ".zip":
                target = target.with_name(target.name + ".zip")
            target.parent.mkdir(parents=True, exist_ok=True)
            archive = io.BytesIO()
            root_resolved = extension_root.resolve()
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                for path in sorted(extension_root.rglob("*")):
                    if not path.is_file() or path.is_symlink() or path.name in {".DS_Store", "Thumbs.db"}:
                        continue
                    try:
                        relative = path.resolve().relative_to(root_resolved).as_posix()
                    except ValueError:
                        continue
                    bundle.write(path, f"myknow-extension/{relative}")
            target.write_bytes(archive.getvalue())
            return {"ok": True, "path": str(target.resolve()), "bytes": target.stat().st_size}
        except OSError as error:
            return {"ok": False, "error": f"保存浏览器扩展失败：{error}"}


def append_launcher_log(log_root: Path, message: str) -> None:
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    with (log_root / "launcher.log").open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] {message}\n")


def start_process(command: list[str], cwd: Path, env: dict, log_path: Path) -> tuple[subprocess.Popen, object]:
    handle = log_path.open("ab", buffering=0)
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return process, handle
    except Exception:
        handle.close()
        raise


def wait_for_server(process: subprocess.Popen, port: int, timeout: float | None = None) -> None:
    if timeout is None:
        # The installer uses PyInstaller onedir, so a healthy API should be
        # ready quickly. A short bound prevents a port conflict from looking
        # like a frozen application.
        timeout = 20
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"本机服务启动失败，退出代码 {process.returncode}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
                if response.status == 200:
                    return
        except Exception as error:
            last_error = str(error)
        time.sleep(0.25)
    raise RuntimeError(f"本机服务启动超时：{last_error}")


def port_in_use(port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        probe.close()


def show_startup_error(error: Exception) -> None:
    message = f"myknow 启动失败：\n\n{error}"
    if os.name == "nt":
        try:
            ctypes.windll.user32.MessageBoxW(0, message, "myknow", 0x10)
            return
        except Exception:
            pass
    print(message, file=sys.stderr)


def stop_processes(processes: list[subprocess.Popen]) -> None:
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 5
    for process in reversed(processes):
        if process.poll() is not None:
            continue
        try:
            process.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            process.kill()


class TrayController:
    """Keep the native window available from the Windows notification area."""

    def __init__(self, window, icon_path: Path, log_root: Path) -> None:
        self.window = window
        self.icon_path = icon_path
        self.log_root = log_root
        self._icon = None
        self._thread: threading.Thread | None = None
        self._allow_close = False
        self._lock = threading.Lock()

    def start(self) -> None:
        import pystray
        from PIL import Image

        if not self.icon_path.is_file():
            append_launcher_log(self.log_root, f"tray_skipped icon_missing={self.icon_path}")
            return
        image = Image.open(self.icon_path).convert("RGBA")
        menu = pystray.Menu(
            pystray.MenuItem("打开 myknow", self._show_window, default=True),
            pystray.MenuItem("退出 myknow", self._exit_application),
        )
        self._icon = pystray.Icon("myknow", image, "myknow", menu)
        self._thread = threading.Thread(target=self._icon.run, name="myknow-tray", daemon=True)
        self._thread.start()
        append_launcher_log(self.log_root, "tray_started")

    def handle_closing(self, window=None) -> bool:
        with self._lock:
            allow_close = self._allow_close
        if allow_close:
            return True
        try:
            self.window.hide()
            append_launcher_log(self.log_root, "window_hidden_to_tray")
        except Exception as error:
            append_launcher_log(self.log_root, f"tray_hide_failed error={error}")
        return False

    def _show_window(self, icon=None, item=None) -> None:
        try:
            self.window.show()
            self.window.restore()
            append_launcher_log(self.log_root, "window_restored_from_tray")
        except Exception as error:
            append_launcher_log(self.log_root, f"tray_show_failed error={error}")

    def _exit_application(self, icon=None, item=None) -> None:
        with self._lock:
            self._allow_close = True
        try:
            self.window.destroy()
        except Exception as error:
            append_launcher_log(self.log_root, f"tray_exit_window_failed error={error}")
        if self._icon is not None:
            self._icon.stop()

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.stop()
            self._icon = None
        append_launcher_log(self.log_root, "tray_stopped")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="myknow desktop launcher")
    parser.add_argument("--configure", action="store_true", help="选择数据与日志目录后退出")
    parser.add_argument("--service", choices=("api", "worker"), help=argparse.SUPPRESS)
    parser.add_argument("--data-dir", help="本次启动使用的数据目录")
    parser.add_argument("--log-dir", help="本次启动使用的日志目录")
    parser.add_argument("--port", type=int, help="本次启动使用的本机 API 端口，默认 8765")
    parser.add_argument("--dev-ui", action="store_true", help="使用 Vite 开发界面")
    parser.add_argument("--native", action="store_true", help="使用 pywebview 原生窗口")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开界面")
    return parser.parse_args()


def service_command(service: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--service", service]
    return [sys.executable, str(Path(__file__).resolve()), "--service", service]


def run_service(service: str) -> int:
    backend_root = ROOT / "backend"
    sys.path.insert(0, str(backend_root))
    os.chdir(backend_root)
    if service == "api":
        from a2wsgi import ASGIMiddleware
        from socketserver import ThreadingMixIn
        from wsgiref.simple_server import WSGIServer, make_server
        from main import app, init_db, start_integrity_repair_background

        class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
            """Keep slow uploads/AI calls from blocking the whole local UI."""

            daemon_threads = True

        init_db(repair=False)
        start_integrity_repair_background()
        server = make_server(
            "127.0.0.1",
            int(os.getenv("MUSE_VAULT_API_PORT", "8765")),
            ASGIMiddleware(app),
            server_class=ThreadingWSGIServer,
        )
        server.serve_forever()
        return 0

    from worker import init_db, process_one

    init_db(repair=False)
    while True:
        if not process_one():
            time.sleep(1)


def main() -> int:
    args = parse_args()
    if args.service:
        return run_service(args.service)
    if args.configure:
        return configure_interactively()

    data_root, log_root = configured_paths(args)
    api_port = args.port or int(os.getenv("MUSE_VAULT_API_PORT", "8765"))
    if not 1 <= api_port <= 65535:
        raise SystemExit("API 端口必须在 1 到 65535 之间")
    env = os.environ.copy()
    env["MUSE_VAULT_HOME"] = str(data_root)
    env["MUSE_VAULT_LOG_DIR"] = str(log_root)
    env["MUSE_VAULT_UI_DIST"] = str(ROOT / "desktop-ui" / "dist")
    env["MUSE_VAULT_EXTENSION_ROOT"] = str(ROOT / "extension")
    env["MUSE_VAULT_API_PORT"] = str(api_port)
    append_launcher_log(log_root, f"starting data_root={data_root} log_root={log_root}")

    process_pairs: list[tuple[subprocess.Popen, object]] = []
    tray: TrayController | None = None
    try:
        if port_in_use(api_port):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{api_port}/api/health", timeout=0.5) as response:
                    if response.status == 200:
                        raise RuntimeError(f"已有 myknow 正在运行（端口 {api_port}）。请先关闭旧版本，再启动这个版本。")
            except RuntimeError:
                raise
            except Exception:
                raise RuntimeError(f"端口 {api_port} 已被其他程序占用。请关闭占用程序后再启动 myknow。")
        api_pair = start_process(service_command("api"), ROOT, env, log_root / "api.log")
        process_pairs.append(api_pair)
        # Let the API finish its first database initialization before the
        # worker opens the same SQLite file. This avoids a cold-start lock
        # race, which is especially visible in the frozen EXE.
        wait_for_server(api_pair[0], api_port)
        process_pairs.append(start_process(service_command("worker"), ROOT, env, log_root / "worker.log"))
        url = f"http://127.0.0.1:{api_port}"
        if args.dev_ui:
            env["MUSE_VAULT_API_TARGET"] = url
            process_pairs.append(start_process(
                ["npm.cmd", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5174"],
                ROOT / "desktop-ui", env, log_root / "ui.log",
            ))
            url = "http://127.0.0.1:5174"

        processes = [item[0] for item in process_pairs]
        append_launcher_log(log_root, f"ready url={url}")
        use_native = not args.no_browser and (
            args.native or os.getenv("MUSE_VAULT_NATIVE_WINDOW") == "1" or getattr(sys, "frozen", False)
        )
        if use_native:
            import webview
            desktop_api = DesktopApi()
            window = webview.create_window(
                "myknow", url, js_api=desktop_api, min_size=(1080, 720), background_color="#111413"
            )
            desktop_api._window = window
            icon = application_icon_path()
            tray = TrayController(window, icon, log_root)
            window.events.closing += tray.handle_closing
            tray.start()
            try:
                webview.start(icon=str(icon) if icon.is_file() else None)
            finally:
                tray.stop()
        elif args.no_browser:
            while all(process.poll() is None for process in processes):
                time.sleep(1)
        else:
            webbrowser.open(url)
            input("myknow 正在运行，按 Enter 停止。")
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        append_launcher_log(log_root, f"startup_failed error={error}")
        show_startup_error(error)
        return 1
    finally:
        processes = [item[0] for item in process_pairs]
        stop_processes(processes)
        for _, handle in process_pairs:
            handle.close()
        append_launcher_log(log_root, "stopped")


if __name__ == "__main__":
    raise SystemExit(main())
