from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT_ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class AiConfigSaveTests(unittest.TestCase):
    """Saved AI settings must survive a restart even when online validation fails."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_root = Path(tempfile.mkdtemp(prefix="muse-vault-ai-config-"))
        os.environ["MUSE_VAULT_HOME"] = str(cls.temp_root)
        for name in list(sys.modules):
            if name.startswith("ai_adapter"):
                sys.modules.pop(name, None)
        cls.adapter = importlib.import_module("ai_adapter")
        cls.config_path = cls.adapter.CONFIG_PATH

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.temp_root, ignore_errors=True)
        os.environ.pop("MUSE_VAULT_HOME", None)

    def setUp(self) -> None:
        if self.config_path.exists():
            self.config_path.unlink()

    def _read_stored(self) -> dict:
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def test_validation_failure_still_persists_config(self) -> None:
        with mock.patch.object(self.adapter, "validate_ai_config", side_effect=RuntimeError("无法连接接口")):
            status = self.adapter.save_ai_config("https://example.com/v1", "qwen3.7-max", "test-token-placeholder")
        self.assertFalse(status["validated"])
        self.assertIn("无法连接接口", status["validation_warning"])
        stored = self._read_stored()
        self.assertEqual(stored["base_url"], "https://example.com/v1")
        self.assertEqual(stored["model"], "qwen3.7-max")
        self.assertTrue(stored["api_key_encrypted"])
        config = self.adapter.load_ai_config()
        self.assertEqual(config["base_url"], "https://example.com/v1")
        self.assertEqual(config["model"], "qwen3.7-max")
        self.assertEqual(config["api_key"], "test-token-placeholder")

    def test_validation_success_persists_models(self) -> None:
        with mock.patch.object(self.adapter, "validate_ai_config", return_value=["qwen3.7-max", "qwen3-vl-plus"]):
            status = self.adapter.save_ai_config("https://example.com/v1", "qwen3.7-max", "test-token-placeholder")
        self.assertTrue(status["validated"])
        self.assertEqual(status["available_models"], ["qwen3.7-max", "qwen3-vl-plus"])
        stored = self._read_stored()
        self.assertEqual(stored["validated_models"], ["qwen3.7-max", "qwen3-vl-plus"])
        self.assertEqual(stored["base_url"], "https://example.com/v1")

    def test_offline_save_can_be_reloaded_after_restart(self) -> None:
        with mock.patch.object(self.adapter, "validate_ai_config", side_effect=RuntimeError("断网")):
            self.adapter.save_ai_config("https://example.com/v1", "qwen3.7-max", "test-token-placeholder")
        # Simulate an application restart: reload the module against the same
        # data root and confirm the settings come back from disk.
        for name in list(sys.modules):
            if name.startswith("ai_adapter"):
                sys.modules.pop(name, None)
        reloaded = importlib.import_module("ai_adapter")
        config = reloaded.load_ai_config()
        self.assertEqual(config["base_url"], "https://example.com/v1")
        self.assertEqual(config["model"], "qwen3.7-max")
        self.assertEqual(config["api_key"], "test-token-placeholder")

    def test_save_keeps_existing_key_when_blank_supplied(self) -> None:
        with mock.patch.object(self.adapter, "validate_ai_config", return_value=[]):
            self.adapter.save_ai_config("https://example.com/v1", "qwen3.7-max", "existing-token-placeholder")
        with mock.patch.object(self.adapter, "validate_ai_config", return_value=[]):
            status = self.adapter.save_ai_config("https://example.com/v1", "qwen3.8-max", "")
        config = self.adapter.load_ai_config()
        self.assertEqual(config["model"], "qwen3.8-max")
        self.assertEqual(config["api_key"], "existing-token-placeholder")
        self.assertFalse(status.get("api_key_configured", True) is False or not status["api_key_configured"])

    def test_blank_key_without_existing_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.adapter.save_ai_config("https://example.com/v1", "qwen3.7-max", "")

    def test_invalid_url_is_rejected_before_write(self) -> None:
        with self.assertRaises(ValueError):
            self.adapter.save_ai_config("not-a-url", "qwen3.7-max", "test-token-placeholder")
        self.assertFalse(self.config_path.exists())


if __name__ == "__main__":
    unittest.main()
