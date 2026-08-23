from __future__ import annotations

import ast
import json
from pathlib import Path
import tempfile
import unittest

from launcher import settings_store


REPO_ROOT = Path(__file__).resolve().parents[1]


class SettingsStoreTests(unittest.TestCase):
    def test_legacy_settings_are_merged_into_user_data(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old_launcher = root / "launcher" / "settings"
            old_agent = root / "launcher" / "agent" / "settings"
            old_launcher.mkdir(parents=True)
            old_agent.mkdir(parents=True)
            (old_launcher / "user_config.json").write_text(
                json.dumps({"language": "ko", "last_menu_choice": "8", "future_key": "keep-me"}),
                encoding="utf-8",
            )
            (old_agent / "user_config.json").write_text(
                json.dumps({"logging_enabled": False}),
                encoding="utf-8",
            )

            cfg = settings_store.load(root)

            self.assertEqual(cfg.language, "ko")
            self.assertEqual(cfg.last_menu_choice, "8")
            self.assertFalse(cfg.logging_enabled)
            canonical = root / "user_data" / "settings" / "user_config.json"
            self.assertTrue(canonical.is_file())
            saved = json.loads(canonical.read_text(encoding="utf-8"))
            self.assertEqual(saved["language"], "ko")
            self.assertFalse(saved["logging_enabled"])
            self.assertEqual(saved["future_key"], "keep-me")

            self.assertTrue(settings_store.save(cfg, root))
            saved_again = json.loads(canonical.read_text(encoding="utf-8"))
            self.assertEqual(saved_again["future_key"], "keep-me")

    def test_save_uses_single_canonical_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = settings_store.Settings(language="en", logging_enabled=False)
            self.assertTrue(settings_store.save(cfg, root))
            self.assertEqual(
                settings_store.path(root),
                root / "user_data" / "settings" / "user_config.json",
            )
            loaded = settings_store.load(root)
            self.assertEqual(loaded.language, "en")
            self.assertFalse(loaded.logging_enabled)


class RepositoryStructureTests(unittest.TestCase):
    def _function_count(self, relative: str, name: str) -> int:
        tree = ast.parse((REPO_ROOT / relative).read_text(encoding="utf-8"))
        return sum(
            1 for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        )

    def test_no_shadowed_gui_module(self):
        self.assertFalse((REPO_ROOT / "launcher" / "presenter" / "gui.py").exists())
        self.assertTrue((REPO_ROOT / "launcher" / "presenter" / "gui" / "__init__.py").is_file())

    def test_patch_redefinitions_are_flattened(self):
        self.assertEqual(self._function_count("launcher/app.py", "_build_menu_items"), 1)
        self.assertEqual(self._function_count("installer/steps/python_tools.py", "install_open_webui"), 1)

    def test_documented_batch_entrypoints_exist(self):
        self.assertTrue((REPO_ROOT / "INSTALL.bat").is_file())
        self.assertTrue((REPO_ROOT / "RUN_TUI.bat").is_file())

    def test_legacy_agent_config_is_not_tracked_as_source(self):
        self.assertFalse(
            (REPO_ROOT / "launcher" / "agent" / "settings" / "user_config.json").is_file()
        )


if __name__ == "__main__":
    unittest.main()
