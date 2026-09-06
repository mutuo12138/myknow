from __future__ import annotations

import base64
import binascii
import asyncio
import colorsys
import hashlib
import io
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import subprocess
import threading
import time
import uuid
import zipfile
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ai_adapter import (
    compact_tags, interpret_material_assistant_query, public_ai_status,
    redact_sensitive_text, save_ai_config,
)

if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

ROOT = Path(os.getenv("MUSE_VAULT_HOME", Path(__file__).resolve().parents[1] / "data"))
DB_PATH = ROOT / "muse-vault.db"
ASSET_ROOT = ROOT / "assets"
STAGING_ROOT = ROOT / ".staging"
RECOVERY_ROOT = ROOT / "recovery"
LOG_ROOT = Path(os.getenv("MUSE_VAULT_LOG_DIR", ROOT / "logs"))
UI_DIST = Path(os.getenv("MUSE_VAULT_UI_DIST", Path(__file__).resolve().parents[1] / "desktop-ui" / "dist"))
EXTENSION_ROOT = Path(os.getenv("MUSE_VAULT_EXTENSION_ROOT", Path(__file__).resolve().parents[1] / "extension"))
API_PORT = int(os.getenv("MUSE_VAULT_API_PORT", "8765"))
ROOT.mkdir(parents=True, exist_ok=True)
ASSET_ROOT.mkdir(parents=True, exist_ok=True)
STAGING_ROOT.mkdir(parents=True, exist_ok=True)
RECOVERY_ROOT.mkdir(parents=True, exist_ok=True)
LOG_ROOT.mkdir(parents=True, exist_ok=True)

MaterialType = Literal["page", "blog", "document", "presentation", "image", "video", "link"]
AIMode = Literal["off", "manual", "auto"]
ExportPolicy = Literal["collect_only", "on_demand", "auto"]

DEFAULT_PROCESSING_SETTINGS = {
    "ai_mode": "off",
    "auto_idle_minutes": 10,
    "auto_since": 0,
    "daily_request_limit": 100,
    "batch_size": 100,
    "export_policy": "on_demand",
    "export_formats": ["pdf", "docx"],
}

# Browser-captured videos are downloaded once into the local asset store. Keep
# the limit explicit so a protected page cannot turn a deliberate capture into
# an unbounded memory or disk operation.
MAX_LOCAL_VIDEO_BYTES = 120 * 1024 * 1024
MAX_CAPTURE_DATA_URL_CHARS = 180_000_000


@contextmanager
def db():
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db(repair: bool = True) -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS folders (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              parent_id TEXT REFERENCES folders(id) ON DELETE SET NULL,
              created_at INTEGER NOT NULL,
              sort_order INTEGER NOT NULL DEFAULT 0,
              UNIQUE(parent_id, name)
            );
            CREATE TABLE IF NOT EXISTS materials (
              id TEXT PRIMARY KEY,
              fingerprint TEXT NOT NULL UNIQUE,
              source_url TEXT NOT NULL,
              canonical_url TEXT,
              title TEXT NOT NULL,
              material_type TEXT NOT NULL,
              source_name TEXT,
              local_path TEXT,
              captured_at INTEGER NOT NULL,
              content_created_at INTEGER,
              status TEXT NOT NULL DEFAULT 'queued',
              ai_summary TEXT,
              category TEXT NOT NULL DEFAULT '未分类',
              subcategory TEXT,
              text_content TEXT,
              tags_json TEXT NOT NULL DEFAULT '[]',
              entities_json TEXT NOT NULL DEFAULT '[]',
              thumbnail_url TEXT,
              media_url TEXT,
              user_permitted_media INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS visual_features (
              material_id TEXT PRIMARY KEY REFERENCES materials(id) ON DELETE CASCADE,
              palette_json TEXT NOT NULL DEFAULT '[]',
              histogram_json TEXT NOT NULL DEFAULT '[]',
              mean_brightness REAL,
              detail_score REAL,
              visual_description TEXT
            );
            CREATE TABLE IF NOT EXISTS material_derivatives (
              material_id TEXT PRIMARY KEY REFERENCES materials(id) ON DELETE CASCADE,
              thumbnail_path TEXT,
              thumbnail_width INTEGER,
              thumbnail_height INTEGER,
              state TEXT NOT NULL DEFAULT 'not_requested',
              error TEXT,
              updated_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS transcripts (
              material_id TEXT PRIMARY KEY REFERENCES materials(id) ON DELETE CASCADE,
              transcript TEXT,
              segments_json TEXT NOT NULL DEFAULT '[]',
              language TEXT,
              state TEXT NOT NULL DEFAULT 'not_requested'
            );
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY,
              material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
              stage TEXT NOT NULL,
              state TEXT NOT NULL DEFAULT 'queued',
              attempts INTEGER NOT NULL DEFAULT 0,
              next_run_at INTEGER NOT NULL,
              last_error TEXT,
              UNIQUE(material_id, stage)
            );
            CREATE TABLE IF NOT EXISTS app_settings (
              key TEXT PRIMARY KEY,
              value_json TEXT NOT NULL,
              updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ai_batch_runs (
              id TEXT PRIMARY KEY,
              trigger_type TEXT NOT NULL,
              scope TEXT NOT NULL,
              state TEXT NOT NULL DEFAULT 'queued',
              total_items INTEGER NOT NULL DEFAULT 0,
              processed_items INTEGER NOT NULL DEFAULT 0,
              failed_items INTEGER NOT NULL DEFAULT 0,
              estimated_requests INTEGER NOT NULL DEFAULT 0,
              created_at INTEGER NOT NULL,
              started_at INTEGER,
              completed_at INTEGER,
              stopped_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS ai_batch_items (
              batch_id TEXT NOT NULL REFERENCES ai_batch_runs(id) ON DELETE CASCADE,
              material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
              state TEXT NOT NULL DEFAULT 'queued',
              error TEXT,
              PRIMARY KEY(batch_id, material_id)
            );
            CREATE TABLE IF NOT EXISTS ai_usage (
              id TEXT PRIMARY KEY,
              batch_id TEXT REFERENCES ai_batch_runs(id) ON DELETE SET NULL,
              material_id TEXT REFERENCES materials(id) ON DELETE SET NULL,
              model TEXT,
              request_count INTEGER NOT NULL DEFAULT 1,
              input_tokens INTEGER,
              output_tokens INTEGER,
              total_tokens INTEGER,
              error TEXT,
              created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS offline_exports (
              material_id TEXT PRIMARY KEY REFERENCES materials(id) ON DELETE CASCADE,
              html_path TEXT,
              pdf_path TEXT,
              docx_path TEXT,
              state TEXT NOT NULL DEFAULT 'not_requested',
              error TEXT,
              updated_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS capture_operations (
              id TEXT PRIMARY KEY,
              material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
              state TEXT NOT NULL DEFAULT 'pending',
              local_staged_path TEXT,
              local_final_path TEXT,
              snapshot_staged_path TEXT,
              snapshot_final_path TEXT,
              error TEXT,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS assistant_action_plans (
              id TEXT PRIMARY KEY,
              action TEXT NOT NULL,
              material_ids_json TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              preview_json TEXT NOT NULL,
              state TEXT NOT NULL DEFAULT 'pending',
              confirmation_hash TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              expires_at INTEGER NOT NULL,
              executed_at INTEGER,
              undone_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS assistant_action_logs (
              id TEXT PRIMARY KEY,
              plan_id TEXT NOT NULL REFERENCES assistant_action_plans(id) ON DELETE CASCADE,
              material_id TEXT NOT NULL,
              action TEXT NOT NULL,
              before_json TEXT NOT NULL,
              after_json TEXT NOT NULL,
              created_at INTEGER NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS materials_fts USING fts5(
              material_id UNINDEXED, title, text_content, ai_summary, visual_description, tags,
              tokenize='trigram'
            );
            CREATE INDEX IF NOT EXISTS idx_materials_type ON materials(material_type);
            CREATE INDEX IF NOT EXISTS idx_materials_category ON materials(category, subcategory);
            CREATE INDEX IF NOT EXISTS idx_materials_captured ON materials(captured_at DESC);
            CREATE INDEX IF NOT EXISTS idx_jobs_ready ON jobs(state, next_run_at);
            CREATE INDEX IF NOT EXISTS idx_folders_parent ON folders(parent_id, sort_order, name);
            CREATE INDEX IF NOT EXISTS idx_capture_operations_state ON capture_operations(state, updated_at);
            CREATE INDEX IF NOT EXISTS idx_ai_batch_runs_state ON ai_batch_runs(state, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_ai_batch_items_state ON ai_batch_items(batch_id, state);
            CREATE INDEX IF NOT EXISTS idx_ai_usage_created ON ai_usage(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_derivatives_state ON material_derivatives(state, updated_at);
            CREATE INDEX IF NOT EXISTS idx_assistant_plans_state ON assistant_action_plans(state, expires_at);
            CREATE INDEX IF NOT EXISTS idx_assistant_logs_plan ON assistant_action_logs(plan_id, created_at);
            """
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_folders_sibling_name ON folders(COALESCE(parent_id, ''), name)"
        )
        material_columns = {row[1] for row in conn.execute("PRAGMA table_info(materials)")}
        for column, definition in (
            ("folder_id", "TEXT"),
            ("snapshot_path", "TEXT"),
            ("content_hash", "TEXT"),
            ("storage_mode", "TEXT NOT NULL DEFAULT 'managed'"),
            ("status_reason", "TEXT"),
            ("deleted_at", "INTEGER"),
            ("tags_user_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("tags_ai_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("tags_rejected_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("media_url", "TEXT"),
        ):
            if column in material_columns:
                continue
            try:
                conn.execute(f"ALTER TABLE materials ADD COLUMN {column} {definition}")
            except sqlite3.OperationalError as error:
                if "duplicate column name" not in str(error).lower():
                    raise
        conn.execute("UPDATE materials SET tags_ai_json=tags_json WHERE tags_ai_json='[]' AND tags_user_json='[]'")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_materials_folder ON materials(folder_id, captured_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_materials_content_hash ON materials(content_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_materials_canonical ON materials(material_type, canonical_url)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_materials_deleted ON materials(deleted_at, captured_at DESC)")
        job_columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        if "batch_id" not in job_columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN batch_id TEXT")
        export_columns = {row[1] for row in conn.execute("PRAGMA table_info(offline_exports)")}
        if "requested_formats_json" not in export_columns:
            conn.execute("ALTER TABLE offline_exports ADD COLUMN requested_formats_json TEXT NOT NULL DEFAULT '[]'")
        visual_columns = {row[1] for row in conn.execute("PRAGMA table_info(visual_features)")}
        if "histogram_json" not in visual_columns:
            conn.execute("ALTER TABLE visual_features ADD COLUMN histogram_json TEXT NOT NULL DEFAULT '[]'")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_batch ON jobs(batch_id, state)")
        conn.execute(
            "INSERT OR IGNORE INTO app_settings (key, value_json, updated_at) VALUES ('processing', ?, ?)",
            (json.dumps(DEFAULT_PROCESSING_SETTINGS, ensure_ascii=False), now()),
        )
        conn.execute("INSERT OR IGNORE INTO folders (id, name, parent_id, created_at, sort_order) VALUES ('inbox', '收件箱', NULL, ?, 0)", (now(),))
        conn.execute("UPDATE materials SET folder_id='inbox' WHERE folder_id IS NULL OR folder_id='' ")
        conn.execute("INSERT OR IGNORE INTO visual_features (material_id) SELECT id FROM materials")
        conn.execute("INSERT OR IGNORE INTO material_derivatives (material_id) SELECT id FROM materials")
        conn.execute("INSERT OR IGNORE INTO transcripts (material_id, state) SELECT id, 'not_requested' FROM materials")
        conn.execute(
            """INSERT OR IGNORE INTO offline_exports (material_id, html_path, state, updated_at)
               SELECT id, snapshot_path, 'not_requested', ? FROM materials""",
            (now(),),
        )
        conn.execute(
            """INSERT OR IGNORE INTO jobs (id, material_id, stage, state, attempts, next_run_at)
               SELECT lower(hex(randomblob(16))), m.id, 'thumbnail', 'queued', 0, ?
               FROM materials m JOIN material_derivatives d ON d.material_id=m.id
               WHERE m.deleted_at IS NULL AND m.local_path IS NOT NULL
                 AND m.material_type IN ('image', 'page', 'blog')
                 AND (d.thumbnail_path IS NULL OR d.state <> 'ready')""",
            (now(),),
        )
        fts_sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='materials_fts'").fetchone()[0].lower()
        if "tokenize='trigram'" not in fts_sql.replace(" ", "") or "visual_description" not in fts_sql:
            conn.execute("ALTER TABLE materials_fts RENAME TO materials_fts_legacy")
            conn.execute("CREATE VIRTUAL TABLE materials_fts USING fts5(material_id UNINDEXED, title, text_content, ai_summary, visual_description, tags, tokenize='trigram')")
            for row in conn.execute("""SELECT m.id, m.title, m.text_content, m.ai_summary, m.tags_json,
                                              v.visual_description
                                       FROM materials m LEFT JOIN visual_features v ON v.material_id=m.id
                                       WHERE m.deleted_at IS NULL"""):
                conn.execute(
                    "INSERT INTO materials_fts(material_id, title, text_content, ai_summary, visual_description, tags) VALUES (?, ?, ?, ?, ?, ?)",
                    (row["id"], row["title"], row["text_content"] or "", row["ai_summary"] or "", row["visual_description"] or "", " ".join(json.loads(row["tags_json"] or "[]"))),
                )
            conn.execute("DROP TABLE materials_fts_legacy")
    if repair:
        scan_integrity(repair=True)


_integrity_repair_lock = threading.Lock()
_integrity_repair_started = False


def start_integrity_repair_background(delay_seconds: float = 3.0) -> bool:
    """Run the expensive startup consistency scan after the API is available."""
    global _integrity_repair_started
    with _integrity_repair_lock:
        if _integrity_repair_started:
            return False
        _integrity_repair_started = True

    def repair() -> None:
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        try:
            scan_integrity(repair=True)
        except Exception:
            # A failed maintenance scan must not take down the local API.
            # The normal integrity endpoint remains available for a later retry.
            return

    threading.Thread(target=repair, name="muse-integrity-repair", daemon=True).start()
    return True


class CaptureRequest(BaseModel):
    source_url: str = Field(min_length=3, max_length=4000)
    title: str = Field(default="未命名素材", max_length=500)
    material_type: MaterialType
    source_name: str | None = Field(default=None, max_length=200)
    text_content: str | None = Field(default=None, max_length=250_000)
    selection: str | None = Field(default=None, max_length=30_000)
    media_url: str | None = Field(default=None, max_length=4000)
    thumbnail_url: str | None = Field(default=None, max_length=4000)
    data_url: str | None = Field(default=None, max_length=MAX_CAPTURE_DATA_URL_CHARS)
    html_content: str | None = Field(default=None, max_length=4_000_000)
    folder_id: str = Field(default="inbox", max_length=100)
    # Extension-only signal: the user explicitly selected this media in the
    # browser. It is not persisted and is only used by the extension fallback.
    browser_session_capture: bool = False
    user_permitted_media: bool = False


class LinkImportRequest(BaseModel):
    source_dir: str = Field(min_length=1, max_length=4000)
    folder_id: str = Field(default="inbox", max_length=100)
    link_mode: Literal["auto", "hardlink", "symlink"] = "auto"


class MaterialPatch(BaseModel):
    category: str | None = Field(default=None, max_length=100)
    subcategory: str | None = Field(default=None, max_length=100)
    tags: list[str] | None = None
    folder_id: str | None = Field(default=None, max_length=100)


class FolderRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    parent_id: str | None = Field(default=None, max_length=100)


class AIConfigRequest(BaseModel):
    base_url: str = Field(min_length=8, max_length=1000)
    model: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=1000)


class ProcessingSettingsRequest(BaseModel):
    ai_mode: AIMode
    # 0 means immediate automatic intake; positive values keep the quiet-period batch mode.
    auto_idle_minutes: int = Field(default=10, ge=0, le=240)
    daily_request_limit: int = Field(default=100, ge=1, le=10_000)
    batch_size: int = Field(default=100, ge=1, le=10_000)
    export_policy: ExportPolicy = "on_demand"
    export_formats: list[Literal["pdf", "docx"]] = Field(default_factory=lambda: ["pdf", "docx"])
    include_existing_on_auto: bool = False


class AIBatchRequest(BaseModel):
    scope: Literal["all_unprocessed", "folder", "recent"] = "all_unprocessed"
    folder_id: str | None = Field(default=None, max_length=100)
    recent_hours: int = Field(default=24, ge=1, le=720)
    batch_size: int | None = Field(default=None, ge=1, le=10_000)
    force: bool = False


AssistantAction = Literal["add_tags", "remove_tags", "move_folder"]


class AssistantQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=60, ge=1, le=200)
    use_ai: bool = True


class AssistantPlanRequest(BaseModel):
    action: AssistantAction
    material_ids: list[str] = Field(min_length=1, max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=5)
    folder_id: str | None = Field(default=None, max_length=100)


class AssistantConfirmRequest(BaseModel):
    confirmation_token: str = Field(min_length=20, max_length=200)


def now() -> int:
    return int(time.time())


def get_processing_settings(conn: sqlite3.Connection | None = None) -> dict:
    if conn is None:
        with db() as connection:
            return get_processing_settings(connection)
    row = conn.execute("SELECT value_json FROM app_settings WHERE key='processing'").fetchone()
    try:
        stored = json.loads(row["value_json"]) if row else {}
    except (TypeError, json.JSONDecodeError):
        stored = {}
    settings = {**DEFAULT_PROCESSING_SETTINGS, **stored}
    try:
        settings["auto_idle_minutes"] = max(0, min(int(settings.get("auto_idle_minutes", 10)), 240))
    except (TypeError, ValueError):
        settings["auto_idle_minutes"] = DEFAULT_PROCESSING_SETTINGS["auto_idle_minutes"]
    try:
        settings["batch_size"] = max(1, min(int(settings.get("batch_size", 100)), 10_000))
    except (TypeError, ValueError):
        settings["batch_size"] = DEFAULT_PROCESSING_SETTINGS["batch_size"]
    settings["export_formats"] = [value for value in settings.get("export_formats", []) if value in {"pdf", "docx"}]
    if not settings["export_formats"]:
        settings["export_formats"] = ["pdf", "docx"]
    return settings


def set_processing_settings(conn: sqlite3.Connection, settings: dict) -> dict:
    clean = {key: settings[key] for key in DEFAULT_PROCESSING_SETTINGS}
    conn.execute(
        """INSERT INTO app_settings (key, value_json, updated_at) VALUES ('processing', ?, ?)
           ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at""",
        (json.dumps(clean, ensure_ascii=False), now()),
    )
    return clean


TRACKING_QUERY_KEYS = {
    "fbclid", "gclid", "xsec_source", "xsec_token", "spm", "share_source", "share_medium",
}


def canonicalize_url(url: str) -> str:
    raw = url.strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw
    scheme = parts.scheme.lower()
    hostname = (parts.hostname or "").lower()
    if not scheme or not hostname:
        return raw
    try:
        port = parts.port
    except ValueError:
        port = None
    host = hostname
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lower_key = key.lower()
        if lower_key.startswith("utm_") or lower_key in TRACKING_QUERY_KEYS:
            continue
        query.append((key, value))
    query.sort()
    return urlunsplit((scheme, host, parts.path or "/", urlencode(query, doseq=True), ""))


def normalize_url(url: str) -> str:
    return canonicalize_url(url)


def stable_media_identity(url: str | None) -> str:
    """Return a durable identity for signed browser-media URLs."""
    canonical = canonicalize_url(url or "")
    try:
        parts = urlsplit(canonical)
    except ValueError:
        return canonical
    if parts.hostname == "chatgpt.com" and parts.path == "/backend-api/estuary/content":
        file_id = dict(parse_qsl(parts.query, keep_blank_values=True)).get("id")
        if file_id:
            return f"{parts.scheme}://{parts.netloc}{parts.path}?id={quote(file_id, safe='')}"
    return canonical


def decode_data_url(data_url: str | None) -> tuple[str, bytes] | None:
    if not data_url:
        return None
    match = re.match(r"data:([^;]+);base64,(.+)", data_url, re.S)
    if not match:
        raise ValueError("素材 data URL 格式无效")
    mime, encoded = match.groups()
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("素材 data URL 不是有效 Base64") from error
    return mime.lower(), content


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(payload: CaptureRequest, content_hash: str | None = None) -> str:
    if content_hash and payload.material_type in {"image", "document", "presentation", "video"}:
        basis = f"content|{payload.material_type}|{content_hash}"
    elif payload.material_type in {"page", "blog", "link"}:
        basis = f"url|{payload.material_type}|{canonicalize_url(payload.source_url)}"
    else:
        basis = f"url|{payload.material_type}|{canonicalize_url(payload.media_url or payload.source_url)}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def category_for(text: str, material_type: str) -> tuple[str, str | None, list[str]]:
    lower = text.lower()
    rules = [
        ("科学", ["science", "research", "physics", "biology", "chemistry", "论文", "实验"]),
        ("技术", ["code", "python", "ai", "software", "programming", "开发", "算法"]),
        ("设计", ["design", "ui", "ux", "视觉", "排版", "品牌"]),
        ("生活", ["travel", "food", "vlog", "生活", "旅行", "美食"]),
    ]
    if material_type in {"document", "presentation"}:
        parent = "文档"
    elif material_type == "image":
        parent = "图片"
    elif material_type == "video":
        parent = "视频"
    else:
        parent = "网页"
    for category, words in rules:
        if any(word in lower for word in words):
            return parent, category, [category]
    return parent, None, []


def safe_folder_name(folder_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", folder_id)[:100] or "inbox"


FILE_EXTENSIONS = {
    "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif",
    "image/avif": "avif", "application/pdf": "pdf", "video/mp4": "mp4",
    "video/webm": "webm", "video/ogg": "ogv", "video/quicktime": "mov",
    "video/x-msvideo": "avi", "video/x-matroska": "mkv",
}

LOCAL_IMAGE_MIMES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif", ".avif": "image/avif",
}
MAX_LOCAL_IMPORT_FILES = 50
MAX_LOCAL_IMPORT_BYTES = 100 * 1024 * 1024


def extension_for_mime(mime: str) -> str:
    return FILE_EXTENSIONS.get(mime.lower(), "bin")


def local_image_mime(filename: str, content_type: str | None) -> str | None:
    suffix = Path(filename).suffix.lower()
    expected = LOCAL_IMAGE_MIMES.get(suffix)
    if not expected:
        return None
    if content_type and content_type.startswith("image/"):
        return expected
    return expected


async def stage_uploaded_file(upload: UploadFile, destination: Path) -> tuple[int, str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    writing = destination.with_suffix(destination.suffix + ".writing")
    digest = hashlib.sha256()
    size = 0
    try:
        with writing.open("wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_LOCAL_IMPORT_BYTES:
                    raise ValueError(f"单张图片不能超过 {MAX_LOCAL_IMPORT_BYTES // (1024 * 1024)}MB")
                digest.update(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if size == 0:
            raise ValueError("图片文件为空")
        os.replace(writing, destination)
        return size, digest.hexdigest()
    except Exception:
        writing.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


def operation_plan(operation_id: str, material_id: str, material_type: str, folder_id: str,
                   local_mime: str | None, html_content: str | None) -> dict:
    stage_dir = STAGING_ROOT / operation_id
    local_final = None
    if local_mime:
        local_final = ASSET_ROOT / material_type / safe_folder_name(folder_id) / f"{material_id}.{extension_for_mime(local_mime)}"
    snapshot_final = ASSET_ROOT / "web" / safe_folder_name(folder_id) / f"{material_id}.html" if html_content else None
    return {
        "id": operation_id,
        "material_id": material_id,
        "local_staged": stage_dir / "local.part" if local_final else None,
        "local_final": local_final,
        "snapshot_staged": stage_dir / "snapshot.part" if snapshot_final else None,
        "snapshot_final": snapshot_final,
    }


def create_capture_operation(conn: sqlite3.Connection, plan: dict) -> None:
    conn.execute(
        """INSERT INTO capture_operations
           (id, material_id, state, local_staged_path, local_final_path,
            snapshot_staged_path, snapshot_final_path, created_at, updated_at)
           VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?)""",
        (plan["id"], plan["material_id"],
         str(plan["local_staged"]) if plan["local_staged"] else None,
         str(plan["local_final"]) if plan["local_final"] else None,
         str(plan["snapshot_staged"]) if plan["snapshot_staged"] else None,
         str(plan["snapshot_final"]) if plan["snapshot_final"] else None,
         now(), now()),
    )


def write_staged_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writing = path.with_suffix(path.suffix + ".writing")
    with writing.open("wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(writing, path)


def write_capture_files(plan: dict, local_content: bytes | None, html_content: str | None) -> None:
    if local_content is not None:
        write_staged_file(plan["local_staged"], local_content)
    if html_content is not None:
        write_staged_file(plan["snapshot_staged"], html_content.encode("utf-8"))
    for staged_key, final_key in (("local_staged", "local_final"), ("snapshot_staged", "snapshot_final")):
        staged, final = plan[staged_key], plan[final_key]
        if staged and final:
            final.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, final)
    stage_paths = [path for path in (plan["local_staged"], plan["snapshot_staged"]) if path]
    if stage_paths:
        stage_dir = stage_paths[0].parent
        try:
            stage_dir.rmdir()
        except OSError:
            pass


def cleanup_staging(operation_id: str) -> None:
    folder = STAGING_ROOT / operation_id
    if not folder.exists():
        return
    for path in sorted(folder.rglob("*"), reverse=True):
        if path.is_file() or path.is_symlink():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            path.rmdir()
    folder.rmdir() if folder.exists() else None


def path_is_asset(path_value: str | None) -> bool:
    if not path_value:
        return False
    try:
        # Deliberately do not resolve symlinks here. A linked import stores a
        # link inside ASSET_ROOT; serving or deleting that link must never
        # follow it and touch the user's original file.
        path = Path(path_value).absolute()
        return path.is_relative_to(ASSET_ROOT.absolute())
    except OSError:
        return False


def quarantine_unreferenced_operation_files(operation_id: str) -> list[str]:
    moved: list[str] = []
    with db() as conn:
        operation = conn.execute("SELECT local_final_path, snapshot_final_path FROM capture_operations WHERE id=?", (operation_id,)).fetchone()
        referenced = referenced_asset_paths(conn)
    if not operation:
        return moved
    destination = RECOVERY_ROOT / operation_id
    for value in operation:
        if not value:
            continue
        path = Path(value)
        try:
            resolved = path.absolute()
            if not path_is_asset(str(resolved)) or not resolved.is_file() or resolved in referenced:
                continue
            destination.mkdir(parents=True, exist_ok=True)
            target = destination / resolved.name
            os.replace(resolved, target)
            moved.append(str(target))
        except OSError:
            continue
    return moved
def queue_job(conn: sqlite3.Connection, material_id: str, stage: str, batch_id: str | None = None) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO jobs (id, material_id, stage, next_run_at, batch_id) VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), material_id, stage, now(), batch_id),
    )


def requeue_job(conn: sqlite3.Connection, material_id: str, stage: str, batch_id: str | None = None) -> None:
    conn.execute(
        """INSERT INTO jobs (id, material_id, stage, state, attempts, next_run_at, batch_id)
           VALUES (?, ?, ?, 'queued', 0, ?, ?)
           ON CONFLICT(material_id, stage) DO UPDATE SET
             state='queued', attempts=0, next_run_at=excluded.next_run_at,
             last_error=NULL, batch_id=excluded.batch_id""",
         (str(uuid.uuid4()), material_id, stage, now(), batch_id),
    )


def required_stages(material: sqlite3.Row | dict, settings: dict | None = None) -> list[str]:
    material = dict(material)
    stages: list[str] = []
    if material.get("material_type") in {"image", "video"} and (material.get("media_url") or material.get("thumbnail_url")) and not material.get("local_path"):
        stages.append("download")
    stages.append("classify")
    if material.get("local_path") and material.get("material_type") in {"image", "page", "blog"}:
        stages.append("thumbnail")
    if material.get("local_path") and material.get("material_type") in {"image", "page", "blog"}:
        stages.append("visual")
    settings = settings or get_processing_settings()
    if material.get("snapshot_path") and settings["export_policy"] == "auto":
        stages.append("export")
    stages.append("index")
    if material.get("user_permitted_media") and material.get("material_type") == "video":
        stages.append("transcribe")
    return stages


def queue_material_jobs(conn: sqlite3.Connection, material_id: str, *, reset: bool = False) -> None:
    material = conn.execute("SELECT * FROM materials WHERE id=?", (material_id,)).fetchone()
    if not material:
        return
    settings = get_processing_settings(conn)
    stages = required_stages(material, settings)
    if "export" in stages:
        conn.execute(
            "UPDATE offline_exports SET requested_formats_json=?, state='queued', error=NULL, updated_at=? WHERE material_id=?",
            (json.dumps(settings["export_formats"]), now(), material_id),
        )
    for stage in stages:
        requeue_job(conn, material_id, stage) if reset else queue_job(conn, material_id, stage)


def local_day_start() -> int:
    current = time.localtime()
    return int(time.mktime((current.tm_year, current.tm_mon, current.tm_mday, 0, 0, 0, 0, 0, -1)))


def ai_usage_today(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        """SELECT COALESCE(SUM(request_count), 0) AS requests,
                  COALESCE(SUM(input_tokens), 0) AS input_tokens,
                  COALESCE(SUM(output_tokens), 0) AS output_tokens,
                  COALESCE(SUM(total_tokens), 0) AS total_tokens
           FROM ai_usage WHERE created_at>=?""",
        (local_day_start(),),
    ).fetchone()
    return dict(row)


def ai_alert_message(error: str | None) -> str:
    """Turn a provider error into an actionable, non-secret user message."""
    raw = (error or "").lower()
    if any(marker in raw for marker in ("insufficient_quota", "quota exhausted", "quota", "余额", "额度")):
        return "AI 额度不足，批次已暂停。请更换到仍有额度的模型并保存配置，然后点击“重试失败项”。"
    if any(marker in raw for marker in ("unsupported model", "invalid model", "model_not_found", "model does not exist")):
        return "当前模型名称不可用，批次已暂停。请在 AI 设置中选择可用模型并保存，然后点击“重试失败项”。"
    if " 401" in raw or " 403" in raw or "unauthorized" in raw or "forbidden" in raw:
        return "AI 接口鉴权或权限失败，批次已暂停。请检查 API Key、模型权限或更换模型后重试。"
    if " 429" in raw or "rate limit" in raw:
        return "AI 接口触发频率限制，批次已暂停。请稍后或更换模型后点击“重试失败项”。"
    return "AI 请求失败，批次已暂停。请打开运行日志查看原因，修复配置后点击“重试失败项”。"


def eligible_ai_materials(
    conn: sqlite3.Connection,
    *,
    scope: str = "all_unprocessed",
    folder_id: str | None = None,
    recent_hours: int = 24,
    force: bool = False,
    only_unqueued: bool = False,
    captured_after: int | None = None,
    captured_before: int | None = None,
) -> list[str]:
    clauses = ["m.deleted_at IS NULL"]
    values: list[object] = []
    if not force:
        clauses.append("(done.id IS NULL OR done.state<>'done')")
    if only_unqueued:
        # Automatic intake must not resurrect an old failed/paused AI item and
        # let that historical failure stop newly captured material.
        clauses.append("done.id IS NULL")
    clauses.append("active.id IS NULL")
    if scope == "folder":
        if not folder_id:
            raise ValueError("请选择要整理的文件夹")
        clauses.append("m.folder_id=?")
        values.append(folder_id)
    elif scope == "recent":
        clauses.append("m.captured_at>=?")
        values.append(now() - recent_hours * 3600)
    if captured_after is not None:
        clauses.append("m.captured_at>=?")
        values.append(captured_after)
    if captured_before is not None:
        clauses.append("m.captured_at<=?")
        values.append(captured_before)
    rows = conn.execute(
        f"""SELECT m.id FROM materials m
            LEFT JOIN jobs done ON done.material_id=m.id AND done.stage='ai_enrich'
            LEFT JOIN jobs active ON active.material_id=m.id AND active.stage='ai_enrich'
              AND active.state IN ('queued','running')
            WHERE {' AND '.join(clauses)} ORDER BY m.captured_at""",
        values,
    ).fetchall()
    return [row["id"] for row in rows]


def create_ai_batch(
    conn: sqlite3.Connection,
    material_ids: list[str],
    *,
    trigger_type: Literal["manual", "auto", "single"],
    scope: str,
    batch_size: int | None = None,
) -> dict:
    if not public_ai_status()["configured"]:
        raise ValueError("请先配置 AI API")
    material_ids = list(dict.fromkeys(material_ids))
    if batch_size is not None:
        material_ids = material_ids[:max(1, int(batch_size))]
    if not material_ids:
        raise ValueError("没有符合条件的待整理素材")
    settings = get_processing_settings(conn)
    usage = ai_usage_today(conn)
    reserved = conn.execute(
        """SELECT COALESCE(SUM(total_items-processed_items), 0) FROM ai_batch_runs
           WHERE state IN ('queued','running','stopping')"""
    ).fetchone()[0]
    remaining = max(0, settings["daily_request_limit"] - usage["requests"] - reserved)
    estimated = len(material_ids)
    if estimated > remaining:
        raise ValueError(f"本批预计 {estimated} 次请求，超过今天剩余的 {remaining} 次限额")
    batch_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO ai_batch_runs
           (id, trigger_type, scope, state, total_items, estimated_requests, created_at)
           VALUES (?, ?, ?, 'queued', ?, ?, ?)""",
        (batch_id, trigger_type, scope, len(material_ids), estimated, now()),
    )
    for material_id in material_ids:
        conn.execute(
            "INSERT INTO ai_batch_items (batch_id, material_id, state) VALUES (?, ?, 'queued')",
            (batch_id, material_id),
        )
        requeue_job(conn, material_id, "ai_enrich", batch_id=batch_id)
        requeue_job(conn, material_id, "index")
        conn.execute("UPDATE materials SET status='analyzing', status_reason=NULL WHERE id=?", (material_id,))
    return {
        "id": batch_id,
        "state": "queued",
        "trigger_type": trigger_type,
        "scope": scope,
        "total_items": len(material_ids),
        "estimated_requests": estimated,
    }


def schedule_auto_batch() -> dict | None:
    if not public_ai_status()["configured"]:
        return None
    with db() as conn:
        settings = get_processing_settings(conn)
        if settings["ai_mode"] != "auto":
            return None
        active = conn.execute(
            "SELECT id FROM ai_batch_runs WHERE state IN ('queued','running','stopping') LIMIT 1"
        ).fetchone()
        if active:
            return None
        latest_capture = conn.execute("SELECT MAX(captured_at) FROM materials WHERE deleted_at IS NULL").fetchone()[0]
        cutoff = now() - settings["auto_idle_minutes"] * 60
        if not latest_capture or latest_capture > cutoff:
            return None
        material_ids = eligible_ai_materials(
            conn,
            only_unqueued=True,
            captured_after=settings.get("auto_since") or 0,
            captured_before=cutoff,
        )
        if not material_ids:
            return None
        try:
            return create_ai_batch(
                conn,
                material_ids,
                trigger_type="auto",
                scope="auto_idle",
                batch_size=settings.get("batch_size", 100),
            )
        except ValueError:
            return None


def refresh_ai_batch(conn: sqlite3.Connection, batch_id: str) -> dict | None:
    batch = conn.execute("SELECT * FROM ai_batch_runs WHERE id=?", (batch_id,)).fetchone()
    if not batch:
        return None
    counts = {
        row["state"]: row["count"]
        for row in conn.execute(
            "SELECT state, COUNT(*) AS count FROM ai_batch_items WHERE batch_id=? GROUP BY state", (batch_id,)
        )
    }
    processed = counts.get("done", 0) + counts.get("failed", 0)
    failed = counts.get("failed", 0)
    if processed >= batch["total_items"]:
        state = "partial" if failed else "completed"
        completed_at = now()
    elif counts.get("running", 0):
        state = "stopping" if batch["state"] == "stopping" else "running"
        completed_at = None
    elif counts.get("paused", 0):
        state, completed_at = "paused", None
    else:
        state, completed_at = "queued", None
    conn.execute(
        """UPDATE ai_batch_runs SET state=?, processed_items=?, failed_items=?,
           started_at=CASE WHEN ?='running' AND started_at IS NULL THEN ? ELSE started_at END,
           completed_at=COALESCE(?, completed_at) WHERE id=?""",
        (state, processed, failed, state, now(), completed_at, batch_id),
    )
    row = conn.execute("SELECT * FROM ai_batch_runs WHERE id=?", (batch_id,)).fetchone()
    return dict(row) if row else None


def start_ai_batch_item(conn: sqlite3.Connection, batch_id: str | None, material_id: str) -> None:
    if not batch_id:
        return
    conn.execute(
        "UPDATE ai_batch_items SET state='running', error=NULL WHERE batch_id=? AND material_id=?",
        (batch_id, material_id),
    )
    conn.execute(
        "UPDATE ai_batch_runs SET state='running', started_at=COALESCE(started_at, ?) WHERE id=? AND state<>'stopping'",
        (now(), batch_id),
    )


def finish_ai_batch_item(
    conn: sqlite3.Connection,
    batch_id: str | None,
    material_id: str,
    *,
    state: Literal["queued", "done", "failed"],
    error: str | None = None,
    usage: dict | None = None,
) -> None:
    if not batch_id:
        return
    safe_error = redact_sensitive_text(error)[:500] if error else None
    conn.execute(
        "UPDATE ai_batch_items SET state=?, error=? WHERE batch_id=? AND material_id=?",
        (state, safe_error, batch_id, material_id),
    )
    status = public_ai_status()
    usage = usage or {}
    conn.execute(
        """INSERT INTO ai_usage
           (id, batch_id, material_id, model, request_count, input_tokens, output_tokens, total_tokens, error, created_at)
           VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)""",
        (
            str(uuid.uuid4()), batch_id, material_id, status.get("model"),
            usage.get("prompt_tokens") or usage.get("input_tokens"),
            usage.get("completion_tokens") or usage.get("output_tokens"),
            usage.get("total_tokens"), safe_error, now(),
        ),
    )
    refresh_ai_batch(conn, batch_id)


def ai_batch_detail(conn: sqlite3.Connection, batch_id: str) -> dict | None:
    batch = conn.execute("SELECT * FROM ai_batch_runs WHERE id=?", (batch_id,)).fetchone()
    if not batch:
        return None
    result = dict(batch)
    result["items"] = [
        dict(row) for row in conn.execute(
            """SELECT i.material_id, i.state, i.error, m.title, m.material_type
               FROM ai_batch_items i JOIN materials m ON m.id=i.material_id
               WHERE i.batch_id=? ORDER BY m.captured_at""",
            (batch_id,),
        )
    ]
    return result


def find_existing_material(conn: sqlite3.Connection, payload: CaptureRequest, content_hash: str | None) -> sqlite3.Row | None:
    if content_hash and payload.material_type in {"image", "document", "presentation", "video"}:
        row = conn.execute(
            "SELECT * FROM materials WHERE material_type=? AND content_hash=? ORDER BY captured_at LIMIT 1",
            (payload.material_type, content_hash),
        ).fetchone()
        if row:
            return row
    # A previous protected browser image may have been saved only with its
    # temporary URL after the remote download failed. If the user drags that
    # exact image again and the extension now supplies local bytes, enrich the
    # existing record instead of creating a duplicate.
    if payload.material_type in {"image", "video"} and payload.media_url:
        row = conn.execute(
            """SELECT * FROM materials
               WHERE material_type=? AND (media_url=? OR thumbnail_url=?)
               ORDER BY captured_at LIMIT 1""",
            (payload.material_type, payload.media_url, payload.media_url),
        ).fetchone()
        if row:
            return row
        stable_media = stable_media_identity(payload.media_url)
        if stable_media:
            for candidate in conn.execute(
                "SELECT * FROM materials WHERE material_type=? AND (media_url IS NOT NULL OR thumbnail_url IS NOT NULL) ORDER BY captured_at LIMIT 200",
                (payload.material_type,),
            ).fetchall():
                if any(stable_media_identity(candidate[field]) == stable_media for field in ("media_url", "thumbnail_url") if candidate[field]):
                    return candidate
    canonical = canonicalize_url(payload.source_url)
    if payload.material_type in {"page", "blog", "link"}:
        row = conn.execute(
            "SELECT * FROM materials WHERE material_type=? AND canonical_url=? ORDER BY captured_at LIMIT 1",
            (payload.material_type, canonical),
        ).fetchone()
        if row:
            return row
    key = fingerprint(payload, content_hash)
    return conn.execute("SELECT * FROM materials WHERE fingerprint=?", (key,)).fetchone()


def mark_operation_failed(operation_id: str, material_id: str, error: Exception | str) -> None:
    message = redact_sensitive_text(error)[:500]
    quarantine_unreferenced_operation_files(operation_id)
    cleanup_staging(operation_id)
    with db() as conn:
        conn.execute("UPDATE capture_operations SET state='failed', error=?, updated_at=? WHERE id=?", (message, now(), operation_id))
        conn.execute("UPDATE materials SET status='failed', status_reason=? WHERE id=?", (message, material_id))


def commit_capture_operation(operation_id: str, material_id: str, content_hash: str | None) -> dict:
    with db() as conn:
        operation = conn.execute("SELECT * FROM capture_operations WHERE id=?", (operation_id,)).fetchone()
        if not operation:
            raise RuntimeError("采集操作记录不存在")
        local_final = operation["local_final_path"]
        snapshot_final = operation["snapshot_final_path"]
        conn.execute(
            """UPDATE materials SET local_path=COALESCE(?, local_path), snapshot_path=COALESCE(?, snapshot_path),
               content_hash=COALESCE(?, content_hash), status='queued', status_reason=NULL WHERE id=?""",
            (local_final, snapshot_final, content_hash, material_id),
        )
        if snapshot_final:
            settings = get_processing_settings(conn)
            auto_export = settings["export_policy"] == "auto" and bool(settings["export_formats"])
            conn.execute(
                """INSERT INTO offline_exports (material_id, html_path, state, requested_formats_json, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(material_id) DO UPDATE SET
                     html_path=excluded.html_path, state=excluded.state,
                     requested_formats_json=excluded.requested_formats_json,
                     error=NULL, updated_at=excluded.updated_at""",
                (material_id, snapshot_final, "queued" if auto_export else "not_requested",
                 json.dumps(settings["export_formats"] if auto_export else []), now()),
            )
        if local_final:
            conn.execute(
                "UPDATE jobs SET state='done', last_error=NULL WHERE material_id=? AND stage='download' AND state IN ('queued','running')",
                (material_id,),
            )
        conn.execute("UPDATE capture_operations SET state='committed', error=NULL, updated_at=? WHERE id=?", (now(), operation_id))
        queue_material_jobs(conn, material_id, reset=True)
        return {"local_path": local_final, "snapshot_path": snapshot_final}


def update_fts_row(conn: sqlite3.Connection, material_id: str) -> None:
    conn.execute("DELETE FROM materials_fts WHERE material_id=?", (material_id,))
    row = conn.execute(
        """SELECT m.title, m.text_content, m.ai_summary, m.tags_json, m.deleted_at,
                  v.visual_description
           FROM materials m LEFT JOIN visual_features v ON v.material_id=m.id WHERE m.id=?""",
        (material_id,),
    ).fetchone()
    if not row or row["deleted_at"] is not None:
        return
    conn.execute(
        "INSERT INTO materials_fts(material_id, title, text_content, ai_summary, visual_description, tags) VALUES (?, ?, ?, ?, ?, ?)",
        (material_id, row["title"], row["text_content"] or "", row["ai_summary"] or "", row["visual_description"] or "", " ".join(json.loads(row["tags_json"] or "[]"))),
    )


def referenced_asset_paths(conn: sqlite3.Connection) -> set[Path]:
    values: set[Path] = set()
    for row in conn.execute("SELECT local_path, snapshot_path FROM materials"):
        for value in row:
            if value:
                try:
                    values.add(Path(value).absolute())
                except OSError:
                    pass
    for row in conn.execute("SELECT html_path, pdf_path, docx_path FROM offline_exports"):
        for value in row:
            if value:
                try:
                    values.add(Path(value).absolute())
                except OSError:
                    pass
    for row in conn.execute("SELECT thumbnail_path FROM material_derivatives"):
        if row["thumbnail_path"]:
            try:
                values.add(Path(row["thumbnail_path"]).absolute())
            except OSError:
                pass
    return values


def recover_pending_capture_operations() -> int:
    recovered = 0
    with db() as conn:
        operations = conn.execute("SELECT * FROM capture_operations WHERE state='pending' ORDER BY created_at").fetchall()
    for operation in operations:
        operation_id = operation["id"]
        all_present = True
        for staged_key, final_key in (("local_staged_path", "local_final_path"), ("snapshot_staged_path", "snapshot_final_path")):
            staged = Path(operation[staged_key]) if operation[staged_key] else None
            final = Path(operation[final_key]) if operation[final_key] else None
            if not final:
                continue
            try:
                if not final.exists() and staged and staged.exists():
                    final.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(staged, final)
                if not final.is_file():
                    all_present = False
            except OSError as error:
                all_present = False
                mark_operation_failed(operation_id, operation["material_id"], error)
                break
        if all_present:
            try:
                material = material_detail_row(operation["material_id"])
                recovered_hash = material["content_hash"] if material else None
                if not recovered_hash and operation["local_final_path"] and Path(operation["local_final_path"]).is_file() and material and material["material_type"] in {"image", "document", "presentation", "video"}:
                    recovered_hash = sha256_file(Path(operation["local_final_path"]))
                commit_capture_operation(operation_id, operation["material_id"], recovered_hash)
                cleanup_staging(operation_id)
                recovered += 1
            except Exception as error:
                mark_operation_failed(operation_id, operation["material_id"], error)
        else:
            mark_operation_failed(operation_id, operation["material_id"], "采集文件缺失")
    return recovered


def material_detail_row(material_id: str) -> sqlite3.Row | None:
    with db() as conn:
        return conn.execute("SELECT * FROM materials WHERE id=?", (material_id,)).fetchone()


def scan_integrity(repair: bool = False) -> dict:
    if repair:
        recover_pending_capture_operations()
    report = {
        "missing_files": [], "orphan_files": [], "orphan_staging": [], "recovery_files": [], "dead_ready": [],
        "missing_auxiliary": [], "missing_derivatives": [], "missing_fts": [], "duplicate_fts": [], "stale_fts": [], "content_hash_backfilled": 0,
        "repaired": 0,
    }
    with db() as conn:
        rows = conn.execute("SELECT * FROM materials ORDER BY captured_at").fetchall()
        referenced = referenced_asset_paths(conn)
        report["duplicate_fts"] = [
            {"id": row["material_id"], "count": row["count"]}
            for row in conn.execute("SELECT material_id, COUNT(*) AS count FROM materials_fts GROUP BY material_id HAVING COUNT(*) <> 1")
        ]
        report["stale_fts"] = [
            row["material_id"] for row in conn.execute(
                """SELECT DISTINCT f.material_id FROM materials_fts f
                   LEFT JOIN materials m ON m.id=f.material_id
                   WHERE m.id IS NULL OR m.deleted_at IS NOT NULL"""
            )
        ]
        if repair:
            if report["stale_fts"]:
                placeholders = ",".join("?" for _ in report["stale_fts"])
                report["repaired"] += conn.execute(f"DELETE FROM materials_fts WHERE material_id IN ({placeholders})", report["stale_fts"]).rowcount
            for duplicate in report["duplicate_fts"]:
                update_fts_row(conn, duplicate["id"])
                report["repaired"] += 1
        for row in rows:
            for field in ("local_path", "snapshot_path"):
                value = row[field]
                if value and not Path(value).is_file():
                    report["missing_files"].append({"id": row["id"], "field": field, "path": value})
            for table in ("visual_features", "material_derivatives", "transcripts", "offline_exports"):
                if not conn.execute(f"SELECT 1 FROM {table} WHERE material_id=?", (row["id"],)).fetchone():
                    report["missing_auxiliary"].append({"id": row["id"], "table": table})
            derivative = conn.execute("SELECT * FROM material_derivatives WHERE material_id=?", (row["id"],)).fetchone()
            expects_thumbnail = bool(row["local_path"] and row["material_type"] in {"image", "page", "blog"})
            if expects_thumbnail and derivative and (
                derivative["state"] != "ready" or not derivative["thumbnail_path"] or not Path(derivative["thumbnail_path"]).is_file()
            ):
                report["missing_derivatives"].append({
                    "id": row["id"], "state": derivative["state"], "path": derivative["thumbnail_path"]
                })
            if row["deleted_at"] is None and not conn.execute("SELECT 1 FROM materials_fts WHERE material_id=?", (row["id"],)).fetchone():
                report["missing_fts"].append(row["id"])
            dead = conn.execute("SELECT stage, last_error FROM jobs WHERE material_id=? AND state='dead'", (row["id"],)).fetchall()
            if row["status"] == "ready" and dead:
                report["dead_ready"].append({"id": row["id"], "stages": [item["stage"] for item in dead]})
            if repair and row["local_path"] and Path(row["local_path"]).is_file() and not row["content_hash"] and row["material_type"] in {"image", "document", "presentation", "video"}:
                conn.execute("UPDATE materials SET content_hash=? WHERE id=?", (sha256_file(Path(row["local_path"])), row["id"]))
                report["content_hash_backfilled"] += 1
            if repair and row["canonical_url"] != canonicalize_url(row["source_url"]):
                conn.execute("UPDATE materials SET canonical_url=? WHERE id=?", (canonicalize_url(row["source_url"]), row["id"]))
                report["repaired"] += 1
            if repair and row["status"] == "ready" and dead:
                conn.execute("UPDATE materials SET status='partial', status_reason=? WHERE id=?", ("必需任务失败：" + ", ".join(item["stage"] for item in dead), row["id"]))
                report["repaired"] += 1
            if repair and row["status"] != "failed" and any(item["id"] == row["id"] and item["field"] == "local_path" for item in report["missing_files"]):
                conn.execute("UPDATE materials SET status='partial', status_reason='本地文件缺失' WHERE id=?", (row["id"],))
                report["repaired"] += 1
            if repair:
                report["repaired"] += conn.execute("INSERT OR IGNORE INTO visual_features (material_id) VALUES (?)", (row["id"],)).rowcount
                report["repaired"] += conn.execute("INSERT OR IGNORE INTO material_derivatives (material_id) VALUES (?)", (row["id"],)).rowcount
                report["repaired"] += conn.execute("INSERT OR IGNORE INTO transcripts (material_id, state) VALUES (?, 'not_requested')", (row["id"],)).rowcount
                report["repaired"] += conn.execute("INSERT OR IGNORE INTO offline_exports (material_id, html_path, state, updated_at) VALUES (?, ?, 'not_requested', ?)", (row["id"], row["snapshot_path"], now())).rowcount
                if row["deleted_at"] is None and not conn.execute("SELECT 1 FROM materials_fts WHERE material_id=?", (row["id"],)).fetchone():
                    update_fts_row(conn, row["id"])
                    report["repaired"] += 1
                derivative = conn.execute("SELECT * FROM material_derivatives WHERE material_id=?", (row["id"],)).fetchone()
                if expects_thumbnail and derivative and (
                    derivative["state"] != "ready" or not derivative["thumbnail_path"] or not Path(derivative["thumbnail_path"]).is_file()
                ):
                    conn.execute(
                        "UPDATE material_derivatives SET thumbnail_path=NULL, thumbnail_width=NULL, thumbnail_height=NULL, state='queued', error=NULL, updated_at=? WHERE material_id=?",
                        (now(), row["id"]),
                    )
                    requeue_job(conn, row["id"], "thumbnail")
                    report["repaired"] += 1
        for path in ASSET_ROOT.rglob("*"):
            if path.is_file() and path.absolute() not in referenced:
                report["orphan_files"].append(str(path))
        for path in STAGING_ROOT.rglob("*"):
            if path.is_file():
                report["orphan_staging"].append(str(path))
        for path in RECOVERY_ROOT.rglob("*"):
            if path.is_file():
                report["recovery_files"].append(str(path))
    return report


def parse_prompt_bundle(description: str | None) -> dict[str, str]:
    """Expose the prompt parts stored in the visual description as UI fields."""
    fields = {"prompt_positive": "", "prompt_negative": "", "verification_checklist": ""}
    for raw_line in str(description or "").splitlines():
        label, separator, value = raw_line.partition(":")
        if not separator:
            continue
        key = {
            "positive prompt": "prompt_positive",
            "negative prompt": "prompt_negative",
            "verification": "verification_checklist",
        }.get(label.strip().lower())
        if key:
            fields[key] = value.strip()
    return fields


def row_to_material(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["tags"] = json.loads(item.pop("tags_json") or "[]")
    item["tags_user"] = json.loads(item.pop("tags_user_json", "[]") or "[]")
    item["tags_ai"] = json.loads(item.pop("tags_ai_json", "[]") or "[]")
    item["tags_rejected"] = json.loads(item.pop("tags_rejected_json", "[]") or "[]")
    item["entities"] = json.loads(item.pop("entities_json") or "[]")
    palette = json.loads(item.pop("palette_json") or "[]")
    for color in palette:
        rgb = color.get("rgb") if isinstance(color, dict) else None
        if isinstance(rgb, (list, tuple)) and len(rgb) >= 3 and not color.get("hex"):
            color["hex"] = "#%02X%02X%02X" % tuple(max(0, min(255, int(value))) for value in rgb[:3])
    item["palette"] = palette
    histogram = json.loads(item.pop("histogram_json", "{}") or "{}")
    # Older databases stored a 16-bin grayscale list. Keep it readable as a
    # legacy field, but only the channel curves are rendered as an RGB photo
    # histogram by the current inspector.
    if isinstance(histogram, list):
        histogram = {"legacy_luma": histogram, "bins": len(histogram)}
    item["histogram"] = histogram if isinstance(histogram, dict) else {}
    item.update(parse_prompt_bundle(item.get("visual_description")))
    item["permitted_media"] = bool(item.pop("user_permitted_media"))
    # Older video records stored the playable URL in thumbnail_url because
    # media_url did not exist yet. Keep those records inspectable after the
    # migration while new captures use the dedicated field.
    if item.get("material_type") == "video" and not item.get("media_url"):
        item["media_url"] = item.get("thumbnail_url") or None
    item["asset_url"] = f"/api/materials/{item['id']}/asset" if item.get("local_path") else None
    item["thumbnail_asset_url"] = (
        f"/api/materials/{item['id']}/thumbnail"
        if item.get("thumbnail_path") and item.get("thumbnail_state") == "ready"
        else None
    )
    item["has_local_copy"] = bool(item.get("local_path"))
    item["is_linked"] = str(item.get("storage_mode") or "").startswith("linked_")
    item["is_deleted"] = item.get("deleted_at") is not None
    return item


def clean_user_tags(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values or []:
        clean = " ".join(str(value).split()).strip("，,。.!！？?、;；:：\"'“”")
        if clean and len(clean) <= 40 and clean not in result:
            result.append(clean)
    return result[:20]


ASSISTANT_COLOR_LABELS = {
    "blue": "蓝色系", "green": "绿色系", "warm": "暖色系", "pink": "粉紫色系", "neutral": "黑白灰",
}
ASSISTANT_COLOR_NAME_LABELS = {
    "red": "红色", "orange": "橙色", "yellow": "黄色", "green": "绿色", "cyan": "青色", "blue": "蓝色",
    "purple": "紫色", "pink": "粉色", "gray": "灰色", "black": "黑色", "white": "白色",
    "warm": "暖色系", "cool": "冷色系", "neutral": "中性色",
}
ASSISTANT_BRIGHTNESS_LABELS = {"dark": "偏暗", "medium": "中等亮度", "bright": "明亮"}
ASSISTANT_TYPE_LABELS = {"image": "图片", "video": "视频", "document": "文档", "page": "网页"}
ASSISTANT_CONCEPTS = (
    "背景", "人像", "人物", "女性", "男性", "天空", "海边", "海洋", "水面", "花朵", "樱花", "植物", "森林",
    "城市", "街道", "建筑", "室内", "户外", "夜景", "美食", "动物", "猫", "狗", "汽车", "科技", "设计",
    "界面", "海报", "插画", "摄影", "婚礼", "旅行", "教程", "代码", "研究", "小提琴", "舞台", "复古", "极简",
)


def parse_assistant_query_locally(query: str) -> dict:
    text = " ".join(query.strip().split())
    lower = text.lower()
    if re.search(r"(移除|去掉|取消).{0,6}标签", text):
        intent = "remove_tags"
    elif re.search(r"(添加|加上|打上|标记为).{0,6}标签", text):
        intent = "add_tags"
    elif re.search(r"(移到|移动到|放到|归入).{0,10}(文件夹|目录)", text):
        intent = "move_folder"
    else:
        intent = "search"

    material_type = None
    for candidate, words in (
        ("image", ("图片", "照片", "图像", "插画")),
        ("video", ("视频", "短片", "影片")),
        ("document", ("文档", "ppt", "pdf", "word", "文章")),
        ("page", ("网页", "网站", "博客")),
    ):
        if any(word in lower for word in words):
            material_type = candidate
            break

    color_name = None
    for candidate, words in (
        ("neutral", ("黑白", "中性色", "中性调", "单色")),
        ("gray", ("灰色", "灰调", "灰阶")),
        ("black", ("黑色", "黑调")),
        ("white", ("白色", "白调")),
        ("pink", ("粉色", "粉红", "玫红")),
        ("purple", ("紫色", "紫调")),
        ("red", ("红色", "红调")),
        ("orange", ("橙色", "橘色", "橙调")),
        ("yellow", ("黄色", "金色", "黄调")),
        ("green", ("绿色", "绿调")),
        ("cyan", ("青色", "青调")),
        ("blue", ("蓝色", "蓝调")),
        ("warm", ("暖色", "暖调")),
        ("cool", ("冷色", "冷调")),
    ):
        if any(word in lower for word in words):
            color_name = candidate
            break
    color_family = {
        "blue": "blue", "cyan": "blue", "green": "green", "red": "warm", "orange": "warm", "yellow": "warm",
        "warm": "warm", "pink": "pink", "purple": "pink", "gray": "neutral", "black": "neutral", "white": "neutral",
        "neutral": "neutral",
    }.get(color_name)

    brightness = None
    if any(word in text for word in ("偏暗", "暗调", "昏暗", "低亮度", "深色")):
        brightness = "dark"
    elif any(word in text for word in ("明亮", "亮色", "高亮", "通透", "高调")):
        brightness = "bright"
    elif any(word in text for word in ("中等亮度", "中间调")):
        brightness = "medium"

    tags: list[str] = []
    if intent in {"add_tags", "remove_tags"}:
        match = re.search(r"(?:标签|标记为)\s*[：:]?\s*[「『“\"']?([^，。；;、」』”\"']{1,40})", text)
        if match:
            tags = clean_user_tags(re.split(r"[、,，和\s]+", match.group(1)))[:5]

    folder_name = None
    if intent == "move_folder":
        match = re.search(r"(?:移到|移动到|放到|归入)\s*[「『“\"']?([^，。；;、」』”\"']{1,40}?)(?:文件夹|目录)", text)
        if match:
            folder_name = match.group(1).strip()

    concepts = [concept for concept in ASSISTANT_CONCEPTS if concept.lower() in lower]
    stop_parts = {
        "图片", "照片", "图像", "视频", "文档", "网页", "网站", "博客", "蓝色", "蓝调", "青色", "冷色", "绿色", "绿调",
        "暖色", "红色", "橙色", "黄色", "金色", "粉色", "粉红", "紫色", "玫红", "黑白", "灰色", "中性", "单色",
        "黑色", "白色", "冷色",
        "偏暗", "暗调", "昏暗", "明亮", "亮色", "高亮", "通透", "全部", "所有", "素材", "帮我", "找到", "查找", "搜索",
    }
    for part in re.split(r"[\s，。！？、,;；的和]+", text):
        part = re.sub(r"^(?:把|给我|帮我|找出|找到|查找|搜索|筛选|带)", "", part)
        part = re.sub(r"(?:图片|照片|图像|视频|文档|网页|网站|博客|素材)$", "", part)
        if 2 <= len(part) <= 12 and part not in stop_parts and not any(word in part for word in ("标签", "文件夹", "目录")) and not any(part in concept or concept in part for concept in concepts):
            concepts.append(part)
    return {
        "intent": intent,
        "concepts": concepts[:6],
        "negative_concepts": [],
        "material_type": material_type,
        "color_family": color_family,
        "color_name": color_name,
        "brightness": brightness,
        "tags": tags,
        "folder_name": folder_name,
    }


def assistant_rgb_hsv(rgb: object) -> tuple[float, float, float] | None:
    if not isinstance(rgb, (list, tuple)) or len(rgb) < 3:
        return None
    try:
        red, green, blue = [max(0, min(255, float(value))) / 255 for value in rgb[:3]]
    except (TypeError, ValueError):
        return None
    hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
    return hue * 360, saturation, value


def assistant_hue_similarity(hue: float, center: float, tolerance: float) -> float:
    distance = abs((hue - center + 180) % 360 - 180)
    return max(0.0, 1 - distance / tolerance)


def assistant_color_similarity(rgb: object, target: str) -> float:
    hsv = assistant_rgb_hsv(rgb)
    if not hsv:
        return 0.0
    hue, saturation, value = hsv
    if target == "black":
        return max(0.0, min(1.0, (0.34 - value) / 0.28))
    if target == "white":
        return max(0.0, min(1.0, (value - 0.68) / 0.28)) * max(0.0, 1 - saturation / 0.28)
    if target == "gray":
        # A dark shadow or an almost-white highlight is not enough to make an
        # image read as gray. Keep exact-gray search focused on visible
        # mid-tone gray; black and white have their own intents.
        if not 0.18 <= value <= 0.80:
            return 0.0
        return max(0.0, 1 - saturation / 0.26) * (0.72 + 0.28 * (1 - abs(value - 0.53) / 0.53))
    if target == "neutral":
        return max(0.0, 1 - saturation / 0.24)
    if saturation < 0.16 or value < 0.16:
        return 0.0
    centers = {
        "red": (0, 28), "orange": (30, 28), "yellow": (58, 30), "green": (120, 58),
        "cyan": (184, 34), "blue": (224, 48), "purple": (278, 45), "pink": (330, 38),
    }
    if target == "warm":
        hue_score = max(assistant_hue_similarity(hue, center, tolerance) for center, tolerance in (centers["red"], centers["orange"], centers["yellow"], centers["pink"]))
    elif target == "cool":
        hue_score = max(assistant_hue_similarity(hue, center, tolerance) for center, tolerance in (centers["green"], centers["cyan"], centers["blue"], centers["purple"]))
    elif target in centers:
        hue_score = assistant_hue_similarity(hue, *centers[target])
    else:
        return 0.0
    return hue_score * min(1.0, saturation / 0.48) * min(1.0, value / 0.42)


def assistant_color_evidence(palette: list[dict], description: str, target: str, *, strict: bool, context_terms: list[str] | None = None) -> dict:
    matched_ratio = 0.0
    muted_gray_ratio = 0.0
    weighted_ratio = 0.0
    dominant_similarity = 0.0
    dominant_ratio = 0.0
    for index, item in enumerate(palette or []):
        if not isinstance(item, dict):
            continue
        try:
            ratio = max(0.0, min(1.0, float(item.get("ratio") or 0)))
        except (TypeError, ValueError):
            ratio = 0.0
        similarity = assistant_color_similarity(item.get("rgb"), target)
        hsv = assistant_rgb_hsv(item.get("rgb"))
        if target == "gray" and hsv and 0.18 <= hsv[2] <= 0.80 and hsv[1] <= 0.38:
            # Blue-gray and other slightly tinted grays are common in real
            # photography. They only count when the visual description also
            # identifies an overall gray treatment, so muted blue/brown alone
            # cannot satisfy an exact gray query.
            muted_gray_ratio += ratio
        if index == 0:
            dominant_similarity, dominant_ratio = similarity, ratio
        weighted_ratio += ratio * similarity
        if similarity >= 0.56:
            matched_ratio += ratio

    color_words = {
        "red": ("红色", "红调"), "orange": ("橙色", "橘色", "橙调"), "yellow": ("黄色", "金色", "黄调"),
        "green": ("绿色", "绿调"), "cyan": ("青色", "青调"), "blue": ("蓝色", "蓝调", "蓝灰"),
        "purple": ("紫色", "紫调"), "pink": ("粉色", "粉红", "玫红"), "gray": ("灰色", "灰调", "灰阶", "蓝灰"),
        "black": ("黑色", "黑调"), "white": ("白色", "白调"), "warm": ("暖色", "暖调"),
        "cool": ("冷色", "冷调"), "neutral": ("中性色", "中性调", "黑白", "单色"),
    }
    description = description or ""
    mention = any(word in description for word in color_words.get(target, ()))
    tone_patterns = {
        "red": "红", "orange": "橙|橘", "yellow": "黄|金", "green": "绿", "cyan": "青", "blue": "蓝",
        "purple": "紫", "pink": "粉|玫红", "gray": "灰", "black": "黑", "white": "白",
        "warm": "暖", "cool": "冷", "neutral": "中性|黑白|单色",
    }
    needle = tone_patterns.get(target, re.escape(ASSISTANT_COLOR_NAME_LABELS.get(target, target)))
    tone_mention = bool(re.search(rf"(?:整体|主色|色调|以)[^。；]{{0,18}}(?:{needle})|(?:{needle})[^。；]{{0,8}}(?:为主|色调)", description))
    contextual_mention = False
    for term in (context_terms or []):
        if not term:
            continue
        if term == "背景":
            pattern = rf"(?:背景|底色)[^，,。；]{{0,12}}(?:{needle})|(?:{needle})[^，,。；]{{0,6}}(?:背景|底色)"
        else:
            pattern = rf"(?:{needle})[^，,。；]{{0,8}}{re.escape(term)}|{re.escape(term)}[^，,。；]{{0,8}}(?:{needle})"
        if re.search(pattern, description):
            contextual_mention = True
            break

    base_threshold = {
        "gray": 0.24, "black": 0.22, "white": 0.22, "neutral": 0.28,
        "warm": 0.24, "cool": 0.24,
    }.get(target, 0.16)
    relation_required = "背景" in (context_terms or [])
    threshold = base_threshold if strict or relation_required else min(0.08, base_threshold)
    dominant_pass = dominant_similarity >= 0.68 and dominant_ratio >= (0.12 if strict else 0.07)
    description_pass = tone_mention and (
        (target == "gray" and muted_gray_ratio >= (0.20 if strict else 0.08))
        or matched_ratio >= (0.07 if strict else 0.0)
    )
    contextual_pass = not strict and contextual_mention
    if relation_required:
        matched = contextual_pass or tone_mention or matched_ratio >= max(base_threshold, 0.22)
    else:
        matched = matched_ratio >= threshold or dominant_pass or description_pass or contextual_pass
    effective_ratio = max(weighted_ratio, muted_gray_ratio if target == "gray" and tone_mention else 0.0)
    confidence = min(1.0, effective_ratio / max(0.18, base_threshold) * 0.72 + dominant_similarity * 0.18 + (0.10 if tone_mention else 0) + (0.08 if contextual_mention else 0))
    return {
        "matched": matched,
        "matched_ratio": round(matched_ratio, 4),
        "weighted_ratio": round(weighted_ratio, 4),
        "semantic_ratio": round(max(matched_ratio, muted_gray_ratio if target == "gray" and tone_mention else 0.0), 4),
        "dominant_similarity": round(dominant_similarity, 4),
        "description_mention": mention,
        "tone_mention": tone_mention,
        "contextual_mention": contextual_mention,
        "confidence": round(confidence, 3),
    }


def assistant_understanding(parsed: dict) -> str:
    parts: list[str] = []
    if parsed.get("material_type"):
        parts.append(ASSISTANT_TYPE_LABELS[parsed["material_type"]])
    if parsed.get("color_name"):
        parts.append(ASSISTANT_COLOR_NAME_LABELS[parsed["color_name"]])
    elif parsed.get("color_family"):
        parts.append(ASSISTANT_COLOR_LABELS[parsed["color_family"]])
    if parsed.get("brightness"):
        parts.append(ASSISTANT_BRIGHTNESS_LABELS[parsed["brightness"]])
    parts.extend(parsed.get("concepts") or [])
    return " · ".join(dict.fromkeys(parts)) or "按标题、正文、AI 摘要和视觉描述检索"


def assistant_material_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT m.*, v.palette_json, v.histogram_json, v.mean_brightness, v.detail_score, v.visual_description,
                  f.name AS folder_name, e.pdf_path, e.docx_path, e.state AS export_state,
                  d.thumbnail_path, d.thumbnail_width, d.thumbnail_height,
                  d.state AS thumbnail_state, d.error AS thumbnail_error
           FROM materials m
           LEFT JOIN visual_features v ON v.material_id=m.id
           LEFT JOIN folders f ON f.id=m.folder_id
           LEFT JOIN offline_exports e ON e.material_id=m.id
           LEFT JOIN material_derivatives d ON d.material_id=m.id
           WHERE m.deleted_at IS NULL ORDER BY m.captured_at DESC LIMIT 20000"""
    ).fetchall()


def assistant_search(conn: sqlite3.Connection, query: str, parsed: dict, limit: int) -> list[dict]:
    results: list[tuple[float, int, dict]] = []
    concepts = [str(value).lower() for value in parsed.get("concepts") or [] if str(value).strip()]
    negatives = [str(value).lower() for value in parsed.get("negative_concepts") or [] if str(value).strip()]
    for row in assistant_material_rows(conn):
        item = row_to_material(row)
        if parsed.get("material_type") and item["material_type"] != parsed["material_type"]:
            continue
        haystack = " ".join(str(value or "") for value in (
            item.get("title"), item.get("text_content"), item.get("ai_summary"), item.get("visual_description"),
            item.get("category"), item.get("subcategory"), item.get("source_name"),
            " ".join(item.get("tags") or []), " ".join(item.get("entities") or []),
        )).lower()
        if any(value in haystack for value in negatives):
            continue
        reasons: list[str] = []
        score = 0.0
        if parsed.get("material_type"):
            score += 1.0
            reasons.append(f"类型为{ASSISTANT_TYPE_LABELS[parsed['material_type']]}")
        color_target = parsed.get("color_name") or parsed.get("color_family")
        if color_target:
            color_evidence = assistant_color_evidence(
                item.get("palette") or [], item.get("visual_description") or "", color_target,
                strict=not bool(concepts),
                context_terms=concepts,
            )
            if not color_evidence["matched"]:
                continue
            score += 2.0 + max(color_evidence["weighted_ratio"], color_evidence["semantic_ratio"]) * 10 + color_evidence["dominant_similarity"] * 1.5 + (0.8 if color_evidence["tone_mention"] else 0)
            label = ASSISTANT_COLOR_NAME_LABELS.get(color_target) or ASSISTANT_COLOR_LABELS.get(color_target, color_target)
            if color_evidence["semantic_ratio"]:
                reasons.append(f"{label}约占 {round(color_evidence['semantic_ratio'] * 100)}%")
            else:
                reasons.append(f"视觉描述明确提到{label}")
            item["assistant_color_confidence"] = color_evidence["confidence"]
            item["assistant_color_evidence"] = color_evidence
        brightness = parsed.get("brightness")
        if brightness:
            value = item.get("mean_brightness")
            matches = value is not None and (
                (brightness == "dark" and value < 0.40) or
                (brightness == "medium" and 0.36 <= value <= 0.68) or
                (brightness == "bright" and value > 0.64)
            )
            if not matches:
                continue
            score += 1.5
            reasons.append(f"整体{ASSISTANT_BRIGHTNESS_LABELS[brightness]}")
        matched_concepts = [value for value in concepts if value in haystack]
        if concepts and not matched_concepts:
            continue
        if matched_concepts:
            score += min(8.0, len(matched_concepts) * 2.5)
            reasons.extend(f"内容包含“{value}”" for value in matched_concepts[:2])
        if not concepts and not color_target and not brightness and not parsed.get("material_type"):
            literal = query.strip().lower()
            segments = [value for value in re.split(r"[\s，。！？、,;；的和]+", literal) if len(value) >= 2]
            if literal in haystack:
                score += 5.0
                reasons.append("内容直接匹配这句话")
            else:
                matches = [value for value in segments if value in haystack]
                if not matches:
                    continue
                score += len(matches) * 2.0
                reasons.append(f"内容包含“{matches[0]}”")
        item["assistant_reasons"] = list(dict.fromkeys(reasons))[:3]
        results.append((score, int(item.get("captured_at") or 0), item))
    results.sort(key=lambda value: (value[0], value[1]), reverse=True)
    return [item for _, _, item in results[:limit]]


def assistant_items_by_ids(conn: sqlite3.Connection, material_ids: list[str]) -> list[dict]:
    wanted = list(dict.fromkeys(material_ids))
    if not wanted:
        return []
    placeholders = ",".join("?" for _ in wanted)
    rows = conn.execute(
        f"""SELECT m.*, v.palette_json, v.histogram_json, v.mean_brightness, v.detail_score, v.visual_description,
                   f.name AS folder_name, e.pdf_path, e.docx_path, e.state AS export_state,
                   d.thumbnail_path, d.thumbnail_width, d.thumbnail_height,
                   d.state AS thumbnail_state, d.error AS thumbnail_error
            FROM materials m
            LEFT JOIN visual_features v ON v.material_id=m.id
            LEFT JOIN folders f ON f.id=m.folder_id
            LEFT JOIN offline_exports e ON e.material_id=m.id
            LEFT JOIN material_derivatives d ON d.material_id=m.id
            WHERE m.deleted_at IS NULL AND m.id IN ({placeholders})""",
        wanted,
    ).fetchall()
    by_id = {row["id"]: row_to_material(row) for row in rows}
    return [by_id[value] for value in wanted if value in by_id]


def set_material_tags(conn: sqlite3.Connection, current: sqlite3.Row, next_values: list[str]) -> dict:
    next_tags = clean_user_tags(next_values)
    ai_tags = json.loads(current["tags_ai_json"] or "[]")
    user_tags = [tag for tag in next_tags if tag not in ai_tags]
    rejected_tags = [tag for tag in ai_tags if tag not in next_tags]
    conn.execute(
        "UPDATE materials SET tags_json=?, tags_user_json=?, tags_rejected_json=? WHERE id=?",
        (json.dumps(next_tags, ensure_ascii=False), json.dumps(user_tags, ensure_ascii=False), json.dumps(rejected_tags, ensure_ascii=False), current["id"]),
    )
    update_fts_row(conn, current["id"])
    return {"tags": next_tags, "tags_user": user_tags, "tags_rejected": rejected_tags}


def fts_phrase(value: str) -> str:
    """Treat user search text as a literal FTS phrase, never as FTS query syntax."""
    return '"' + value.replace('"', '""') + '"'


def material_owned_files(conn: sqlite3.Connection, material_id: str) -> list[Path]:
    row = conn.execute(
        """SELECT m.local_path, m.snapshot_path, e.html_path, e.pdf_path, e.docx_path, d.thumbnail_path
           FROM materials m LEFT JOIN offline_exports e ON e.material_id=m.id
           LEFT JOIN material_derivatives d ON d.material_id=m.id
           WHERE m.id=?""",
        (material_id,),
    ).fetchone()
    if not row:
        return []
    result: list[Path] = []
    seen: set[Path] = set()
    for value in row:
        if not value:
            continue
        try:
            path = Path(value).absolute()
        except OSError:
            continue
        if path in seen or not path_is_asset(str(path)) or not path.is_file():
            continue
        seen.add(path)
        result.append(path)
    return result


def permanently_delete_material(material_id: str) -> dict:
    with db() as conn:
        material = conn.execute("SELECT id, deleted_at FROM materials WHERE id=?", (material_id,)).fetchone()
        if not material:
            raise HTTPException(404, "素材不存在")
        if material["deleted_at"] is None:
            raise HTTPException(409, "请先将素材移入回收站")
        if conn.execute("SELECT 1 FROM jobs WHERE material_id=? AND state='running'", (material_id,)).fetchone():
            raise HTTPException(409, "素材仍有后台任务运行，请稍后再永久删除")
        files = material_owned_files(conn, material_id)

    recovery_dir = RECOVERY_ROOT / "deletions" / f"{material_id}-{now()}-{uuid.uuid4().hex[:8]}"
    moved: list[tuple[Path, Path]] = []
    try:
        if files:
            recovery_dir.mkdir(parents=True, exist_ok=False)
        for index, source in enumerate(files):
            destination = recovery_dir / f"{index:02d}-{source.name}"
            os.replace(source, destination)
            moved.append((source, destination))
        with db() as conn:
            material = conn.execute("SELECT deleted_at FROM materials WHERE id=?", (material_id,)).fetchone()
            if not material:
                raise HTTPException(404, "素材不存在")
            if material["deleted_at"] is None:
                raise HTTPException(409, "素材已恢复，不能永久删除")
            if conn.execute("SELECT 1 FROM jobs WHERE material_id=? AND state='running'", (material_id,)).fetchone():
                raise HTTPException(409, "素材仍有后台任务运行，请稍后再永久删除")
            conn.execute("DELETE FROM materials_fts WHERE material_id=?", (material_id,))
            conn.execute("DELETE FROM materials WHERE id=?", (material_id,))
    except Exception:
        for source, destination in reversed(moved):
            if destination.exists():
                source.parent.mkdir(parents=True, exist_ok=True)
                os.replace(destination, source)
        if recovery_dir.exists():
            try:
                recovery_dir.rmdir()
            except OSError:
                pass
        raise

    cleanup_pending = False
    for _, destination in moved:
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            cleanup_pending = True
    if recovery_dir.exists():
        try:
            recovery_dir.rmdir()
            recovery_dir.parent.rmdir()
        except OSError:
            cleanup_pending = True
    return {"ok": True, "permanent": True, "removed_files": len(moved), "cleanup_pending": cleanup_pending}


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db(repair=False)
    yield


app = FastAPI(title="myknow Local API", version="0.1.1", lifespan=lifespan)
TRUSTED_LOCAL_ORIGINS = {
    f"http://127.0.0.1:{API_PORT}",
    f"http://localhost:{API_PORT}",
    "http://127.0.0.1:5174",
    "http://localhost:5174",
}
TRUSTED_EXTENSION_ORIGIN = re.compile(r"^chrome-extension://[a-p]{32}$")


def trusted_browser_origin(origin: str) -> bool:
    return origin in TRUSTED_LOCAL_ORIGINS or bool(TRUSTED_EXTENSION_ORIGIN.fullmatch(origin))


app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(TRUSTED_LOCAL_ORIGINS),
    allow_origin_regex=r"^chrome-extension://[a-p]{32}$",
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def protect_local_api(request: Request, call_next):
    """Reject browser requests that did not originate from myknow or its extension.

    CORS alone does not stop a cross-site form or a simple fetch from executing a
    write. The explicit Origin/Sec-Fetch-Site check closes that loop while still
    allowing the native UI, the unpacked Chromium extension and local CLI/tests.
    """
    origin = (request.headers.get("origin") or "").strip()
    fetch_site = (request.headers.get("sec-fetch-site") or "").strip().lower()
    if (origin and not trusted_browser_origin(origin)) or (not origin and fetch_site == "cross-site"):
        return JSONResponse(status_code=403, content={"detail": "已拒绝非 myknow 页面访问本机素材库"})
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "myknow-local-api", "version": app.version}


@app.get("/api/extension/info")
def extension_info() -> dict:
    manifest_path = EXTENSION_ROOT / "manifest.json"
    if not manifest_path.is_file():
        return {"available": False, "version": None, "name": None}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"available": False, "version": None, "name": None}
    return {
        "available": True,
        "version": manifest.get("version"),
        "name": manifest.get("name", "Muse Vault Capture"),
    }


@app.get("/api/extension/download")
def extension_download() -> StreamingResponse:
    """Download a sanitized browser-extension ZIP from the local app.

    The extension is bundled with the packaged desktop executable. The ZIP is
    generated in memory so it never writes a second copy into the user's data
    directory and never includes the user's database or API configuration.
    """
    if not EXTENSION_ROOT.is_dir() or not (EXTENSION_ROOT / "manifest.json").is_file():
        raise HTTPException(404, "浏览器扩展未随当前版本打包")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(EXTENSION_ROOT.rglob("*")):
            if not path.is_file() or path.name in {".DS_Store", "Thumbs.db"}:
                continue
            relative = path.relative_to(EXTENSION_ROOT).as_posix()
            archive.write(path, f"myknow-extension/{relative}")
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="myknow-extension.zip"'},
    )


@app.get("/api/settings/paths")
def storage_paths() -> dict:
    return {
        "data_root": str(ROOT),
        "database": str(DB_PATH),
        "assets": str(ASSET_ROOT),
        "logs": str(LOG_ROOT),
        "recovery": str(RECOVERY_ROOT),
        "settings_note": "路径由桌面启动器读取，修改后需重新启动 Muse Vault。",
    }


@app.get("/api/integrity")
def integrity(repair: bool = False) -> dict:
    return scan_integrity(repair=repair)


@app.post("/api/captures")
def capture(payload: CaptureRequest) -> dict:
    material_id = str(uuid.uuid4())
    decoded = decode_data_url(payload.data_url)
    local_mime, local_content = decoded if decoded else (None, None)
    if local_content and payload.material_type == "video" and len(local_content) > MAX_LOCAL_VIDEO_BYTES:
        raise HTTPException(413, f"视频超过 {MAX_LOCAL_VIDEO_BYTES // (1024 * 1024)}MB 本地保存限制")
    material_content_hash = sha256_bytes(local_content) if local_content and payload.material_type in {"image", "document", "presentation", "video"} else None
    key = fingerprint(payload, material_content_hash)
    canonical_url = canonicalize_url(payload.source_url)
    combined_text = "\n".join(part for part in [payload.title, payload.selection or "", payload.text_content or ""] if part)
    category, subcategory, tags = category_for(combined_text, payload.material_type)
    tags = compact_tags(tags)
    operation = None
    existing_id = None
    was_enriched = False
    response_message = "已进入本机素材分析队列。"
    with db() as conn:
        folder = conn.execute("SELECT id FROM folders WHERE id=?", (payload.folder_id,)).fetchone()
        if not folder:
            raise HTTPException(400, "目标文件夹不存在")
        existing = find_existing_material(conn, payload, material_content_hash)
        if existing:
            existing_id = existing["id"]
            was_deleted = existing["deleted_at"] is not None
            local_path = existing["local_path"]
            snapshot_path = existing["snapshot_path"]
            local_added = bool(local_content and not local_path)
            snapshot_updated = bool(payload.html_content)
            next_text = combined_text or existing["text_content"] or ""
            next_media_url = payload.media_url or existing["media_url"]
            next_thumbnail = payload.thumbnail_url or payload.media_url or existing["thumbnail_url"]
            enriched = local_added or snapshot_updated or next_text != (existing["text_content"] or "") or next_media_url != existing["media_url"] or next_thumbnail != existing["thumbnail_url"]
            was_enriched = enriched
            if local_added or snapshot_updated:
                operation_id = str(uuid.uuid4())
                operation = operation_plan(operation_id, existing_id, payload.material_type, payload.folder_id, local_mime if local_added else None, payload.html_content if snapshot_updated else None)
                create_capture_operation(conn, operation)
            conn.execute(
                """UPDATE materials SET folder_id=?, canonical_url=?, text_content=?, thumbnail_url=?, media_url=?, content_hash=COALESCE(content_hash, ?),
                   status=CASE WHEN ? THEN 'capturing' ELSE CASE WHEN ? THEN 'queued' ELSE status END END,
                   status_reason=NULL, deleted_at=NULL WHERE id=?""",
                (payload.folder_id, canonical_url, next_text, next_thumbnail, next_media_url, material_content_hash,
                 int(bool(operation)), int(enriched and not operation), existing_id),
            )
            if enriched and not operation:
                conn.execute("INSERT OR IGNORE INTO visual_features (material_id) VALUES (?)", (existing_id,))
                conn.execute("INSERT OR IGNORE INTO material_derivatives (material_id) VALUES (?)", (existing_id,))
                queue_material_jobs(conn, existing_id, reset=True)
            if was_deleted:
                conn.execute("UPDATE jobs SET state='queued', attempts=0, next_run_at=?, last_error=NULL WHERE material_id=? AND state='paused'", (now(), existing_id))
                update_fts_row(conn, existing_id)
            response_message = "素材已从回收站恢复并补全可用内容。" if was_deleted else "素材已存在，已移动并补全可用的新内容。" if enriched else "素材已存在，并已移动到目标文件夹。"
        else:
            operation_id = None
            if local_content or payload.html_content:
                operation_id = str(uuid.uuid4())
                operation = operation_plan(operation_id, material_id, payload.material_type, payload.folder_id, local_mime, payload.html_content)
            try:
                conn.execute(
                     """INSERT INTO materials (id, fingerprint, source_url, canonical_url, title, material_type, source_name, local_path,
                        captured_at, status, category, subcategory, text_content, tags_json, tags_ai_json, entities_json, thumbnail_url, media_url,
                        user_permitted_media, folder_id, snapshot_path, content_hash, status_reason)
                            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?, ?, ?, ?, ?)""",
                    (material_id, key, payload.source_url, canonical_url, payload.title, payload.material_type,
                     payload.source_name, now(), "capturing" if operation else "queued", category, subcategory, combined_text,
                     json.dumps(tags, ensure_ascii=False), json.dumps(tags, ensure_ascii=False), payload.thumbnail_url or payload.media_url, payload.media_url,
                     int(payload.user_permitted_media), payload.folder_id, None, material_content_hash,
                     "等待文件落盘" if operation else None),
                )
            except sqlite3.IntegrityError:
                duplicate = find_existing_material(conn, payload, material_content_hash)
                if duplicate:
                    return {
                        "id": duplicate["id"], "deduplicated": True, "moved": False, "enriched": False,
                        "message": "素材正在由另一个采集任务保存，已复用现有记录。",
                    }
                raise
        if not existing_id:
            conn.execute("INSERT INTO visual_features (material_id) VALUES (?)", (material_id,))
            conn.execute("INSERT INTO material_derivatives (material_id) VALUES (?)", (material_id,))
            conn.execute("INSERT INTO transcripts (material_id, state) VALUES (?, ?)", (material_id, "queued" if payload.user_permitted_media and payload.material_type == "video" else "not_requested"))
            conn.execute("INSERT OR IGNORE INTO offline_exports (material_id, html_path, state, updated_at) VALUES (?, NULL, 'not_requested', ?)", (material_id, now()))
            conn.execute("INSERT INTO materials_fts(material_id, title, text_content, ai_summary, tags) VALUES (?, ?, ?, '', ?)", (material_id, payload.title, combined_text, " ".join(tags)))
            if not operation:
                queue_material_jobs(conn, material_id)
        if operation and not existing_id:
            create_capture_operation(conn, operation)
    if operation:
        try:
            write_capture_files(operation, local_content if operation["local_final"] else None, payload.html_content)
            commit_capture_operation(operation["id"], existing_id or material_id, material_content_hash)
        except Exception as error:
            mark_operation_failed(operation["id"], existing_id or material_id, error)
            raise HTTPException(500, f"素材文件落盘失败：{error}") from error
        response_message = "素材已进入本机素材分析队列。"
    return {
        "id": existing_id or material_id,
        "deduplicated": bool(existing_id),
        "moved": bool(existing_id),
        "enriched": bool(operation or was_enriched),
        "message": response_message,
    }


def discard_provisional_import(material_id: str, operation_id: str) -> None:
    cleanup_staging(operation_id)
    with db() as conn:
        conn.execute("DELETE FROM materials_fts WHERE material_id=?", (material_id,))
        conn.execute("DELETE FROM materials WHERE id=?", (material_id,))


@app.post("/api/import/images")
async def import_local_images(
    files: list[UploadFile] = File(...),
    folder_id: str = Form(default="inbox"),
    relative_paths: list[str] = Form(default=[]),
) -> dict:
    if not files:
        raise HTTPException(400, "没有选择图片")
    if len(files) > MAX_LOCAL_IMPORT_FILES:
        raise HTTPException(400, f"单批最多导入 {MAX_LOCAL_IMPORT_FILES} 张图片")
    with db() as conn:
        if not conn.execute("SELECT 1 FROM folders WHERE id=?", (folder_id,)).fetchone():
            raise HTTPException(400, "目标文件夹不存在")

    imported: list[dict] = []
    deduplicated: list[dict] = []
    skipped: list[dict] = []
    failed: list[dict] = []

    for index, upload in enumerate(files):
        raw_name = upload.filename or f"image-{index + 1}"
        filename = Path(raw_name).name
        relative_raw = relative_paths[index] if index < len(relative_paths) else raw_name
        relative_parts = [part for part in relative_raw.replace("\\", "/").split("/") if part not in {"", ".", ".."}]
        relative_path = "/".join(relative_parts)[-1200:] or filename
        mime = local_image_mime(filename, upload.content_type)
        if not mime:
            skipped.append({"path": relative_path, "reason": "当前版本支持 JPG、PNG、WebP、GIF 和 AVIF"})
            await upload.close()
            continue

        material_id = str(uuid.uuid4())
        operation_id = str(uuid.uuid4())
        operation = operation_plan(operation_id, material_id, "image", folder_id, mime, None)
        title = (Path(filename).stem or filename)[:500]
        encoded_path = quote(relative_path, safe="/")
        source_url = f"local-import:///{encoded_path[-3500:]}"
        searchable_source = f"本机导入：{relative_path}"
        provisional_created = False
        final_created = False
        try:
            with db() as conn:
                conn.execute(
                    """INSERT INTO materials
                       (id, fingerprint, source_url, canonical_url, title, material_type, source_name,
                        captured_at, status, category, text_content, tags_json, tags_ai_json,
                        user_permitted_media, folder_id, status_reason)
                       VALUES (?, ?, ?, ?, ?, 'image', '本机图片库', ?, 'capturing', '图片', ?, '[]', '[]', 0, ?, '正在复制本机图片')""",
                    (material_id, f"pending-import:{operation_id}", source_url, source_url, title, now(), searchable_source, folder_id),
                )
                conn.execute("INSERT INTO visual_features (material_id) VALUES (?)", (material_id,))
                conn.execute("INSERT INTO material_derivatives (material_id) VALUES (?)", (material_id,))
                conn.execute("INSERT INTO transcripts (material_id, state) VALUES (?, 'not_requested')", (material_id,))
                conn.execute("INSERT INTO offline_exports (material_id, state, updated_at) VALUES (?, 'not_requested', ?)", (material_id, now()))
                conn.execute(
                    "INSERT INTO materials_fts(material_id, title, text_content, ai_summary, tags) VALUES (?, ?, ?, '', '')",
                    (material_id, title, searchable_source),
                )
                create_capture_operation(conn, operation)
            provisional_created = True

            size, content_hash = await stage_uploaded_file(upload, operation["local_staged"])
            payload = CaptureRequest(source_url=source_url, title=title, material_type="image", folder_id=folder_id)
            with db() as conn:
                existing = conn.execute(
                    """SELECT * FROM materials
                       WHERE id<>? AND material_type='image' AND content_hash=?
                       ORDER BY deleted_at IS NOT NULL, captured_at LIMIT 1""",
                    (material_id, content_hash),
                ).fetchone()
                if existing:
                    existing_id = existing["id"]
                    was_deleted = existing["deleted_at"] is not None
                    conn.execute("DELETE FROM materials_fts WHERE material_id=?", (material_id,))
                    conn.execute("DELETE FROM materials WHERE id=?", (material_id,))
                    conn.execute(
                        "UPDATE materials SET folder_id=?, captured_at=?, deleted_at=NULL WHERE id=?",
                        (folder_id, now(), existing_id),
                    )
                    if was_deleted:
                        paused = conn.execute(
                            "SELECT COUNT(*) FROM jobs WHERE material_id=? AND state='paused'", (existing_id,)
                        ).fetchone()[0]
                        conn.execute(
                            "UPDATE jobs SET state='queued', attempts=0, next_run_at=?, last_error=NULL WHERE material_id=? AND state='paused'",
                            (now(), existing_id),
                        )
                        if paused:
                            conn.execute(
                                "UPDATE materials SET status='analyzing', status_reason=NULL WHERE id=?", (existing_id,)
                            )
                    update_fts_row(conn, existing_id)
                else:
                    existing_id = None
                    conn.execute(
                        "UPDATE materials SET fingerprint=?, content_hash=? WHERE id=?",
                        (fingerprint(payload, content_hash), content_hash, material_id),
                    )

            if existing_id:
                cleanup_staging(operation_id)
                deduplicated.append({"id": existing_id, "path": relative_path, "size": size})
                continue

            operation["local_final"].parent.mkdir(parents=True, exist_ok=True)
            os.replace(operation["local_staged"], operation["local_final"])
            final_created = True
            commit_capture_operation(operation_id, material_id, content_hash)
            cleanup_staging(operation_id)
            imported.append({"id": material_id, "path": relative_path, "size": size})
        except Exception as error:
            await upload.close()
            if provisional_created and final_created:
                mark_operation_failed(operation_id, material_id, error)
            elif provisional_created:
                discard_provisional_import(material_id, operation_id)
            else:
                cleanup_staging(operation_id)
            failed.append({"path": relative_path, "reason": str(error)[:300]})

    return {
        "ok": not failed,
        "imported": len(imported),
        "deduplicated": len(deduplicated),
        "skipped": len(skipped),
        "failed": len(failed),
        "items": imported,
        "duplicates": deduplicated,
        "skipped_items": skipped,
        "failed_items": failed,
        "message": f"新增 {len(imported)} 张，重复 {len(deduplicated)} 张，跳过 {len(skipped)} 张，失败 {len(failed)} 张。",
    }


LINK_IMPORT_MAX_FILES = 5000


def link_import_source_dir(value: str) -> Path:
    source = Path(value).expanduser()
    try:
        source = source.resolve(strict=True)
    except OSError as error:
        raise HTTPException(400, f"源文件夹不可用：{error}") from error
    if not source.is_dir():
        raise HTTPException(400, "源路径不是文件夹")
    asset_root = ASSET_ROOT.resolve()
    if source == asset_root or asset_root in source.parents:
        raise HTTPException(400, "不能把素材库自身再次作为外部引用源")
    return source


def create_external_link(source: Path, destination: Path, mode: str) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    same_volume = source.drive.lower() == destination.drive.lower()
    if mode in {"auto", "hardlink"} and same_volume:
        try:
            os.link(source, destination)
            return "linked_hardlink"
        except OSError as error:
            if mode == "hardlink":
                raise RuntimeError(f"硬链接创建失败：{error}") from error
    elif mode == "hardlink":
        raise RuntimeError("硬链接只能用于同一磁盘分区")
    try:
        os.symlink(str(source), str(destination), target_is_directory=False)
        return "linked_symlink"
    except OSError as error:
        raise RuntimeError("软链接创建失败；请开启 Windows 开发者模式或改用复制模式") from error


@app.post("/api/import/link-folder")
def import_linked_folder(payload: LinkImportRequest) -> dict:
    """Index an image folder without copying its bytes."""
    source_dir = link_import_source_dir(payload.source_dir)
    with db() as conn:
        if not conn.execute("SELECT 1 FROM folders WHERE id=?", (payload.folder_id,)).fetchone():
            raise HTTPException(400, "目标文件夹不存在")
    try:
        candidates = [
            path for path in sorted(source_dir.rglob("*"))
            if path.is_file() and not path.is_symlink() and local_image_mime(path.name, None)
        ]
    except OSError as error:
        raise HTTPException(400, f"读取源文件夹失败：{error}") from error
    if len(candidates) > LINK_IMPORT_MAX_FILES:
        raise HTTPException(400, f"单次最多引用 {LINK_IMPORT_MAX_FILES} 张图片")

    imported: list[dict] = []
    deduplicated: list[dict] = []
    failed: list[dict] = []
    for source in candidates:
        destination: Path | None = None
        try:
            content_hash = sha256_file(source)
            with db() as conn:
                existing = conn.execute(
                    """SELECT * FROM materials
                       WHERE material_type='image' AND content_hash=?
                       ORDER BY deleted_at IS NOT NULL, captured_at LIMIT 1""",
                    (content_hash,),
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE materials SET folder_id=?, captured_at=?, deleted_at=NULL WHERE id=?",
                        (payload.folder_id, now(), existing["id"]),
                    )
                    update_fts_row(conn, existing["id"])
                    deduplicated.append({"id": existing["id"], "path": str(source), "size": source.stat().st_size})
                    continue

            material_id = str(uuid.uuid4())
            destination = ASSET_ROOT / "image" / safe_folder_name(payload.folder_id) / f"{material_id}{source.suffix.lower()}"
            storage_mode = create_external_link(source, destination, payload.link_mode)
            title = (source.stem or source.name)[:500]
            source_url = f"local-link:///{quote(str(source), safe='')}"
            category, subcategory, tags = category_for(f"{title} {source}", "image")
            tags = compact_tags(tags)
            fingerprint_value = hashlib.sha256(f"content|image|{content_hash}".encode("utf-8")).hexdigest()
            try:
                with db() as conn:
                    conn.execute(
                        """INSERT INTO materials
                           (id, fingerprint, source_url, canonical_url, title, material_type, source_name, local_path,
                            captured_at, status, category, subcategory, text_content, tags_json, tags_ai_json,
                            entities_json, thumbnail_url, user_permitted_media, folder_id, snapshot_path,
                            content_hash, status_reason, storage_mode)
                           VALUES (?, ?, ?, ?, ?, 'image', ?, ?, ?, 'queued', ?, ?, ?, ?, ?, '[]', NULL, 0, ?, NULL, ?, ?, ?)""",
                        (material_id, fingerprint_value, source_url, source_url, title, source.parent.name,
                         str(destination), now(), category, subcategory, f"本机外部引用：{source}",
                         json.dumps(tags, ensure_ascii=False), json.dumps(tags, ensure_ascii=False), payload.folder_id,
                         content_hash, "原位置引用，不复制文件", storage_mode),
                    )
                    conn.execute("INSERT INTO visual_features (material_id) VALUES (?)", (material_id,))
                    conn.execute("INSERT INTO material_derivatives (material_id) VALUES (?)", (material_id,))
                    conn.execute("INSERT INTO transcripts (material_id, state) VALUES (?, 'not_requested')", (material_id,))
                    conn.execute("INSERT INTO offline_exports (material_id, state, updated_at) VALUES (?, 'not_requested', ?)", (material_id, now()))
                    conn.execute(
                        "INSERT INTO materials_fts(material_id, title, text_content, ai_summary, visual_description, tags) VALUES (?, ?, ?, '', '', ?)",
                        (material_id, title, f"本机外部引用：{source}", " ".join(tags)),
                    )
                    queue_material_jobs(conn, material_id)
            except Exception:
                destination.unlink(missing_ok=True)
                raise
            imported.append({"id": material_id, "path": str(source), "size": source.stat().st_size, "storage_mode": storage_mode})
        except Exception as error:
            if destination:
                destination.unlink(missing_ok=True)
            failed.append({"path": str(source), "reason": str(error)[:300]})

    return {
        "ok": not failed,
        "mode": payload.link_mode,
        "imported": len(imported),
        "deduplicated": len(deduplicated),
        "failed": len(failed),
        "items": imported,
        "duplicates": deduplicated,
        "failed_items": failed[:50],
        "message": f"新增 {len(imported)} 张，引用去重 {len(deduplicated)} 张，失败 {len(failed)} 张",
    }


@app.post("/api/assistant/query")
def query_material_assistant(payload: AssistantQueryRequest) -> dict:
    query = " ".join(payload.query.split()).strip()
    local_parsed = parse_assistant_query_locally(query)
    parsed = local_parsed
    used_ai = False
    warning = None
    with db() as conn:
        settings = get_processing_settings(conn)
        usage = ai_usage_today(conn)
    status = public_ai_status()
    may_use_ai = (
        payload.use_ai and settings["ai_mode"] != "off" and status["configured"]
        and usage["requests"] < settings["daily_request_limit"]
    )
    if may_use_ai:
        try:
            interpreted = interpret_material_assistant_query(query)
            used_ai = True
            parsed = {
                **local_parsed,
                **{key: interpreted.get(key) for key in (
                    "intent", "material_type", "color_family", "color_name", "brightness", "folder_name"
                ) if interpreted.get(key) is not None},
                "concepts": interpreted.get("concepts") or local_parsed["concepts"],
                "negative_concepts": interpreted.get("negative_concepts") or [],
                "tags": interpreted.get("tags") or local_parsed["tags"],
            }
            with db() as conn:
                model = interpreted.get("_model") or status.get("model")
                request_usage = interpreted.get("_usage") or {}
                conn.execute(
                    """INSERT INTO ai_usage
                       (id, batch_id, material_id, model, request_count, input_tokens, output_tokens, total_tokens, error, created_at)
                       VALUES (?, NULL, NULL, ?, 1, ?, ?, ?, NULL, ?)""",
                    (
                        str(uuid.uuid4()), model,
                        request_usage.get("prompt_tokens") or request_usage.get("input_tokens"),
                        request_usage.get("completion_tokens") or request_usage.get("output_tokens"),
                        request_usage.get("total_tokens"), now(),
                    ),
                )
        except Exception as error:
            warning = f"AI 理解暂不可用，已改用本机检索：{str(error)[:160]}"
    elif payload.use_ai and status["configured"] and settings["ai_mode"] == "off":
        warning = "AI 当前关闭，本次只使用本机索引，不会产生费用。"
    elif payload.use_ai and status["configured"] and usage["requests"] >= settings["daily_request_limit"]:
        warning = "已达到今日 AI 请求限额，本次只使用本机索引。"
    elif payload.use_ai and not status["configured"]:
        warning = "尚未配置 AI，本次只使用本机索引。"

    # Search is always read-only. A management intent is returned as a proposal;
    # the client must still create and confirm a separate action plan.
    with db() as conn:
        items = assistant_search(conn, query, parsed, payload.limit)
        proposed_folder = None
        if parsed.get("folder_name"):
            proposed_folder = conn.execute(
                "SELECT id, name FROM folders WHERE name=? COLLATE NOCASE LIMIT 1", (parsed["folder_name"],)
            ).fetchone()
    proposed_action = None
    if parsed.get("intent") in {"add_tags", "remove_tags", "move_folder"}:
        proposed_action = {
            "action": parsed["intent"],
            "tags": clean_user_tags(parsed.get("tags") or [])[:5],
            "folder": dict(proposed_folder) if proposed_folder else None,
        }
    return {
        "items": items,
        "total": len(items),
        "query": query,
        "understanding": assistant_understanding(parsed),
        "parsed": {key: value for key, value in parsed.items() if not key.startswith("_")},
        "used_ai": used_ai,
        "warning": warning,
        "proposed_action": proposed_action,
        "write_access": "confirmation_required",
        "deletion_access": False,
    }


@app.post("/api/assistant/plans")
def create_assistant_plan(payload: AssistantPlanRequest) -> dict:
    material_ids = list(dict.fromkeys(payload.material_ids))[:200]
    tags = clean_user_tags(payload.tags)[:5]
    if payload.action in {"add_tags", "remove_tags"} and not tags:
        raise HTTPException(400, "请至少填写一个标签")
    if payload.action == "move_folder" and not payload.folder_id:
        raise HTTPException(400, "请选择目标文件夹")
    with db() as conn:
        items = assistant_items_by_ids(conn, material_ids)
        if len(items) != len(material_ids):
            raise HTTPException(409, "部分素材已不存在或在回收站，请刷新结果后重试")
        folder = None
        if payload.action == "move_folder":
            folder = conn.execute("SELECT id, name FROM folders WHERE id=?", (payload.folder_id,)).fetchone()
            if not folder:
                raise HTTPException(400, "目标文件夹不存在")
        action_payload = {"tags": tags, "folder_id": payload.folder_id}
        labels = {
            "add_tags": f"添加标签：{'、'.join(tags)}",
            "remove_tags": f"移除标签：{'、'.join(tags)}",
            "move_folder": f"移动到：{folder['name'] if folder else ''}",
        }
        preview = {
            "count": len(items),
            "action_label": labels[payload.action],
            "sample": [{"id": item["id"], "title": item["title"], "thumbnail_asset_url": item.get("thumbnail_asset_url") or item.get("asset_url")} for item in items[:5]],
        }
        plan_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(32)
        created_at = now()
        expires_at = created_at + 15 * 60
        conn.execute(
            """INSERT INTO assistant_action_plans
               (id, action, material_ids_json, payload_json, preview_json, state, confirmation_hash, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
            (
                plan_id, payload.action, json.dumps(material_ids), json.dumps(action_payload, ensure_ascii=False),
                json.dumps(preview, ensure_ascii=False), hashlib.sha256(token.encode("utf-8")).hexdigest(), created_at, expires_at,
            ),
        )
    return {
        "id": plan_id,
        "state": "pending",
        "preview": preview,
        "confirmation_token": token,
        "expires_at": expires_at,
        "message": "这只是变更预览，尚未修改任何素材。",
    }


@app.post("/api/assistant/plans/{plan_id}/confirm")
def confirm_assistant_plan(plan_id: str, payload: AssistantConfirmRequest) -> dict:
    with db() as conn:
        plan = conn.execute("SELECT * FROM assistant_action_plans WHERE id=?", (plan_id,)).fetchone()
        if not plan:
            raise HTTPException(404, "变更计划不存在")
        if plan["state"] != "pending":
            raise HTTPException(409, "这份变更计划已经处理过")
        if plan["expires_at"] < now():
            conn.execute("UPDATE assistant_action_plans SET state='expired' WHERE id=?", (plan_id,))
            raise HTTPException(409, "变更预览已过期，请重新生成")
        actual_hash = hashlib.sha256(payload.confirmation_token.encode("utf-8")).hexdigest()
        if not secrets.compare_digest(actual_hash, plan["confirmation_hash"]):
            raise HTTPException(403, "确认令牌无效")
        action = plan["action"]
        material_ids = json.loads(plan["material_ids_json"])
        action_payload = json.loads(plan["payload_json"])
        changed_ids: list[str] = []
        for material_id in material_ids:
            current = conn.execute("SELECT * FROM materials WHERE id=? AND deleted_at IS NULL", (material_id,)).fetchone()
            if not current:
                continue
            before = {
                "folder_id": current["folder_id"],
                "tags": json.loads(current["tags_json"] or "[]"),
                "tags_user": json.loads(current["tags_user_json"] or "[]"),
                "tags_rejected": json.loads(current["tags_rejected_json"] or "[]"),
            }
            if action == "add_tags":
                after_tags = set_material_tags(conn, current, [*before["tags"], *action_payload["tags"]])
                after = {"folder_id": current["folder_id"], **after_tags}
            elif action == "remove_tags":
                removing = set(action_payload["tags"])
                after_tags = set_material_tags(conn, current, [tag for tag in before["tags"] if tag not in removing])
                after = {"folder_id": current["folder_id"], **after_tags}
            elif action == "move_folder":
                if not conn.execute("SELECT 1 FROM folders WHERE id=?", (action_payload["folder_id"],)).fetchone():
                    raise HTTPException(409, "目标文件夹已不存在")
                conn.execute("UPDATE materials SET folder_id=? WHERE id=?", (action_payload["folder_id"], material_id))
                after = {**before, "folder_id": action_payload["folder_id"]}
            else:
                raise HTTPException(400, "不支持的助手动作")
            conn.execute(
                """INSERT INTO assistant_action_logs
                   (id, plan_id, material_id, action, before_json, after_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), plan_id, material_id, action, json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False), now()),
            )
            changed_ids.append(material_id)
        if not changed_ids:
            raise HTTPException(409, "没有仍可修改的素材")
        conn.execute("UPDATE assistant_action_plans SET state='executed', executed_at=? WHERE id=?", (now(), plan_id))
        updated_items = assistant_items_by_ids(conn, changed_ids)
    return {
        "ok": True,
        "state": "executed",
        "changed": len(changed_ids),
        "updated_items": updated_items,
        "undo_available": True,
        "message": f"已按你的确认修改 {len(changed_ids)} 条素材。",
    }


@app.post("/api/assistant/plans/{plan_id}/undo")
def undo_assistant_plan(plan_id: str) -> dict:
    with db() as conn:
        plan = conn.execute("SELECT * FROM assistant_action_plans WHERE id=?", (plan_id,)).fetchone()
        if not plan:
            raise HTTPException(404, "变更计划不存在")
        if plan["state"] != "executed":
            raise HTTPException(409, "这份变更当前不可撤销")
        logs = conn.execute("SELECT * FROM assistant_action_logs WHERE plan_id=? ORDER BY created_at DESC", (plan_id,)).fetchall()
        restored_ids: list[str] = []
        skipped = 0
        for log in logs:
            current = conn.execute("SELECT * FROM materials WHERE id=? AND deleted_at IS NULL", (log["material_id"],)).fetchone()
            if not current:
                skipped += 1
                continue
            before = json.loads(log["before_json"])
            after = json.loads(log["after_json"])
            if log["action"] == "move_folder":
                if current["folder_id"] != after.get("folder_id"):
                    skipped += 1
                    continue
                conn.execute("UPDATE materials SET folder_id=? WHERE id=?", (before.get("folder_id"), current["id"]))
            else:
                if json.loads(current["tags_json"] or "[]") != after.get("tags", []):
                    skipped += 1
                    continue
                conn.execute(
                    "UPDATE materials SET tags_json=?, tags_user_json=?, tags_rejected_json=? WHERE id=?",
                    (
                        json.dumps(before.get("tags", []), ensure_ascii=False),
                        json.dumps(before.get("tags_user", []), ensure_ascii=False),
                        json.dumps(before.get("tags_rejected", []), ensure_ascii=False), current["id"],
                    ),
                )
                update_fts_row(conn, current["id"])
            restored_ids.append(current["id"])
        conn.execute("UPDATE assistant_action_plans SET state='undone', undone_at=? WHERE id=?", (now(), plan_id))
        updated_items = assistant_items_by_ids(conn, restored_ids)
    return {
        "ok": True,
        "state": "undone",
        "restored": len(restored_ids),
        "skipped": skipped,
        "updated_items": updated_items,
        "message": f"已撤销 {len(restored_ids)} 条修改" + (f"，另有 {skipped} 条因之后被改动而保留现状。" if skipped else "。"),
    }


@app.get("/api/materials")
def list_materials(
    q: str | None = Query(default=None, max_length=200),
    material_type: str | None = None,
    category: str | None = None,
    folder_id: str | None = None,
    tag: list[str] = Query(default=[]),
    min_brightness: float | None = Query(default=None, ge=0, le=1),
    max_brightness: float | None = Query(default=None, ge=0, le=1),
    limit: int = Query(default=60, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    view: Literal["library", "trash"] = "library",
) -> dict:
    clauses, values = ["m.deleted_at IS NOT NULL" if view == "trash" else "m.deleted_at IS NULL"], []
    if q:
        clauses.append("""(m.id IN (SELECT material_id FROM materials_fts WHERE materials_fts MATCH ?)
                          OR m.title LIKE ? OR m.text_content LIKE ? OR m.ai_summary LIKE ?
                          OR v.visual_description LIKE ? OR m.tags_json LIKE ?)""")
        like = f"%{q}%"
        values.extend([fts_phrase(q), like, like, like, like, like])
    if material_type:
        clauses.append("m.material_type = ?"); values.append(material_type)
    if category:
        clauses.append("(m.category = ? OR m.subcategory = ?)"); values.extend([category, category])
    if folder_id:
        clauses.append("m.folder_id = ?"); values.append(folder_id)
    for selected_tag in tag:
        clauses.append("EXISTS (SELECT 1 FROM json_each(m.tags_json) WHERE json_each.value = ?)")
        values.append(selected_tag)
    if min_brightness is not None:
        clauses.append("COALESCE(v.mean_brightness, 0.5) >= ?"); values.append(min_brightness)
    if max_brightness is not None:
        clauses.append("COALESCE(v.mean_brightness, 0.5) <= ?"); values.append(max_brightness)
    with db() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM materials m LEFT JOIN visual_features v ON v.material_id=m.id WHERE {' AND '.join(clauses)}", values).fetchone()[0]
        query = f"""SELECT m.*, v.palette_json, v.histogram_json, v.mean_brightness, v.detail_score, v.visual_description,
                        f.name AS folder_name, e.pdf_path, e.docx_path, e.state AS export_state,
                        d.thumbnail_path, d.thumbnail_width, d.thumbnail_height,
                        d.state AS thumbnail_state, d.error AS thumbnail_error
                 FROM materials m
                 LEFT JOIN visual_features v ON v.material_id=m.id
                 LEFT JOIN folders f ON f.id=m.folder_id
                 LEFT JOIN offline_exports e ON e.material_id=m.id
                 LEFT JOIN material_derivatives d ON d.material_id=m.id
                 WHERE {' AND '.join(clauses)} ORDER BY m.captured_at DESC LIMIT ? OFFSET ?"""
        rows = conn.execute(query, [*values, limit, offset]).fetchall()
    return {
        "items": [row_to_material(row) for row in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(rows) < total,
        "next_offset": offset + len(rows) if offset + len(rows) < total else None,
    }


@app.get("/api/materials/{material_id}")
def material_detail(material_id: str) -> dict:
    with db() as conn:
        row = conn.execute("""SELECT m.*, v.palette_json, v.histogram_json, v.mean_brightness, v.detail_score, v.visual_description,
                                     f.name AS folder_name, e.pdf_path, e.docx_path, e.state AS export_state, e.error AS export_error,
                                     d.thumbnail_path, d.thumbnail_width, d.thumbnail_height,
                                     d.state AS thumbnail_state, d.error AS thumbnail_error
                              FROM materials m
                              LEFT JOIN visual_features v ON v.material_id=m.id
                              LEFT JOIN folders f ON f.id=m.folder_id
                              LEFT JOIN offline_exports e ON e.material_id=m.id
                              LEFT JOIN material_derivatives d ON d.material_id=m.id
                              WHERE m.id=?""", (material_id,)).fetchone()
        if not row:
            raise HTTPException(404, "素材不存在")
        transcript = conn.execute("SELECT * FROM transcripts WHERE material_id=?", (material_id,)).fetchone()
        jobs = conn.execute("SELECT stage, state, attempts, last_error FROM jobs WHERE material_id=? ORDER BY stage", (material_id,)).fetchall()
    result = row_to_material(row)
    result["transcript"] = dict(transcript) if transcript else None
    result["jobs"] = [dict(job) for job in jobs]
    return result


@app.post("/api/materials/{material_id}/reveal-location")
def reveal_material_location(material_id: str) -> dict:
    """Reveal a material's local source in the native file manager."""
    with db() as conn:
        row = conn.execute("SELECT local_path, snapshot_path FROM materials WHERE id=?", (material_id,)).fetchone()
    if not row:
        raise HTTPException(404, "绱犳潗涓嶅瓨鍦ㄣ€?")
    raw_path = row["local_path"] or row["snapshot_path"]
    if not raw_path:
        raise HTTPException(409, "璇ユ潗鏂欐病鏈夊彲瀹氫綅鐨勬湰鍦板師濮嬫枃浠躲€?")
    path = Path(raw_path).expanduser()
    try:
        path = path.resolve()
    except OSError as error:
        raise HTTPException(400, f"鏃犳硶瑙ｆ瀽鍘熷璺緞锛歕n{error}") from error
    if not path.is_file():
        raise HTTPException(404, "鍘熷鏂囦欢宸蹭笉瀛樺湪鎴栨棤娉曡闂€?")
    try:
        if os.name == "nt":
            subprocess.Popen(["explorer.exe", f"/select,{path}"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
    except OSError as error:
        raise HTTPException(500, f"鏃犳硅闂枃浠剁鐞嗗櫒锛歕n{error}") from error
    return {"ok": True, "path": str(path)}


@app.get("/api/materials/{material_id}/asset")
def material_asset(material_id: str) -> FileResponse:
    with db() as conn:
        row = conn.execute("SELECT local_path FROM materials WHERE id=?", (material_id,)).fetchone()
    if not row or not row["local_path"]:
        raise HTTPException(404, "素材没有本地预览文件")
    path = Path(row["local_path"]).absolute()
    if not path_is_asset(str(path)) or not path.is_file():
        raise HTTPException(404, "本地预览文件不存在")
    media_type = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
        ".gif": "image/gif", ".avif": "image/avif", ".pdf": "application/pdf",
    }.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=300"})


@app.get("/api/materials/{material_id}/thumbnail")
def material_thumbnail(material_id: str) -> FileResponse:
    with db() as conn:
        row = conn.execute(
            "SELECT thumbnail_path, state FROM material_derivatives WHERE material_id=?",
            (material_id,),
        ).fetchone()
    if not row or row["state"] != "ready" or not row["thumbnail_path"]:
        raise HTTPException(404, "缩略图尚未生成")
    path = Path(row["thumbnail_path"]).absolute()
    if not path_is_asset(str(path)) or not path.is_file():
        raise HTTPException(404, "缩略图文件不存在")
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "private, max-age=86400"})


@app.post("/api/materials/{material_id}/thumbnail/rebuild")
def rebuild_material_thumbnail(material_id: str) -> dict:
    with db() as conn:
        material = conn.execute(
            "SELECT id, material_type, local_path, deleted_at FROM materials WHERE id=?",
            (material_id,),
        ).fetchone()
        if not material or material["deleted_at"] is not None:
            raise HTTPException(404, "素材不存在")
        if material["material_type"] not in {"image", "page", "blog"} or not material["local_path"]:
            raise HTTPException(409, "当前素材没有可生成缩略图的本地画面")
        if not Path(material["local_path"]).is_file():
            raise HTTPException(409, "生成缩略图所需的本地文件不存在")
        conn.execute("INSERT OR IGNORE INTO material_derivatives (material_id) VALUES (?)", (material_id,))
        conn.execute(
            "UPDATE material_derivatives SET state='queued', error=NULL, updated_at=? WHERE material_id=?",
            (now(), material_id),
        )
        requeue_job(conn, material_id, "thumbnail")
        conn.execute("UPDATE materials SET status='queued', status_reason=NULL WHERE id=?", (material_id,))
    return {"ok": True, "state": "queued", "message": "缩略图已加入重建队列"}


@app.patch("/api/materials/{material_id}")
def update_material(material_id: str, patch: MaterialPatch) -> dict:
    with db() as conn:
        current = conn.execute("SELECT * FROM materials WHERE id=?", (material_id,)).fetchone()
        if not current:
            raise HTTPException(404, "素材不存在")
        if current["deleted_at"] is not None:
            raise HTTPException(409, "请先从回收站恢复素材")
        fields, values = [], []
        if patch.category is not None: fields.append("category=?"); values.append(patch.category)
        if "subcategory" in patch.model_fields_set: fields.append("subcategory=?"); values.append(patch.subcategory)
        if patch.tags is not None:
            next_tags = clean_user_tags(patch.tags)
            ai_tags = json.loads(current["tags_ai_json"] or "[]")
            user_tags = [tag for tag in next_tags if tag not in ai_tags]
            rejected_tags = [tag for tag in ai_tags if tag not in next_tags]
            fields.extend(["tags_json=?", "tags_user_json=?", "tags_rejected_json=?"])
            values.extend([
                json.dumps(next_tags, ensure_ascii=False),
                json.dumps(user_tags, ensure_ascii=False),
                json.dumps(rejected_tags, ensure_ascii=False),
            ])
        if patch.folder_id is not None:
            if not conn.execute("SELECT 1 FROM folders WHERE id=?", (patch.folder_id,)).fetchone():
                raise HTTPException(400, "目标文件夹不存在")
            fields.append("folder_id=?"); values.append(patch.folder_id)
        if not fields:
            raise HTTPException(400, "没有可更新字段")
        values.append(material_id)
        cursor = conn.execute(f"UPDATE materials SET {', '.join(fields)} WHERE id=?", values)
        if cursor.rowcount == 0: raise HTTPException(404, "素材不存在")
        if patch.tags is not None:
            update_fts_row(conn, material_id)
    return {"ok": True}


@app.delete("/api/materials/{material_id}")
def delete_material(material_id: str, permanent: bool = False) -> dict:
    if permanent:
        return permanently_delete_material(material_id)
    with db() as conn:
        material = conn.execute("SELECT deleted_at FROM materials WHERE id=?", (material_id,)).fetchone()
        if not material:
            raise HTTPException(404, "素材不存在")
        if material["deleted_at"] is not None:
            return {"ok": True, "permanent": False, "already_deleted": True}
        deleted_at = now()
        conn.execute("UPDATE materials SET deleted_at=? WHERE id=?", (deleted_at, material_id))
        conn.execute("UPDATE jobs SET state='paused' WHERE material_id=? AND state='queued'", (material_id,))
        conn.execute("DELETE FROM materials_fts WHERE material_id=?", (material_id,))
    return {"ok": True, "permanent": False, "deleted_at": deleted_at}


@app.post("/api/materials/{material_id}/restore")
def restore_material(material_id: str) -> dict:
    with db() as conn:
        material = conn.execute("SELECT deleted_at, status FROM materials WHERE id=?", (material_id,)).fetchone()
        if not material:
            raise HTTPException(404, "素材不存在")
        if material["deleted_at"] is None:
            return {"ok": True, "already_restored": True}
        paused = conn.execute("SELECT COUNT(*) FROM jobs WHERE material_id=? AND state='paused'", (material_id,)).fetchone()[0]
        conn.execute("UPDATE jobs SET state='queued', attempts=0, next_run_at=?, last_error=NULL WHERE material_id=? AND state='paused'", (now(), material_id))
        if paused:
            conn.execute("UPDATE materials SET deleted_at=NULL, status='analyzing', status_reason=NULL WHERE id=?", (material_id,))
        else:
            conn.execute("UPDATE materials SET deleted_at=NULL WHERE id=?", (material_id,))
        update_fts_row(conn, material_id)
    return {"ok": True, "requeued_jobs": paused}


@app.post("/api/trash/restore-all")
def restore_all_trash() -> dict:
    """Restore every item currently in the recycle bin in one operation."""
    with db() as conn:
        material_ids = [row["id"] for row in conn.execute(
            "SELECT id FROM materials WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC"
        ).fetchall()]

    restored = 0
    requeued_jobs = 0
    failed: list[dict] = []
    for material_id in material_ids:
        try:
            result = restore_material(material_id)
            if not result.get("already_restored"):
                restored += 1
                requeued_jobs += int(result.get("requeued_jobs") or 0)
        except HTTPException as exc:
            failed.append({"id": material_id, "detail": str(exc.detail)})
        except Exception:
            failed.append({"id": material_id, "detail": "恢复失败"})

    return {
        "ok": not failed,
        "total": len(material_ids),
        "restored": restored,
        "requeued_jobs": requeued_jobs,
        "failed": failed,
    }


@app.post("/api/trash/permanent-delete-all")
def permanently_delete_all_trash() -> dict:
    """Permanently remove every item in the recycle bin, preserving failures."""
    with db() as conn:
        material_ids = [row["id"] for row in conn.execute(
            "SELECT id FROM materials WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC"
        ).fetchall()]

    deleted = 0
    removed_files = 0
    failed: list[dict] = []
    for material_id in material_ids:
        try:
            result = permanently_delete_material(material_id)
            deleted += 1
            removed_files += int(result.get("removed_files") or 0)
        except HTTPException as exc:
            failed.append({"id": material_id, "detail": str(exc.detail)})
        except Exception:
            failed.append({"id": material_id, "detail": "永久删除失败"})

    return {
        "ok": not failed,
        "total": len(material_ids),
        "deleted": deleted,
        "removed_files": removed_files,
        "failed": failed,
    }


@app.get("/api/categories")
def categories() -> dict:
    with db() as conn:
        rows = conn.execute("SELECT category, COALESCE(subcategory, '未细分') AS subcategory, COUNT(*) AS count FROM materials WHERE deleted_at IS NULL GROUP BY category, subcategory ORDER BY category, count DESC").fetchall()
    return {"items": [dict(row) for row in rows]}


@app.get("/api/folders")
def folders() -> dict:
    with db() as conn:
        rows = conn.execute("""SELECT f.id, f.name, f.parent_id, f.sort_order,
                                      COUNT(CASE WHEN m.deleted_at IS NULL THEN m.id END) AS count
                               FROM folders f LEFT JOIN materials m ON m.folder_id=f.id
                               GROUP BY f.id ORDER BY f.sort_order, f.created_at, f.name""").fetchall()
    return {"items": [dict(row) for row in rows]}


@app.post("/api/folders")
def create_folder(payload: FolderRequest) -> dict:
    folder_id = str(uuid.uuid4())
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "文件夹名称不能为空")
    with db() as conn:
        if payload.parent_id and not conn.execute("SELECT 1 FROM folders WHERE id=?", (payload.parent_id,)).fetchone():
            raise HTTPException(400, "父文件夹不存在")
        duplicate = conn.execute(
            """SELECT 1 FROM folders WHERE name=?
               AND ((parent_id IS NULL AND ? IS NULL) OR parent_id=?)""",
            (name, payload.parent_id, payload.parent_id),
        ).fetchone()
        if duplicate:
            raise HTTPException(409, "同级文件夹名称已存在")
        try:
            conn.execute("INSERT INTO folders (id, name, parent_id, created_at) VALUES (?, ?, ?, ?)", (folder_id, name, payload.parent_id, now()))
        except sqlite3.IntegrityError as error:
            raise HTTPException(409, "同级文件夹名称已存在") from error
    return {"id": folder_id, "name": name, "parent_id": payload.parent_id}


@app.get("/api/tags")
def tags() -> dict:
    with db() as conn:
        rows = conn.execute("""SELECT json_each.value AS name, COUNT(*) AS count
                               FROM materials, json_each(materials.tags_json)
                               WHERE materials.deleted_at IS NULL AND TRIM(json_each.value) <> ''
                               GROUP BY json_each.value ORDER BY count DESC, name LIMIT 200""").fetchall()
    return {"items": [dict(row) for row in rows]}


@app.get("/api/ai/status")
def ai_status() -> dict:
    status = public_ai_status()
    with db() as conn:
        settings = get_processing_settings(conn)
        pending = len(eligible_ai_materials(conn))
        usage = ai_usage_today(conn)
        recent = [dict(row) for row in conn.execute(
            "SELECT * FROM ai_batch_runs ORDER BY created_at DESC LIMIT 5"
        )]
        for batch in recent:
            batch["retryable_items"] = conn.execute(
                "SELECT COUNT(*) FROM ai_batch_items WHERE batch_id=? AND (state='failed' OR (state='paused' AND error IS NOT NULL))",
                (batch["id"],),
            ).fetchone()[0]
        latest_error = conn.execute(
            """SELECT id, batch_id, model, error, created_at
               FROM ai_usage WHERE error IS NOT NULL ORDER BY created_at DESC LIMIT 1"""
        ).fetchone()
        latest_success_at = conn.execute(
            "SELECT MAX(created_at) FROM ai_usage WHERE error IS NULL"
        ).fetchone()[0]
    alert = None
    if latest_error and (latest_success_at is None or latest_error["created_at"] >= latest_success_at):
        alert = {
            "id": latest_error["id"],
            "batch_id": latest_error["batch_id"],
            "model": latest_error["model"],
            "created_at": latest_error["created_at"],
            "message": ai_alert_message(latest_error["error"]),
        }
    return {**status, **settings, "pending_items": pending, "usage_today": usage, "recent_batches": recent, "ai_alert": alert}


@app.put("/api/ai/config")
def configure_ai(payload: AIConfigRequest) -> dict:
    try:
        status = save_ai_config(payload.base_url.strip(), payload.model.strip(), payload.api_key)
        return {**status, "message": "AI 接口已保存。是否调用由处理模式和用户操作决定。"}
    except (ValueError, OSError) as error:
        raise HTTPException(400, str(error)) from error


@app.put("/api/processing/settings")
def update_processing_settings(payload: ProcessingSettingsRequest) -> dict:
    if payload.export_policy == "auto" and not payload.export_formats:
        raise HTTPException(422, "自动生成离线文档时，请至少选择 PDF 或 Word")
    with db() as conn:
        current = get_processing_settings(conn)
        next_settings = {
            "ai_mode": payload.ai_mode,
            "auto_idle_minutes": payload.auto_idle_minutes,
            "auto_since": current.get("auto_since", 0),
            "daily_request_limit": payload.daily_request_limit,
            "batch_size": payload.batch_size,
            "export_policy": payload.export_policy,
            "export_formats": list(dict.fromkeys(payload.export_formats)),
        }
        if payload.ai_mode == "auto" and current["ai_mode"] != "auto":
            next_settings["auto_since"] = 0 if payload.include_existing_on_auto else now()

        affected_batches: list[str] = []
        if payload.ai_mode == "off":
            rows = conn.execute(
                "SELECT id FROM ai_batch_runs WHERE state IN ('queued','running','stopping')"
            ).fetchall()
            affected_batches = [row["id"] for row in rows]
        elif current["ai_mode"] == "auto" and payload.ai_mode != "auto":
            rows = conn.execute(
                "SELECT id FROM ai_batch_runs WHERE trigger_type='auto' AND state IN ('queued','running','stopping')"
            ).fetchall()
            affected_batches = [row["id"] for row in rows]
        for batch_id in affected_batches:
            running = conn.execute(
                "SELECT 1 FROM jobs WHERE batch_id=? AND stage='ai_enrich' AND state='running'", (batch_id,)
            ).fetchone()
            conn.execute(
                "UPDATE jobs SET state='paused' WHERE batch_id=? AND stage='ai_enrich' AND state='queued'", (batch_id,)
            )
            conn.execute(
                "UPDATE ai_batch_items SET state='paused' WHERE batch_id=? AND state='queued'", (batch_id,)
            )
            conn.execute(
                "UPDATE ai_batch_runs SET state=?, stopped_at=? WHERE id=?",
                ("stopping" if running else "paused", now(), batch_id),
            )
        saved = set_processing_settings(conn, next_settings)
    return {**saved, "paused_batches": len(affected_batches), "restart_required": False}


@app.post("/api/ai/batches")
def start_manual_ai_batch(payload: AIBatchRequest) -> dict:
    try:
        with db() as conn:
            settings = get_processing_settings(conn)
            if settings["ai_mode"] == "off":
                raise ValueError("AI 当前关闭。请先切换到手动批量或自动批量模式")
            if payload.scope == "folder" and not conn.execute("SELECT 1 FROM folders WHERE id=?", (payload.folder_id,)).fetchone():
                raise ValueError("目标文件夹不存在")
            material_ids = eligible_ai_materials(
                conn,
                scope=payload.scope,
                folder_id=payload.folder_id,
                recent_hours=payload.recent_hours,
                force=payload.force,
            )
            return create_ai_batch(
                conn,
                material_ids,
                trigger_type="manual",
                scope=payload.scope,
                batch_size=payload.batch_size or settings.get("batch_size", 100),
            )
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@app.get("/api/ai/batches")
def list_ai_batches(limit: int = Query(default=10, ge=1, le=100)) -> dict:
    with db() as conn:
        rows = [dict(row) for row in conn.execute(
            "SELECT * FROM ai_batch_runs ORDER BY created_at DESC LIMIT ?", (limit,)
        )]
    return {"items": rows}


@app.get("/api/ai/batches/{batch_id}")
def get_ai_batch(batch_id: str) -> dict:
    with db() as conn:
        result = ai_batch_detail(conn, batch_id)
    if not result:
        raise HTTPException(404, "批次不存在")
    return result


@app.get("/api/ai/logs")
def list_ai_logs(
    limit: int = Query(default=80, ge=1, le=500),
    batch_id: str | None = Query(default=None, max_length=100),
) -> dict:
    """Return a compact, user-facing activity feed for AI processing."""
    with db() as conn:
        settings = get_processing_settings(conn)
        usage_today = ai_usage_today(conn)
        events: list[dict] = []
        usage_rows = conn.execute(
            """SELECT u.created_at, u.batch_id, u.material_id, u.model, u.input_tokens,
                      u.output_tokens, u.total_tokens, u.error, m.title
               FROM ai_usage u LEFT JOIN materials m ON m.id=u.material_id
               WHERE (? IS NULL OR u.batch_id=?)
               ORDER BY u.created_at DESC LIMIT ?""",
            (batch_id, batch_id, min(limit, 500)),
        ).fetchall()
        for row in usage_rows:
            error = row["error"]
            events.append({
                "created_at": row["created_at"],
                "level": "error" if error else "success",
                "kind": "request",
                "message": error or "AI 已完成一条素材分析",
                "batch_id": row["batch_id"],
                "material_id": row["material_id"],
                "title": row["title"],
                "model": row["model"],
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "total_tokens": row["total_tokens"],
            })

        queued_item_rows = conn.execute(
            """SELECT i.batch_id, i.material_id, i.state, m.title,
                      COALESCE(j.next_run_at, b.created_at) AS created_at
               FROM ai_batch_items i
               JOIN ai_batch_runs b ON b.id=i.batch_id
               JOIN materials m ON m.id=i.material_id
               LEFT JOIN jobs j ON j.batch_id=i.batch_id AND j.material_id=i.material_id AND j.stage='ai_enrich'
               WHERE i.state IN ('queued','running') AND (? IS NULL OR i.batch_id=?)
               ORDER BY created_at DESC LIMIT ?""",
            (batch_id, batch_id, min(limit, 500)),
        ).fetchall()
        for row in queued_item_rows:
            running = row["state"] == "running"
            events.append({
                "created_at": row["created_at"],
                "level": "info",
                "kind": "item",
                "message": "正在解析这一条素材" if running else "已进入 AI 队列，等待解析",
                "batch_id": row["batch_id"],
                "material_id": row["material_id"],
                "title": row["title"],
                "model": None,
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
            })

        batch_rows = conn.execute(
            """SELECT id, state, total_items, processed_items, failed_items,
                      created_at, started_at, completed_at, stopped_at
               FROM ai_batch_runs
               WHERE (? IS NULL OR id=?)
               ORDER BY COALESCE(stopped_at, completed_at, started_at, created_at) DESC
               LIMIT ?""",
            (batch_id, batch_id, min(50, limit)),
        ).fetchall()
        batch_labels = {
            "queued": "批次已排队",
            "running": "批次正在运行",
            "stopping": "批次正在停止",
            "paused": "批次已暂停",
            "completed": "批次已完成",
            "partial": "批次部分完成",
            "failed": "批次处理失败",
        }
        for row in batch_rows:
            timestamp = row["stopped_at"] or row["completed_at"] or row["started_at"] or row["created_at"]
            events.append({
                "created_at": timestamp,
                "level": "error" if row["state"] in {"failed", "partial"} else "info",
                "kind": "batch",
                "message": f"{batch_labels.get(row['state'], row['state'])}：已处理 {row['processed_items']} / {row['total_items']} 条",
                "batch_id": row["id"],
                "material_id": None,
                "title": None,
                "model": None,
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
            })

        paused_rows = conn.execute(
            """SELECT i.batch_id, i.material_id, i.error, m.title
               FROM ai_batch_items i JOIN materials m ON m.id=i.material_id
               WHERE i.error IS NOT NULL AND (? IS NULL OR i.batch_id=?)
               ORDER BY i.batch_id DESC LIMIT ?""",
            (batch_id, batch_id, min(limit, 500)),
        ).fetchall()
        for row in paused_rows:
            events.append({
                "created_at": None,
                "level": "warning",
                "kind": "item",
                "message": row["error"],
                "batch_id": row["batch_id"],
                "material_id": row["material_id"],
                "title": row["title"],
                "model": None,
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
            })

        if usage_today["requests"] >= settings["daily_request_limit"]:
            events.append({
                "created_at": now(),
                "level": "warning",
                "kind": "quota",
                "message": f"已达到每日 AI 请求上限（{settings['daily_request_limit']} 次），未完成任务已暂停；这不是模型额度耗尽。",
                "batch_id": batch_id,
                "material_id": None,
                "title": None,
                "model": None,
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
            })

    events.sort(key=lambda event: event["created_at"] or 0, reverse=True)
    return {
        "items": events[:limit],
        "usage_today": usage_today,
        "daily_request_limit": settings["daily_request_limit"],
    }


@app.post("/api/ai/batches/{batch_id}/pause")
def pause_ai_batch(batch_id: str) -> dict:
    with db() as conn:
        batch = conn.execute("SELECT state FROM ai_batch_runs WHERE id=?", (batch_id,)).fetchone()
        if not batch:
            raise HTTPException(404, "批次不存在")
        if batch["state"] in {"completed", "partial"}:
            raise HTTPException(409, "这个批次已经结束")
        running = conn.execute(
            "SELECT 1 FROM jobs WHERE batch_id=? AND stage='ai_enrich' AND state='running'", (batch_id,)
        ).fetchone()
        conn.execute("UPDATE jobs SET state='paused' WHERE batch_id=? AND stage='ai_enrich' AND state='queued'", (batch_id,))
        conn.execute("UPDATE ai_batch_items SET state='paused' WHERE batch_id=? AND state='queued'", (batch_id,))
        conn.execute(
            "UPDATE ai_batch_runs SET state=?, stopped_at=? WHERE id=?",
            ("stopping" if running else "paused", now(), batch_id),
        )
    return {"ok": True, "state": "stopping" if running else "paused"}


@app.post("/api/ai/batches/{batch_id}/resume")
def resume_ai_batch(batch_id: str) -> dict:
    with db() as conn:
        batch = conn.execute("SELECT state FROM ai_batch_runs WHERE id=?", (batch_id,)).fetchone()
        if not batch:
            raise HTTPException(404, "批次不存在")
        if batch["state"] not in {"paused", "stopping"}:
            raise HTTPException(409, "这个批次当前不需要恢复")
        conn.execute(
            "UPDATE jobs SET state='queued', next_run_at=?, last_error=NULL WHERE batch_id=? AND stage='ai_enrich' AND state='paused'",
            (now(), batch_id),
        )
        conn.execute("UPDATE ai_batch_items SET state='queued', error=NULL WHERE batch_id=? AND state='paused'", (batch_id,))
        conn.execute("UPDATE ai_batch_runs SET state='queued', stopped_at=NULL WHERE id=?", (batch_id,))
    return {"ok": True, "state": "queued"}


@app.post("/api/ai/batches/{batch_id}/retry-failed")
def retry_failed_ai_batch(batch_id: str) -> dict:
    """Requeue only failed AI items after the user fixes the provider/model."""
    with db() as conn:
        batch = conn.execute("SELECT * FROM ai_batch_runs WHERE id=?", (batch_id,)).fetchone()
        if not batch:
            raise HTTPException(404, "鎵规涓嶅瓨鍦?")
        failed = conn.execute(
            "SELECT material_id FROM ai_batch_items WHERE batch_id=? AND (state='failed' OR (state='paused' AND error IS NOT NULL))",
            (batch_id,),
        ).fetchall()
        if not failed:
            raise HTTPException(409, "褰撳墠鎵规娌℃湁鍙噸璇曠殑澶辫触椤?")
        for row in failed:
            material_id = row["material_id"]
            requeue_job(conn, material_id, "ai_enrich", batch_id=batch_id)
            requeue_job(conn, material_id, "index")
            conn.execute(
                "UPDATE ai_batch_items SET state='queued', error=NULL WHERE batch_id=? AND material_id=?",
                (batch_id, material_id),
            )
            conn.execute(
                "UPDATE materials SET status='analyzing', status_reason=NULL WHERE id=?",
                (material_id,),
            )
        conn.execute(
            "UPDATE ai_batch_runs SET state='queued', stopped_at=NULL, completed_at=NULL WHERE id=?",
            (batch_id,),
        )
        refreshed = refresh_ai_batch(conn, batch_id)
    return {"ok": True, "state": refreshed["state"] if refreshed else "queued", "retried": len(failed)}


@app.post("/api/materials/{material_id}/ai-analyze")
def queue_ai_analysis(material_id: str) -> dict:
    if not public_ai_status()["configured"]:
        raise HTTPException(409, "请先配置 AI API")
    with db() as conn:
        if not conn.execute("SELECT 1 FROM materials WHERE id=? AND deleted_at IS NULL", (material_id,)).fetchone():
            raise HTTPException(404, "素材不存在")
        active = conn.execute(
            "SELECT 1 FROM jobs WHERE material_id=? AND stage='ai_enrich' AND state IN ('queued','running')", (material_id,)
        ).fetchone()
        if active:
            raise HTTPException(409, "这条素材已经在 AI 整理队列中")
        try:
            batch = create_ai_batch(conn, [material_id], trigger_type="single", scope="single")
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
    return {"ok": True, "batch": batch, "message": "已授权 AI 仅分析这一条素材"}


@app.post("/api/materials/{material_id}/retry")
def retry_failed_jobs(material_id: str) -> dict:
    with db() as conn:
        if not conn.execute("SELECT 1 FROM materials WHERE id=? AND deleted_at IS NULL", (material_id,)).fetchone():
            raise HTTPException(404, "素材不存在")
        dead = conn.execute("SELECT stage FROM jobs WHERE material_id=? AND state='dead'", (material_id,)).fetchall()
        if not dead:
            raise HTTPException(409, "当前没有可重试的失败步骤")
        stages = {row["stage"] for row in dead}
        for stage in stages:
            requeue_job(conn, material_id, stage)
        requeue_job(conn, material_id, "index")
        if "export" in stages:
            conn.execute("UPDATE offline_exports SET state='queued', error=NULL, updated_at=? WHERE material_id=?", (now(), material_id))
        if "thumbnail" in stages:
            conn.execute(
                "UPDATE material_derivatives SET state='queued', error=NULL, updated_at=? WHERE material_id=?",
                (now(), material_id),
            )
        conn.execute("UPDATE materials SET status='queued', status_reason=NULL WHERE id=?", (material_id,))
    return {"ok": True, "retried": sorted(stages), "message": "失败步骤已重新加入队列"}


@app.post("/api/materials/{material_id}/offline/{file_format}")
def request_offline_file(material_id: str, file_format: Literal["pdf", "docx"]) -> dict:
    column = "pdf_path" if file_format == "pdf" else "docx_path"
    with db() as conn:
        row = conn.execute(
            f"""SELECT m.snapshot_path, m.material_type, m.deleted_at, e.{column} AS ready_path,
                       e.requested_formats_json
                FROM materials m LEFT JOIN offline_exports e ON e.material_id=m.id WHERE m.id=?""",
            (material_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "素材不存在")
        if row["deleted_at"] is not None:
            raise HTTPException(409, "请先从回收站恢复素材")
        if row["material_type"] not in {"page", "blog"} or not row["snapshot_path"]:
            raise HTTPException(409, "这条素材没有可用于离线导出的网页快照")
        if row["ready_path"] and Path(row["ready_path"]).is_file():
            return {"ok": True, "state": "ready", "format": file_format}
        requested = json.loads(row["requested_formats_json"] or "[]")
        requested = list(dict.fromkeys([*requested, file_format]))
        conn.execute(
            "UPDATE offline_exports SET requested_formats_json=?, state='queued', error=NULL, updated_at=? WHERE material_id=?",
            (json.dumps(requested), now(), material_id),
        )
        requeue_job(conn, material_id, "export")
        conn.execute("UPDATE materials SET status='analyzing', status_reason=NULL WHERE id=?", (material_id,))
    return {"ok": True, "state": "queued", "format": file_format}


@app.get("/api/materials/{material_id}/offline/{file_format}")
def offline_file(material_id: str, file_format: Literal["pdf", "docx"]) -> FileResponse:
    column = "pdf_path" if file_format == "pdf" else "docx_path"
    with db() as conn:
        row = conn.execute(f"""SELECT e.{column} AS path, m.title FROM offline_exports e
                               JOIN materials m ON m.id=e.material_id WHERE e.material_id=?""", (material_id,)).fetchone()
    if not row or not row["path"]:
        raise HTTPException(404, "离线文件尚未生成")
    path = Path(row["path"]).absolute()
    if not path_is_asset(str(path)) or not path.exists():
        raise HTTPException(404, "离线文件不存在")
    safe_title = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", row["title"])[:80] or "Muse_Vault"
    filename = f"{safe_title}.{file_format}"
    media_type = "application/pdf" if file_format == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return FileResponse(path, media_type=media_type, filename=filename)


@app.get("/api/stats")
def stats() -> dict:
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM materials WHERE deleted_at IS NULL").fetchone()[0]
        trash = conn.execute("SELECT COUNT(*) FROM materials WHERE deleted_at IS NOT NULL").fetchone()[0]
        queued = conn.execute("""SELECT COUNT(*) FROM jobs j JOIN materials m ON m.id=j.material_id
                                 WHERE j.state='queued' AND m.deleted_at IS NULL""").fetchone()[0]
        types = [dict(row) for row in conn.execute("SELECT material_type AS name, COUNT(*) AS value FROM materials WHERE deleted_at IS NULL GROUP BY material_type").fetchall()]
        folder_count = conn.execute("SELECT COUNT(*) FROM folders").fetchone()[0]
    return {"total": total, "trash": trash, "queued": queued, "types": types, "folders": folder_count}


if UI_DIST.is_dir():
    app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="desktop-ui")


def run() -> None:
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=API_PORT, reload=True)


if __name__ == "__main__":
    run()
