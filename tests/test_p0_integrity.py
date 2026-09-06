from __future__ import annotations

import base64
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


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT_ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class P0IntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_root = Path(tempfile.mkdtemp(prefix="muse-vault-p0-"))
        os.environ["MUSE_VAULT_HOME"] = str(cls.temp_root)
        sys.modules.pop("worker", None)
        sys.modules.pop("main", None)
        cls.main = importlib.import_module("main")
        cls.worker = importlib.import_module("worker")
        cls.main.init_db()

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.temp_root, ignore_errors=True)
        os.environ.pop("MUSE_VAULT_HOME", None)

    def setUp(self) -> None:
        with self.main.db() as connection:
            connection.execute("DELETE FROM ai_usage")
            connection.execute("DELETE FROM ai_batch_items")
            connection.execute("DELETE FROM ai_batch_runs")
            connection.execute("DELETE FROM capture_operations")
            connection.execute("DELETE FROM materials_fts")
            connection.execute("DELETE FROM materials")
            self.main.set_processing_settings(connection, dict(self.main.DEFAULT_PROCESSING_SETTINGS))
        for root in (self.main.ASSET_ROOT, self.main.STAGING_ROOT, self.main.RECOVERY_ROOT):
            shutil.rmtree(root, ignore_errors=True)
            root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def png_data_url() -> str:
        payload = base64.b64encode(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
        ).decode("ascii")
        return f"data:image/png;base64,{payload}"

    def test_database_pragmas_are_multi_process_safe(self) -> None:
        with self.main.db() as connection:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertGreaterEqual(connection.execute("PRAGMA busy_timeout").fetchone()[0], 30_000)
            self.assertEqual(connection.execute("PRAGMA synchronous").fetchone()[0], 1)

    def test_page_identity_ignores_title_and_tracking_parameters(self) -> None:
        first = self.main.CaptureRequest(
            source_url="https://example.test/article?id=7&utm_source=one",
            title="标题一",
            material_type="page",
        )
        second = self.main.CaptureRequest(
            source_url="https://example.test/article?utm_source=two&id=7#comments",
            title="完全不同的标题",
            material_type="page",
        )
        third = self.main.CaptureRequest(
            source_url="https://example.test/article?id=8",
            title="标题一",
            material_type="page",
        )
        self.assertEqual(self.main.fingerprint(first), self.main.fingerprint(second))
        self.assertNotEqual(self.main.fingerprint(first), self.main.fingerprint(third))

    def test_retry_endpoint_requeues_dead_stage_and_index(self) -> None:
        result = self.main.capture(self.main.CaptureRequest(
            source_url="https://example.test/retry",
            title="失败重试",
            material_type="page",
        ))
        with self.main.db() as connection:
            connection.execute("UPDATE jobs SET state='done' WHERE material_id=?", (result["id"],))
            connection.execute("UPDATE jobs SET state='dead', last_error='forced' WHERE material_id=? AND stage='classify'", (result["id"],))
            connection.execute("UPDATE materials SET status='partial', status_reason='forced' WHERE id=?", (result["id"],))
        response = self.main.retry_failed_jobs(result["id"])
        self.assertEqual(response["retried"], ["classify"])
        with self.main.db() as connection:
            states = dict(connection.execute("SELECT stage, state FROM jobs WHERE material_id=?", (result["id"],)).fetchall())
            status = connection.execute("SELECT status, status_reason FROM materials WHERE id=?", (result["id"],)).fetchone()
        self.assertEqual(states["classify"], "queued")
        self.assertEqual(states["index"], "queued")
        self.assertEqual((status["status"], status["status_reason"]), ("queued", None))

    def test_image_bytes_deduplicate_across_titles(self) -> None:
        common = {
            "source_url": "https://example.test/gallery",
            "material_type": "image",
            "media_url": "https://cdn.example.test/a.png",
            "data_url": self.png_data_url(),
        }
        first = self.main.capture(self.main.CaptureRequest(title="图片标题一", **common))
        second = self.main.capture(self.main.CaptureRequest(title="图片标题二", **common))
        self.assertFalse(first["deduplicated"])
        self.assertTrue(second["deduplicated"])
        self.assertEqual(first["id"], second["id"])
        with self.main.db() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM materials").fetchone()[0], 1)
            content_hash = connection.execute("SELECT content_hash FROM materials").fetchone()[0]
        self.assertRegex(content_hash, r"^[0-9a-f]{64}$")

    def test_protected_browser_image_can_repair_failed_remote_record(self) -> None:
        media_url = "https://chatgpt.com/backend-api/estuary/content?id=file-protected"
        first = self.main.capture(self.main.CaptureRequest(
            source_url="https://chatgpt.com/c/conversation",
            title="GPT 临时图片",
            material_type="image",
            media_url=media_url,
            thumbnail_url=media_url,
        ))
        content = self.main.decode_data_url(self.png_data_url())[1]
        second = self.main.capture(self.main.CaptureRequest(
            source_url="https://chatgpt.com/c/conversation",
            title="GPT 临时图片（重新拖入）",
            material_type="image",
            media_url=media_url,
            thumbnail_url=media_url,
            data_url=self.png_data_url(),
            browser_session_capture=True,
        ))
        self.assertEqual(second["id"], first["id"])
        with self.main.db() as connection:
            row = connection.execute("SELECT local_path, content_hash, status FROM materials WHERE id=?", (first["id"],)).fetchone()
        self.assertIsNotNone(row["local_path"])
        self.assertTrue(Path(row["local_path"]).is_file())
        self.assertEqual(row["content_hash"], self.main.sha256_bytes(content))
        self.assertEqual(row["status"], "queued")

    def test_video_capture_keeps_playable_url_and_legacy_video_is_readable(self) -> None:
        media_url = "https://video.example.test/clip.mp4?token=temporary"
        result = self.main.capture(self.main.CaptureRequest(
            source_url="https://video.example.test/page",
            title="可检视视频",
            material_type="video",
            media_url=media_url,
            thumbnail_url="https://video.example.test/poster.jpg",
        ))
        with self.main.db() as connection:
            row = connection.execute("SELECT media_url, thumbnail_url FROM materials WHERE id=?", (result["id"],)).fetchone()
        self.assertEqual(row["media_url"], media_url)
        with TestClient(self.main.app) as client:
            response = client.get(f"/api/materials/{result['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["media_url"], media_url)

    def test_local_folder_import_copies_and_deduplicates_images(self) -> None:
        content = self.main.decode_data_url(self.png_data_url())[1]
        with TestClient(self.main.app) as client:
            first_response = client.post(
                "/api/import/images",
                data={"folder_id": "inbox", "relative_paths": "旧图库/第一张.png"},
                files={"files": ("first.png", content, "image/png")},
            )
            second_response = client.post(
                "/api/import/images",
                data={"folder_id": "inbox", "relative_paths": "另一个目录/改名图片.png"},
                files={"files": ("renamed.png", content, "image/png")},
            )
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        first = first_response.json()
        second = second_response.json()
        self.assertEqual((first["imported"], first["failed"]), (1, 0))
        self.assertEqual((second["deduplicated"], second["failed"]), (1, 0))
        with self.main.db() as connection:
            rows = connection.execute("SELECT id, local_path, source_name, content_hash FROM materials").fetchall()
            stages = {row[0] for row in connection.execute("SELECT stage FROM jobs WHERE material_id=?", (rows[0]["id"],))}
        self.assertEqual(len(rows), 1)
        self.assertTrue(Path(rows[0]["local_path"]).is_file())
        self.assertEqual(rows[0]["source_name"], "本机图片库")
        self.assertRegex(rows[0]["content_hash"], r"^[0-9a-f]{64}$")
        self.assertTrue({"classify", "visual", "index"}.issubset(stages))

    def test_ai_modes_never_run_merely_because_provider_is_configured(self) -> None:
        material = self.main.capture(self.main.CaptureRequest(
            source_url="https://example.test/off-mode",
            title="关闭模式素材",
            material_type="page",
        ))
        with self.main.db() as connection:
            stages = {row[0] for row in connection.execute("SELECT stage FROM jobs WHERE material_id=?", (material["id"],))}
        self.assertNotIn("ai_enrich", stages)

        self.main.update_processing_settings(self.main.ProcessingSettingsRequest(ai_mode="manual"))
        with mock.patch.object(self.main, "public_ai_status", return_value={"configured": True, "model": "test-model"}):
            batch = self.main.start_manual_ai_batch(self.main.AIBatchRequest())
        with self.main.db() as connection:
            job = connection.execute("SELECT state, batch_id FROM jobs WHERE material_id=? AND stage='ai_enrich'", (material["id"],)).fetchone()
        self.assertEqual((job["state"], job["batch_id"]), ("queued", batch["id"]))

        self.main.update_processing_settings(self.main.ProcessingSettingsRequest(ai_mode="off"))
        with self.main.db() as connection:
            self.assertEqual(connection.execute("SELECT state FROM jobs WHERE batch_id=? AND stage='ai_enrich'", (batch["id"],)).fetchone()[0], "paused")
            self.assertEqual(connection.execute("SELECT state FROM ai_batch_runs WHERE id=?", (batch["id"],)).fetchone()[0], "paused")

    def test_auto_mode_waits_for_quiet_window_before_batching(self) -> None:
        self.main.update_processing_settings(self.main.ProcessingSettingsRequest(
            ai_mode="auto", auto_idle_minutes=1, include_existing_on_auto=True,
        ))
        material = self.main.capture(self.main.CaptureRequest(
            source_url="https://example.test/auto-mode",
            title="自动模式素材",
            material_type="page",
        ))
        with mock.patch.object(self.main, "public_ai_status", return_value={"configured": True, "model": "test-model"}):
            self.assertIsNone(self.main.schedule_auto_batch())
            with self.main.db() as connection:
                connection.execute("UPDATE materials SET captured_at=? WHERE id=?", (self.main.now() - 120, material["id"]))
            batch = self.main.schedule_auto_batch()
        self.assertIsNotNone(batch)
        self.assertEqual((batch["trigger_type"], batch["total_items"]), ("auto", 1))

    def test_web_exports_default_to_on_demand_and_auto_is_explicit(self) -> None:
        page = self.main.capture(self.main.CaptureRequest(
            source_url="https://example.test/on-demand-export",
            title="按需导出网页",
            material_type="page",
            html_content="<html><body>offline</body></html>",
            text_content="离线正文",
        ))
        with self.main.db() as connection:
            self.assertIsNone(connection.execute("SELECT 1 FROM jobs WHERE material_id=? AND stage='export'", (page["id"],)).fetchone())
        response = self.main.request_offline_file(page["id"], "pdf")
        self.assertEqual(response["state"], "queued")
        with self.main.db() as connection:
            export = connection.execute("SELECT state, requested_formats_json FROM offline_exports WHERE material_id=?", (page["id"],)).fetchone()
            job = connection.execute("SELECT state FROM jobs WHERE material_id=? AND stage='export'", (page["id"],)).fetchone()
        self.assertEqual(export["state"], "queued")
        self.assertEqual(json.loads(export["requested_formats_json"]), ["pdf"])
        self.assertEqual(job["state"], "queued")

    def test_auto_export_requires_at_least_one_format(self) -> None:
        with self.assertRaises(Exception) as raised:
            self.main.update_processing_settings(self.main.ProcessingSettingsRequest(
                ai_mode="off", export_policy="auto", export_formats=[],
            ))
        self.assertEqual(getattr(raised.exception, "status_code", None), 422)
        with self.main.db() as connection:
            settings = self.main.get_processing_settings(connection)
        self.assertEqual(settings["export_policy"], "on_demand")

    def test_file_commit_failure_is_visible_and_leaves_no_orphan(self) -> None:
        request = self.main.CaptureRequest(
            source_url="https://example.test/failure.png",
            title="故意落盘失败",
            material_type="image",
            media_url="https://example.test/failure.png",
            data_url=self.png_data_url(),
        )
        with mock.patch.object(self.main.os, "replace", side_effect=OSError("forced commit failure")):
            with self.assertRaises(Exception):
                self.main.capture(request)
        with self.main.db() as connection:
            material = connection.execute("SELECT status, local_path FROM materials").fetchone()
            operation = connection.execute("SELECT state, error FROM capture_operations").fetchone()
        self.assertIsNotNone(material)
        self.assertEqual(material["status"], "failed")
        self.assertIsNone(material["local_path"])
        self.assertEqual(operation["state"], "failed")
        self.assertIn("forced commit failure", operation["error"])
        unexpected = [path for path in self.main.ASSET_ROOT.rglob("*") if path.is_file()]
        self.assertEqual(unexpected, [])

    def test_second_file_failure_quarantines_partial_page_capture(self) -> None:
        request = self.main.CaptureRequest(
            source_url="https://example.test/partial-page",
            title="双文件落盘失败",
            material_type="page",
            data_url=self.png_data_url(),
            html_content="<html><body>snapshot</body></html>",
        )
        real_replace = self.main.os.replace
        calls = 0

        def fail_snapshot_final(source, target):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise OSError("forced second artifact failure")
            return real_replace(source, target)

        with mock.patch.object(self.main.os, "replace", side_effect=fail_snapshot_final):
            with self.assertRaises(Exception):
                self.main.capture(request)
        report = self.main.scan_integrity(repair=False)
        self.assertEqual(report["orphan_files"], [])
        self.assertEqual(report["orphan_staging"], [])
        self.assertEqual(len(report["recovery_files"]), 1)
        with self.main.db() as connection:
            self.assertEqual(connection.execute("SELECT status FROM materials").fetchone()[0], "failed")

    def test_dead_required_job_can_never_finalize_ready(self) -> None:
        result = self.main.capture(self.main.CaptureRequest(
            source_url="https://example.test/dead-stage",
            title="前置任务失败",
            material_type="page",
        ))
        with self.main.db() as connection:
            connection.execute("UPDATE jobs SET state='done' WHERE material_id=?", (result["id"],))
            connection.execute("UPDATE jobs SET state='dead', last_error='forced' WHERE material_id=? AND stage='classify'", (result["id"],))
            self.worker.finalize_material(connection, result["id"])
            status = connection.execute("SELECT status FROM materials WHERE id=?", (result["id"],)).fetchone()[0]
        self.assertIn(status, {"partial", "failed"})
        self.assertNotEqual(status, "ready")

    def test_integrity_repair_backfills_auxiliary_rows_and_fts(self) -> None:
        result = self.main.capture(self.main.CaptureRequest(
            source_url="https://example.test/repair",
            title="一致性修复",
            material_type="page",
            text_content="蓝色头发的测试正文",
        ))
        with self.main.db() as connection:
            connection.execute("DELETE FROM offline_exports WHERE material_id=?", (result["id"],))
            connection.execute("DELETE FROM visual_features WHERE material_id=?", (result["id"],))
            connection.execute("DELETE FROM materials_fts WHERE material_id=?", (result["id"],))
            connection.execute("INSERT INTO materials_fts(material_id, title, text_content, ai_summary, tags) VALUES ('stale-id', 'stale', '', '', '')")
        report = self.main.scan_integrity(repair=True)
        self.assertGreaterEqual(report["repaired"], 3)
        with self.main.db() as connection:
            self.assertIsNotNone(connection.execute("SELECT 1 FROM offline_exports WHERE material_id=?", (result["id"],)).fetchone())
            self.assertIsNotNone(connection.execute("SELECT 1 FROM visual_features WHERE material_id=?", (result["id"],)).fetchone())
            self.assertIsNotNone(connection.execute("SELECT 1 FROM materials_fts WHERE material_id=?", (result["id"],)).fetchone())
            self.assertIsNone(connection.execute("SELECT 1 FROM materials_fts WHERE material_id='stale-id'").fetchone())

    def test_pending_download_operation_recovers_content_hash_and_completes_download_job(self) -> None:
        result = self.main.capture(self.main.CaptureRequest(
            source_url="https://example.test/download-source",
            title="远程下载中断恢复",
            material_type="image",
            media_url="https://cdn.example.test/download.png",
        ))
        with self.main.db() as connection:
            material = dict(connection.execute("SELECT * FROM materials WHERE id=?", (result["id"],)).fetchone())
        operation = self.worker.claim_download_operation(material)
        content = self.main.decode_data_url(self.png_data_url())[1]
        self.main.write_staged_file(operation["staged"], content)
        final = self.main.ASSET_ROOT / "image" / "inbox" / f"{result['id']}.png"
        with self.main.db() as connection:
            connection.execute("UPDATE capture_operations SET local_final_path=? WHERE id=?", (str(final), operation["id"]))
        self.main.scan_integrity(repair=True)
        with self.main.db() as connection:
            row = connection.execute("SELECT local_path, content_hash FROM materials WHERE id=?", (result["id"],)).fetchone()
            download = connection.execute("SELECT state FROM jobs WHERE material_id=? AND stage='download'", (result["id"],)).fetchone()[0]
        self.assertEqual(Path(row["local_path"]), final)
        self.assertTrue(final.is_file())
        self.assertRegex(row["content_hash"], r"^[0-9a-f]{64}$")
        self.assertEqual(download, "done")

    def test_material_list_paginates_beyond_first_sixty(self) -> None:
        with self.main.db() as connection:
            for index in range(125):
                material_id = f"page-{index:03d}"
                connection.execute(
                    """INSERT INTO materials (id, fingerprint, source_url, canonical_url, title, material_type, captured_at)
                       VALUES (?, ?, ?, ?, ?, 'page', ?)""",
                    (material_id, f"fingerprint-{index:03d}", f"https://example.test/{index}", f"https://example.test/{index}", f"分页素材 {index}", index),
                )
                connection.execute("INSERT INTO visual_features(material_id) VALUES (?)", (material_id,))
        first = self.main.list_materials(None, None, None, None, [], None, None, 60, 0)
        second = self.main.list_materials(None, None, None, None, [], None, None, 60, 60)
        third = self.main.list_materials(None, None, None, None, [], None, None, 60, 120)
        self.assertEqual((len(first["items"]), first["total"], first["has_more"]), (60, 125, True))
        self.assertEqual((len(second["items"]), second["offset"], second["has_more"]), (60, 60, True))
        self.assertEqual((len(third["items"]), third["offset"], third["has_more"]), (5, 120, False))

    def test_recycle_bin_soft_delete_restore_and_fts_visibility(self) -> None:
        result = self.main.capture(self.main.CaptureRequest(
            source_url="https://example.test/recycle-page",
            title="回收站页面",
            material_type="page",
            text_content="回收站搜索测试正文",
        ))
        removed = self.main.delete_material(result["id"])
        self.assertFalse(removed["permanent"])
        library = self.main.list_materials(None, None, None, None, [], None, None, 60, 0)
        trash = self.main.list_materials(None, None, None, None, [], None, None, 60, 0, view="trash")
        self.assertEqual(library["total"], 0)
        self.assertEqual(trash["total"], 1)
        with self.main.db() as connection:
            self.assertIsNone(connection.execute("SELECT 1 FROM materials_fts WHERE material_id=?", (result["id"],)).fetchone())
        restored = self.main.restore_material(result["id"])
        self.assertEqual(restored["requeued_jobs"], 2)
        library = self.main.list_materials(None, None, None, None, [], None, None, 60, 0)
        self.assertEqual(library["total"], 1)
        with self.main.db() as connection:
            self.assertIsNotNone(connection.execute("SELECT 1 FROM materials_fts WHERE material_id=?", (result["id"],)).fetchone())

    def test_recycle_bin_permanent_delete_quarantines_and_removes_file(self) -> None:
        result = self.main.capture(self.main.CaptureRequest(
            source_url="https://example.test/recycle-image",
            title="永久删除验收图片",
            material_type="image",
            data_url=self.png_data_url(),
        ))
        with self.main.db() as connection:
            local_path = Path(connection.execute("SELECT local_path FROM materials WHERE id=?", (result["id"],)).fetchone()[0])
        self.main.delete_material(result["id"])
        deleted = self.main.permanently_delete_material(result["id"])
        self.assertEqual(deleted["removed_files"], 1)
        self.assertFalse(deleted["cleanup_pending"])
        self.assertFalse(local_path.exists())
        with self.main.db() as connection:
            self.assertIsNone(connection.execute("SELECT 1 FROM materials WHERE id=?", (result["id"],)).fetchone())
        self.assertEqual(self.main.scan_integrity(repair=False)["recovery_files"], [])

    def test_chinese_substring_search_supports_short_and_trigram_queries(self) -> None:
        result = self.main.capture(self.main.CaptureRequest(
            source_url="https://example.test/chinese-search",
            title="夜景素材",
            material_type="page",
            text_content="蓝色头发的人像在夜景中。",
        ))
        found = self.main.list_materials("蓝色", None, None, None, [], None, None, 60, 0)
        self.assertEqual(found["total"], 1)
        self.assertEqual(found["items"][0]["id"], result["id"])
        trigram = self.main.list_materials("蓝色头", None, None, None, [], None, None, 60, 0)
        self.assertEqual(trigram["total"], 1)

    def test_search_treats_filename_punctuation_as_literal_text(self) -> None:
        result = self.main.capture(self.main.CaptureRequest(
            source_url="https://example.test/punctuated-filename",
            title="DSC09842-已增强-降噪.psd 1.jpg",
            material_type="page",
        ))
        found = self.main.list_materials("降噪.psd", None, None, None, [], None, None, 60, 0)
        self.assertEqual(found["total"], 1)
        self.assertEqual(found["items"][0]["id"], result["id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
