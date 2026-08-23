from __future__ import annotations

import base64
from io import BytesIO
import importlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT_ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class SystemAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_root = Path(tempfile.mkdtemp(prefix="muse-vault-system-"))
        os.environ["MUSE_VAULT_HOME"] = str(cls.temp_root)
        sys.modules.pop("worker", None)
        sys.modules.pop("main", None)
        sys.modules.pop("ai_adapter", None)
        cls.main = importlib.import_module("main")
        cls.worker = importlib.import_module("worker")
        cls.ai_adapter = importlib.import_module("ai_adapter")
        cls.main.init_db()
        cls.client_context = TestClient(cls.main.app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_context.__exit__(None, None, None)
        shutil.rmtree(cls.temp_root, ignore_errors=True)
        os.environ.pop("MUSE_VAULT_HOME", None)

    def setUp(self) -> None:
        # The production worker performs restart recovery before it begins its
        # idle loop. Individual unit tests run process_one() directly, so mark
        # that startup phase complete unless a test explicitly targets it.
        self.worker._restart_recovery_done = True
        with self.main.db() as connection:
            connection.execute("DELETE FROM ai_usage")
            connection.execute("DELETE FROM ai_batch_items")
            connection.execute("DELETE FROM ai_batch_runs")
            connection.execute("DELETE FROM capture_operations")
            connection.execute("DELETE FROM materials_fts")
            connection.execute("DELETE FROM materials")
            connection.execute("DELETE FROM folders WHERE id<>'inbox'")
            self.main.set_processing_settings(connection, dict(self.main.DEFAULT_PROCESSING_SETTINGS))
        for root in (self.main.ASSET_ROOT, self.main.STAGING_ROOT, self.main.RECOVERY_ROOT):
            shutil.rmtree(root, ignore_errors=True)
            root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def png_bytes(color: tuple[int, int, int] = (54, 132, 196)) -> bytes:
        buffer = BytesIO()
        Image.new("RGB", (96, 72), color).save(buffer, format="PNG")
        return buffer.getvalue()

    @classmethod
    def data_url(cls, mime: str = "image/png", content: bytes | None = None) -> str:
        payload = content if content is not None else cls.png_bytes()
        return f"data:{mime};base64,{base64.b64encode(payload).decode('ascii')}"

    def capture(self, **overrides) -> dict:
        payload = {
            "source_url": "https://acceptance.example/item",
            "title": "系统验收素材",
            "material_type": "page",
            **overrides,
        }
        response = self.client.post("/api/captures", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def drain_worker(self, maximum: int = 200) -> int:
        processed = 0
        for _ in range(maximum):
            if not self.worker.process_one():
                break
            processed += 1
        self.assertLess(processed, maximum, "Worker did not become idle")
        return processed

    def test_health_paths_metadata_and_integrity_contracts(self) -> None:
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertTrue(health.json()["ok"])

        paths = self.client.get("/api/settings/paths").json()
        self.assertEqual(Path(paths["data_root"]).resolve(), self.temp_root.resolve())
        self.assertTrue(Path(paths["assets"]).is_dir())

        self.assertEqual(self.client.get("/api/materials").json()["total"], 0)
        self.assertEqual(self.client.get("/api/categories").json()["items"], [])
        self.assertEqual(self.client.get("/api/tags").json()["items"], [])
        self.assertEqual(self.client.get("/api/stats").json()["total"], 0)
        self.assertEqual([item["id"] for item in self.client.get("/api/folders").json()["items"]], ["inbox"])

        integrity = self.client.get("/api/integrity").json()
        for key in ("missing_files", "missing_derivatives", "orphan_files", "orphan_staging", "recovery_files", "dead_ready", "missing_auxiliary", "missing_fts", "duplicate_fts", "stale_fts"):
            self.assertEqual(integrity[key], [], key)

    def test_extension_info_and_download_bundle(self) -> None:
        extension_root = self.temp_root / "test-extension"
        extension_root.mkdir(parents=True, exist_ok=True)
        (extension_root / "manifest.json").write_text(
            json.dumps({"name": "myknow Capture", "version": "test"}), encoding="utf-8"
        )
        (extension_root / "popup.html").write_text("<html></html>", encoding="utf-8")
        with mock.patch.object(self.main, "EXTENSION_ROOT", extension_root):
            info = self.client.get("/api/extension/info")
            self.assertEqual(info.status_code, 200)
            self.assertEqual(info.json()["version"], "test")
            response = self.client.get("/api/extension/download")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/zip")
        import zipfile
        with zipfile.ZipFile(BytesIO(response.content)) as archive:
            self.assertEqual(sorted(archive.namelist()), ["myknow-extension/manifest.json", "myknow-extension/popup.html"])

    def test_all_material_types_worker_search_filters_and_asset_download(self) -> None:
        samples = [
            self.capture(
                source_url="https://acceptance.example/page",
                title="蓝色头发研究网页",
                material_type="page",
                text_content="这是一篇关于蓝色头发与摄影构图的中文文章。",
                html_content="<html><body><h1>蓝色头发研究</h1><p>离线正文</p></body></html>",
                data_url=self.data_url(content=self.png_bytes((40, 85, 190))),
            ),
            self.capture(source_url="https://acceptance.example/image", title="粉色花朵图片", material_type="image", media_url="https://acceptance.example/image.png", data_url=self.data_url(content=self.png_bytes((230, 110, 170)))),
            self.capture(source_url="https://acceptance.example/document", title="科学文档", material_type="document", data_url=self.data_url("application/pdf", b"%PDF-1.4 acceptance")),
            self.capture(source_url="https://acceptance.example/presentation", title="项目演示文稿", material_type="presentation", data_url=self.data_url("application/vnd.openxmlformats-officedocument.presentationml.presentation", b"PK acceptance pptx")),
            self.capture(source_url="https://acceptance.example/video", title="教学视频", material_type="video", data_url=self.data_url("video/mp4", b"acceptance mp4"), user_permitted_media=True),
            self.capture(source_url="https://acceptance.example/link", title="普通链接", material_type="link"),
        ]
        self.assertGreaterEqual(self.drain_worker(), 10)

        listing = self.client.get("/api/materials", params={"limit": 20}).json()
        self.assertEqual(listing["total"], 6)
        self.assertFalse(listing["has_more"])
        self.assertEqual(self.client.get("/api/materials", params={"material_type": "image"}).json()["total"], 1)
        self.assertEqual(self.client.get("/api/materials", params={"q": "蓝色"}).json()["total"], 1)
        self.assertEqual(self.client.get("/api/materials", params={"q": "蓝色头发"}).json()["total"], 1)

        for sample in samples:
            detail_response = self.client.get(f"/api/materials/{sample['id']}")
            self.assertEqual(detail_response.status_code, 200)
            self.assertEqual(detail_response.json()["status"], "ready")

        image_asset = self.client.get(f"/api/materials/{samples[1]['id']}/asset")
        self.assertEqual(image_asset.status_code, 200)
        self.assertEqual(image_asset.headers["content-type"], "image/png")
        self.assertEqual(image_asset.content[:8], b"\x89PNG\r\n\x1a\n")
        for sample in samples[:2]:
            detail = self.client.get(f"/api/materials/{sample['id']}").json()
            self.assertEqual(detail["thumbnail_state"], "ready")
            self.assertEqual(detail["thumbnail_asset_url"], f"/api/materials/{sample['id']}/thumbnail")
            thumbnail = self.client.get(detail["thumbnail_asset_url"])
            self.assertEqual(thumbnail.status_code, 200)
            self.assertEqual(thumbnail.headers["content-type"], "image/webp")
            with Image.open(BytesIO(thumbnail.content)) as preview:
                self.assertLessEqual(max(preview.size), self.worker.THUMBNAIL_MAX_EDGE)

        rebuild = self.client.post(f"/api/materials/{samples[1]['id']}/thumbnail/rebuild")
        self.assertEqual(rebuild.status_code, 200, rebuild.text)
        self.assertEqual(rebuild.json()["state"], "queued")
        self.drain_worker()
        self.assertEqual(self.client.get(f"/api/materials/{samples[1]['id']}").json()["thumbnail_state"], "ready")
        video_detail = self.client.get(f"/api/materials/{samples[4]['id']}").json()
        self.assertEqual(video_detail["transcript"]["state"], "waiting_for_local_asr")

    def test_ai_vision_preview_has_pixel_and_byte_limits(self) -> None:
        path = self.temp_root / "large-vision-source.png"
        Image.effect_noise((2800, 1800), 80).convert("RGB").save(path, format="PNG")
        payload = self.ai_adapter.build_vision_preview(path)
        self.assertLessEqual(len(payload), self.ai_adapter.VISION_MAX_BYTES)
        with Image.open(BytesIO(payload)) as preview:
            self.assertEqual(preview.format, "JPEG")
            self.assertLessEqual(max(preview.size), self.ai_adapter.VISION_MAX_EDGE)

    def test_reverse_prompt_protocol_is_bounded_and_precise(self) -> None:
        self.assertIn("prompt_positive", self.ai_adapter.VISION_PROMPT)
        self.assertIn("prompt_negative", self.ai_adapter.VISION_PROMPT)
        self.assertIn("verification_checklist", self.ai_adapter.VISION_PROMPT)
        self.assertIn("ambiguous clothing", self.ai_adapter.VISION_PROMPT)
        self.assertLessEqual(self.ai_adapter.VISION_MAX_TOKENS, 700)

    def test_folder_tag_editing_stacked_filter_and_rejected_ai_tags(self) -> None:
        folder = self.client.post("/api/folders", json={"name": "研究资料"})
        self.assertEqual(folder.status_code, 200)
        folder_id = folder.json()["id"]
        self.assertEqual(self.client.post("/api/folders", json={"name": "研究资料"}).status_code, 409)
        self.assertEqual(self.client.post("/api/folders", json={"name": "子目录", "parent_id": "missing"}).status_code, 400)

        material = self.capture(source_url="https://acceptance.example/tags", title="认证科学资料", material_type="page")
        with self.main.db() as connection:
            connection.execute(
                "UPDATE materials SET tags_json=?, tags_ai_json=? WHERE id=?",
                (json.dumps(["科学", "认证"], ensure_ascii=False), json.dumps(["科学", "认证"], ensure_ascii=False), material["id"]),
            )
        patch = self.client.patch(f"/api/materials/{material['id']}", json={
            "category": "文档", "subcategory": "研究", "tags": ["科学", "自定义"], "folder_id": folder_id,
        })
        self.assertEqual(patch.status_code, 200, patch.text)
        detail = self.client.get(f"/api/materials/{material['id']}").json()
        self.assertEqual(detail["folder_id"], folder_id)
        self.assertEqual(detail["tags"], ["科学", "自定义"])
        self.assertEqual((detail["category"], detail["subcategory"]), ("文档", "研究"))
        clear_subcategory = self.client.patch(f"/api/materials/{material['id']}", json={"category": "文档", "subcategory": None})
        self.assertEqual(clear_subcategory.status_code, 200, clear_subcategory.text)
        detail = self.client.get(f"/api/materials/{material['id']}").json()
        self.assertEqual((detail["category"], detail["subcategory"]), ("文档", None))
        with self.main.db() as connection:
            row = connection.execute("SELECT tags_user_json, tags_rejected_json FROM materials WHERE id=?", (material["id"],)).fetchone()
        self.assertEqual(json.loads(row["tags_user_json"]), ["自定义"])
        self.assertEqual(json.loads(row["tags_rejected_json"]), ["认证"])

        stacked = self.client.get("/api/materials", params=[("tag", "科学"), ("tag", "自定义")]).json()
        self.assertEqual((stacked["total"], stacked["items"][0]["id"]), (1, material["id"]))
        self.assertEqual(self.client.get("/api/materials", params=[("tag", "科学"), ("tag", "不存在")]).json()["total"], 0)
        tag_names = {item["name"] for item in self.client.get("/api/tags").json()["items"]}
        self.assertTrue({"科学", "自定义"}.issubset(tag_names))

    def test_recycle_restore_and_permanent_delete_are_consistent(self) -> None:
        material = self.capture(source_url="https://acceptance.example/trash", title="待删除图片", material_type="image", data_url=self.data_url())
        self.drain_worker()
        local_path = Path(self.client.get(f"/api/materials/{material['id']}").json()["local_path"])
        self.assertTrue(local_path.is_file())

        self.assertEqual(self.client.delete(f"/api/materials/{material['id']}").status_code, 200)
        self.assertEqual(self.client.get("/api/materials").json()["total"], 0)
        self.assertEqual(self.client.get("/api/materials", params={"view": "trash"}).json()["total"], 1)
        self.assertEqual(self.client.patch(f"/api/materials/{material['id']}", json={"tags": ["不允许"]}).status_code, 409)

        restored = self.client.post(f"/api/materials/{material['id']}/restore")
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(self.client.get("/api/materials").json()["total"], 1)
        self.client.delete(f"/api/materials/{material['id']}")
        permanent = self.client.delete(f"/api/materials/{material['id']}", params={"permanent": "true"})
        self.assertEqual(permanent.status_code, 200, permanent.text)
        self.assertFalse(local_path.exists())
        self.assertEqual(self.client.get(f"/api/materials/{material['id']}").status_code, 404)
        self.assertEqual(self.client.get("/api/integrity").json()["orphan_files"], [])

    def test_pdf_and_word_are_generated_on_demand_and_cached(self) -> None:
        page = self.capture(
            source_url="https://acceptance.example/offline",
            title="离线阅读验收",
            material_type="page",
            text_content="第一段中文正文。\n\n第二段用于验证 Word 和 PDF 文件。",
            html_content="<html><body><h1>离线阅读</h1><p>正文</p></body></html>",
        )
        self.drain_worker()
        self.assertEqual(self.client.get(f"/api/materials/{page['id']}").json()["export_state"], "not_requested")
        self.assertEqual(self.client.post(f"/api/materials/{page['id']}/offline/pdf").status_code, 200)
        self.assertEqual(self.client.post(f"/api/materials/{page['id']}/offline/docx").status_code, 200)
        self.drain_worker()

        pdf = self.client.get(f"/api/materials/{page['id']}/offline/pdf")
        docx = self.client.get(f"/api/materials/{page['id']}/offline/docx")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(docx.status_code, 200)
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        self.assertTrue(docx.content.startswith(b"PK"))
        self.assertGreater(len(pdf.content), 1000)
        self.assertGreater(len(docx.content), 1000)
        self.assertEqual(self.client.post(f"/api/materials/{page['id']}/offline/pdf").json()["state"], "ready")

        image = self.capture(source_url="https://acceptance.example/no-export", title="不可导出图片", material_type="image", data_url=self.data_url())
        self.assertEqual(self.client.post(f"/api/materials/{image['id']}/offline/pdf").status_code, 409)

    def test_manual_ai_batch_pause_resume_success_usage_and_no_config_backfill(self) -> None:
        material_ids = [
            self.capture(source_url=f"https://acceptance.example/ai/{index}", title=f"AI 待整理 {index}", material_type="page")["id"]
            for index in range(2)
        ]
        self.drain_worker()
        fake_status = {"configured": True, "base_url": "https://fake.invalid/v1", "model": "acceptance-model", "api_key_configured": True}

        with mock.patch.object(self.main, "save_ai_config", return_value=fake_status):
            configured = self.client.put("/api/ai/config", json={"base_url": "https://fake.invalid/v1", "model": "acceptance-model", "api_key": "test"})
        self.assertEqual(configured.status_code, 200)
        with self.main.db() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM jobs WHERE stage='ai_enrich'").fetchone()[0], 0)

        settings = self.client.put("/api/processing/settings", json={
            "ai_mode": "manual", "auto_idle_minutes": 10, "daily_request_limit": 10,
            "export_policy": "on_demand", "export_formats": ["pdf", "docx"],
        })
        self.assertEqual(settings.status_code, 200)
        with mock.patch.object(self.main, "public_ai_status", return_value=fake_status):
            created = self.client.post("/api/ai/batches", json={"scope": "all_unprocessed"})
            self.assertEqual(created.status_code, 200, created.text)
            batch_id = created.json()["id"]
            self.assertEqual(self.client.post(f"/api/ai/batches/{batch_id}/pause").json()["state"], "paused")
            self.assertEqual(self.client.post(f"/api/ai/batches/{batch_id}/resume").json()["state"], "queued")

            def fake_analysis(material: dict) -> dict:
                return {
                    "summary": f"已整理：{material['title']}", "tags": ["技术", "教育", "过细长标签应被过滤掉"],
                    "entities": ["验收"], "category": "文档", "subcategory": "测试",
                    "visual_description": "模拟视觉描述", "_usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                    "_model": "acceptance-model",
                }

            with mock.patch.object(self.worker, "analyze_material", side_effect=fake_analysis):
                self.drain_worker()

            detail = self.client.get(f"/api/ai/batches/{batch_id}").json()
            self.assertEqual(detail["state"], "completed")
            self.assertEqual({item["state"] for item in detail["items"]}, {"done"})
            status = self.client.get("/api/ai/status").json()
            self.assertEqual(status["usage_today"]["requests"], 2)
            self.assertEqual(status["usage_today"]["total_tokens"], 30)

        for material_id in material_ids:
            detail = self.client.get(f"/api/materials/{material_id}").json()
            self.assertTrue(detail["ai_summary"].startswith("已整理："))
            self.assertLessEqual(len(detail["tags"]), 4)

    def test_ai_failure_becomes_visible_and_daily_limit_blocks_oversized_batch(self) -> None:
        material = self.capture(source_url="https://acceptance.example/ai-failure", title="AI 失败样本", material_type="page")
        self.drain_worker()
        fake_status = {"configured": True, "model": "acceptance-model"}
        self.client.put("/api/processing/settings", json={
            "ai_mode": "manual", "auto_idle_minutes": 10, "daily_request_limit": 10,
            "export_policy": "on_demand", "export_formats": ["pdf", "docx"],
        })
        with mock.patch.object(self.main, "public_ai_status", return_value=fake_status):
            batch = self.client.post("/api/ai/batches", json={"scope": "all_unprocessed"})
            self.assertEqual(batch.status_code, 200)
            batch_id = batch.json()["id"]
            with mock.patch.object(self.worker, "analyze_material", side_effect=RuntimeError("模拟 AI 400 错误")) as analyze:
                self.assertTrue(self.worker.process_one())
                self.assertEqual(analyze.call_count, 1)
                with self.main.db() as connection:
                    remaining = connection.execute(
                        "SELECT COUNT(*) FROM jobs WHERE batch_id=? AND stage='ai_enrich' AND state IN ('queued','running')",
                        (batch_id,),
                    ).fetchone()[0]
                self.assertEqual(remaining, 0, "AI 首次报错后不应继续保留可计费任务")
            detail = self.client.get(f"/api/ai/batches/{batch_id}").json()
        self.assertIn(detail["state"], {"paused", "partial", "failed"})
        self.assertEqual(detail["items"][0]["state"], "failed")
        material_detail = self.client.get(f"/api/materials/{material['id']}").json()
        self.assertIn(material_detail["status"], {"partial", "failed"})
        self.assertIn("模拟 AI 400 错误", next(job["last_error"] for job in material_detail["jobs"] if job["stage"] == "ai_enrich"))

        self.client.put("/api/processing/settings", json={
            "ai_mode": "manual", "auto_idle_minutes": 10, "daily_request_limit": 2,
            "export_policy": "on_demand", "export_formats": ["pdf", "docx"],
        })
        second = self.capture(source_url="https://acceptance.example/ai-limit-2", title="第二条待整理", material_type="page")
        with mock.patch.object(self.main, "public_ai_status", return_value=fake_status):
            blocked = self.client.post("/api/ai/batches", json={"scope": "all_unprocessed", "force": True})
        self.assertEqual(blocked.status_code, 409)
        self.assertIn("超过今天剩余", blocked.json()["detail"])
        self.assertIsNotNone(second["id"])

    def test_extension_manifest_and_privacy_contracts(self) -> None:
        manifest = json.loads((PROJECT_ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["manifest_version"], 3)
        self.assertEqual(manifest["version"], "0.7.2")
        self.assertIn("capture-hovered-asset", manifest["commands"])
        self.assertIn("capture-current-page", manifest["commands"])
        background = (PROJECT_ROOT / "extension" / "background.js").read_text(encoding="utf-8")
        content = (PROJECT_ROOT / "extension" / "content.js").read_text(encoding="utf-8")
        capture_css = (PROJECT_ROOT / "extension" / "capture.css").read_text(encoding="utf-8")
        popup_html = (PROJECT_ROOT / "extension" / "popup.html").read_text(encoding="utf-8")
        popup_js = (PROJECT_ROOT / "extension" / "popup.js").read_text(encoding="utf-8")
        self.assertIn("credentials: 'omit'", background)
        self.assertNotIn("credentials: 'include'", background)
        self.assertIn("capture-hovered-asset", background)
        self.assertIn("capture-current-page", background)
        self.assertIn("muse-capture-active-page", background)
        self.assertIn("muse-capture-active-page", content)
        self.assertIn("ensureQuickCapture()", content)
        self.assertIn("muse-set-quick-capture-visible", content)
        self.assertIn("muse-get-quick-capture-visibility", background)
        self.assertIn("#muse-quick-capture", capture_css)
        self.assertIn(".muse-quick-dismiss", capture_css)
        self.assertIn("position: fixed", capture_css)
        self.assertIn('id="quick-capture-enabled"', popup_html)
        self.assertIn("muse-set-quick-capture-visible", popup_js)

    def test_local_api_rejects_untrusted_browser_origins(self) -> None:
        before = self.client.get("/api/stats").json()["total"]
        denied = self.client.post(
            "/api/captures",
            headers={"Origin": "https://malicious.example"},
            json={"source_url": "https://malicious.example/item", "title": "不应写入", "material_type": "page"},
        )
        self.assertEqual(denied.status_code, 403, denied.text)
        self.assertEqual(self.client.get("/api/stats").json()["total"], before)

        cross_site = self.client.get("/api/materials", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(cross_site.status_code, 403)

        extension_origin = "chrome-extension://" + "a" * 32
        trusted = self.client.post("/api/captures", headers={"Origin": extension_origin}, json={})
        self.assertEqual(trusted.status_code, 422, trusted.text)

        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertNotIn("database", health.json())
        self.assertNotIn("asset_root", health.json())
        self.assertEqual(health.headers.get("x-content-type-options"), "nosniff")

    def test_ai_config_change_does_not_forward_saved_key(self) -> None:
        current = {
            "base_url": "https://gateway.example/v1",
            "model": "old-model",
            "api_key_encrypted": "encrypted-placeholder",
            "validated_models": ["old-model"],
        }
        with mock.patch.object(self.ai_adapter, "_stored_config", return_value=current), \
             mock.patch.object(self.ai_adapter, "_unprotect", return_value="saved-key-for-test"), \
             mock.patch.object(self.ai_adapter, "validate_ai_config", return_value=["new-model"]) as validate:
            self.ai_adapter.save_ai_config("https://gateway.example/v1", "new-model", None)
            validate.assert_called_once_with("https://gateway.example/v1", "new-model", "saved-key-for-test")

        with mock.patch.object(self.ai_adapter, "_stored_config", return_value=current):
            with self.assertRaisesRegex(ValueError, "重新输入"):
                self.ai_adapter.save_ai_config("https://another.example/v1", "new-model", None)

        with self.assertRaisesRegex(ValueError, "必须使用 https"):
            self.ai_adapter.validate_ai_config("http://gateway.example/v1", "model", "key")

        redacted = self.ai_adapter.redact_sensitive_text("Authorization: Bearer secret-value-123 api_key=hidden-value")
        self.assertNotIn("secret-value-123", redacted)
        self.assertNotIn("hidden-value", redacted)


if __name__ == "__main__":
    unittest.main(verbosity=2)
