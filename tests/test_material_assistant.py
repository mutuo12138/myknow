from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT_ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class MaterialAssistantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_root = Path(tempfile.mkdtemp(prefix="muse-vault-assistant-"))
        os.environ["MUSE_VAULT_HOME"] = str(cls.temp_root)
        for module in ("worker", "main", "ai_adapter"):
            sys.modules.pop(module, None)
        cls.main = importlib.import_module("main")
        cls.main.init_db()
        cls.client_context = TestClient(cls.main.app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client_context.__exit__(None, None, None)
        shutil.rmtree(cls.temp_root, ignore_errors=True)
        os.environ.pop("MUSE_VAULT_HOME", None)

    def setUp(self) -> None:
        with self.main.db() as connection:
            connection.execute("DELETE FROM assistant_action_logs")
            connection.execute("DELETE FROM assistant_action_plans")
            connection.execute("DELETE FROM materials_fts")
            connection.execute("DELETE FROM materials")
            connection.execute("DELETE FROM folders WHERE id<>'inbox'")
            self.main.set_processing_settings(connection, dict(self.main.DEFAULT_PROCESSING_SETTINGS))
            self.blue_id = self.seed_material(
                connection,
                title="阴天人物参考",
                color=(48, 88, 136),
                description="人物站在阴沉的蓝灰色天空前，背景开阔。",
                brightness=0.34,
            )
            self.red_id = self.seed_material(
                connection,
                title="暖色室内静物",
                color=(188, 76, 42),
                description="暖色灯光下的室内静物，木质桌面清晰。",
                brightness=0.61,
            )
            self.gray_id = self.seed_material(
                connection,
                title="灰调建筑参考",
                color=(112, 112, 112),
                description="整体采用灰色调，水泥建筑与阴天天空形成统一的中灰画面。",
                brightness=0.46,
            )
            self.green_id = self.seed_material(
                connection,
                title="绿色森林与黄色长裙",
                color=(48, 136, 64),
                description="绿色森林里的人物穿着黄色长裙，画面清新明亮。",
                brightness=0.52,
                palette=[
                    {"rgb": (48, 136, 64), "ratio": 0.62},
                    {"rgb": (208, 168, 48), "ratio": 0.19},
                    {"rgb": (32, 32, 32), "ratio": 0.11},
                ],
            )
            self.dark_id = self.seed_material(
                connection,
                title="暗光楼梯人像",
                color=(32, 32, 32),
                description="昏暗楼梯间中的人物，整体色调偏暗，局部有暖色肤色高光。",
                brightness=0.22,
                palette=[
                    {"rgb": (32, 32, 32), "ratio": 0.57},
                    {"rgb": (64, 64, 64), "ratio": 0.08},
                    {"rgb": (96, 64, 48), "ratio": 0.14},
                ],
            )
            self.blue_gray_id = self.seed_material(
                connection,
                title="阴天荒野小提琴手",
                color=(64, 96, 96),
                description="背景是阴沉的蓝灰色天空，整体以深蓝、灰黑为主，色调清冷。",
                brightness=0.31,
                palette=[
                    {"rgb": (32, 32, 32), "ratio": 0.25},
                    {"rgb": (64, 96, 96), "ratio": 0.24},
                    {"rgb": (64, 64, 96), "ratio": 0.16},
                ],
            )
            self.blue_dress_id = self.seed_material(
                connection,
                title="蓝裙白墙人像",
                color=(232, 232, 232),
                description="人物身穿蓝色裙子，背景是干净的白色墙壁。",
                brightness=0.72,
                palette=[{"rgb": (232, 232, 232), "ratio": 0.64}, {"rgb": (48, 96, 176), "ratio": 0.10}],
            )
            self.blue_background_id = self.seed_material(
                connection,
                title="蓝天背景人像",
                color=(232, 216, 196),
                description="人物站在户外，背景是明亮的蓝色天空。",
                brightness=0.68,
                palette=[{"rgb": (232, 216, 196), "ratio": 0.61}, {"rgb": (48, 112, 192), "ratio": 0.10}],
            )

    def seed_material(self, connection, *, title: str, color: tuple[int, int, int], description: str, brightness: float, palette: list[dict] | None = None) -> str:
        material_id = str(uuid.uuid4())
        connection.execute(
            """INSERT INTO materials
               (id, fingerprint, source_url, canonical_url, title, material_type, source_name,
                captured_at, status, category, tags_json, tags_user_json, tags_ai_json,
                tags_rejected_json, entities_json, user_permitted_media, folder_id)
               VALUES (?, ?, ?, ?, ?, 'image', '测试库', ?, 'ready', '图片', '[]', '[]', '[]', '[]', '[]', 0, 'inbox')""",
            (material_id, f"fingerprint-{material_id}", f"https://example.test/{material_id}", f"https://example.test/{material_id}", title, self.main.now()),
        )
        connection.execute(
            "INSERT INTO visual_features (material_id, palette_json, mean_brightness, visual_description) VALUES (?, ?, ?, ?)",
            (material_id, json.dumps(palette or [{"rgb": color, "ratio": 0.82}]), brightness, description),
        )
        self.main.update_fts_row(connection, material_id)
        return material_id

    def test_natural_language_search_uses_color_and_visual_description_without_ai(self) -> None:
        response = self.client.post("/api/assistant/query", json={
            "query": "蓝色的背景图片",
            "limit": 20,
            "use_ai": False,
        })
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertFalse(data["used_ai"])
        self.assertFalse(data["deletion_access"])
        ids = [item["id"] for item in data["items"]]
        self.assertIn(self.blue_id, ids)
        self.assertIn(self.blue_background_id, ids)
        self.assertNotIn(self.blue_dress_id, ids, "blue clothing must not satisfy a blue-background relation")
        self.assertTrue(all(any("背景" in reason for reason in item["assistant_reasons"]) for item in data["items"]))

    def test_exact_gray_requires_meaningful_gray_coverage(self) -> None:
        response = self.client.post("/api/assistant/query", json={
            "query": "灰色",
            "limit": 20,
            "use_ai": False,
        })
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        ids = [item["id"] for item in data["items"]]
        self.assertEqual(data["understanding"], "灰色")
        self.assertIn(self.gray_id, ids)
        self.assertIn(self.blue_gray_id, ids, "a clearly described blue-gray treatment should still count as gray")
        self.assertNotIn(self.green_id, ids, "a small dark shadow must not make a green image gray")
        self.assertNotIn(self.dark_id, ids, "a predominantly dark image is black/dark, not automatically gray")
        gray = next(item for item in data["items"] if item["id"] == self.gray_id)
        self.assertGreaterEqual(gray["assistant_color_confidence"], 0.7)
        self.assertTrue(any("灰色约占" in reason for reason in gray["assistant_reasons"]))
        self.assertEqual(self.main.assistant_color_similarity((0, 32, 0), "gray"), 0.0)

    def test_batch_tag_change_requires_preview_confirmation_and_can_be_undone(self) -> None:
        preview = self.client.post("/api/assistant/plans", json={
            "action": "add_tags",
            "material_ids": [self.blue_id, self.red_id],
            "tags": ["灵感"],
        })
        self.assertEqual(preview.status_code, 200, preview.text)
        plan = preview.json()
        with self.main.db() as connection:
            before = connection.execute("SELECT tags_json FROM materials WHERE id=?", (self.blue_id,)).fetchone()[0]
        self.assertEqual(json.loads(before), [], "preview must not write")

        denied = self.client.post(f"/api/assistant/plans/{plan['id']}/confirm", json={"confirmation_token": "x" * 24})
        self.assertEqual(denied.status_code, 403)

        confirmed = self.client.post(f"/api/assistant/plans/{plan['id']}/confirm", json={
            "confirmation_token": plan["confirmation_token"],
        })
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()["changed"], 2)
        with self.main.db() as connection:
            after = json.loads(connection.execute("SELECT tags_json FROM materials WHERE id=?", (self.blue_id,)).fetchone()[0])
            log_count = connection.execute("SELECT COUNT(*) FROM assistant_action_logs WHERE plan_id=?", (plan["id"],)).fetchone()[0]
        self.assertEqual(after, ["灵感"])
        self.assertEqual(log_count, 2)

        undone = self.client.post(f"/api/assistant/plans/{plan['id']}/undo")
        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertEqual(undone.json()["restored"], 2)
        with self.main.db() as connection:
            restored = json.loads(connection.execute("SELECT tags_json FROM materials WHERE id=?", (self.blue_id,)).fetchone()[0])
        self.assertEqual(restored, [])

    def test_move_plan_does_not_overwrite_a_later_manual_change_during_undo(self) -> None:
        with self.main.db() as connection:
            connection.execute("INSERT INTO folders (id, name, parent_id, created_at) VALUES ('ideas', '灵感', NULL, ?)", (self.main.now(),))
            connection.execute("INSERT INTO folders (id, name, parent_id, created_at) VALUES ('manual', '手动整理', NULL, ?)", (self.main.now(),))
        plan = self.client.post("/api/assistant/plans", json={
            "action": "move_folder", "material_ids": [self.blue_id], "folder_id": "ideas",
        }).json()
        confirmed = self.client.post(f"/api/assistant/plans/{plan['id']}/confirm", json={"confirmation_token": plan["confirmation_token"]})
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        with self.main.db() as connection:
            connection.execute("UPDATE materials SET folder_id='manual' WHERE id=?", (self.blue_id,))
        undone = self.client.post(f"/api/assistant/plans/{plan['id']}/undo")
        self.assertEqual(undone.status_code, 200, undone.text)
        self.assertEqual(undone.json()["skipped"], 1)
        with self.main.db() as connection:
            folder_id = connection.execute("SELECT folder_id FROM materials WHERE id=?", (self.blue_id,)).fetchone()[0]
        self.assertEqual(folder_id, "manual")


if __name__ == "__main__":
    unittest.main()
