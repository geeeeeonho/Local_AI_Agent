from __future__ import annotations

import ast
import json
import os
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

    def test_load_does_not_create_legacy_links_as_a_side_effect(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old_launcher = root / "launcher" / "settings"
            old_agent = root / "launcher" / "agent" / "settings"
            old_launcher.mkdir(parents=True)
            old_agent.mkdir(parents=True)
            (old_launcher / "user_config.json").write_text(
                json.dumps({"language": "ko"}), encoding="utf-8"
            )
            (old_agent / "user_config.json").write_text(
                json.dumps({"logging_enabled": False}), encoding="utf-8"
            )

            settings_store.load(root)

            self.assertTrue(old_launcher.is_dir())
            self.assertTrue(old_agent.is_dir())
            self.assertFalse(old_launcher.is_symlink())
            self.assertFalse(old_agent.is_symlink())

    @unittest.skipIf(os.name == "nt", "symlink creation can require Windows developer mode")
    def test_existing_legacy_link_never_deletes_canonical_settings(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            canonical_dir = root / "user_data" / "settings"
            canonical_dir.mkdir(parents=True)
            canonical = canonical_dir / "user_config.json"
            canonical.write_text(
                json.dumps({"language": "ko", "logging_enabled": False}),
                encoding="utf-8",
            )

            legacy = root / "launcher" / "agent" / "settings"
            legacy.parent.mkdir(parents=True)
            legacy.symlink_to(canonical_dir, target_is_directory=True)

            cfg = settings_store.load(root)

            self.assertTrue(canonical.is_file())
            self.assertEqual(cfg.language, "ko")
            self.assertFalse(cfg.logging_enabled)

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

    def _text(self, relative: str) -> str:
        return (REPO_ROOT / relative).read_text(encoding="utf-8")

    def test_no_shadowed_gui_module(self):
        self.assertFalse((REPO_ROOT / "launcher" / "presenter" / "gui.py").exists())
        self.assertTrue((REPO_ROOT / "launcher" / "presenter" / "gui" / "__init__.py").is_file())

    def test_patch_redefinitions_are_flattened(self):
        self.assertEqual(self._function_count("launcher/app.py", "_build_menu_items"), 1)
        self.assertEqual(self._function_count("installer/steps/python_tools.py", "install_open_webui"), 1)

    def test_documented_batch_entrypoints_exist(self):
        self.assertTrue((REPO_ROOT / "INSTALL.bat").is_file())
        self.assertTrue((REPO_ROOT / "RUN_TUI.bat").is_file())

    def test_batch_entrypoints_use_consistent_python_resolution(self):
        install = self._text("INSTALL.bat")
        run = self._text("RUN.bat")
        run_tui = self._text("RUN_TUI.bat")
        manage = self._text("MANAGE.bat")

        self.assertIn("py -3", install)
        self.assertIn("%*", install)

        managed_python = "llm_environment\\venv\\Scripts\\python.exe"
        self.assertIn(managed_python, run)
        self.assertIn("%*", run)

        self.assertIn(managed_python, run_tui)
        self.assertIn("py -3", run_tui)
        self.assertIn("%*", run_tui)

        self.assertIn(managed_python, manage)
        self.assertIn("py -3", manage)
        self.assertIn("%*", manage)
        self.assertNotIn("DIAG_MODEL_PATH.py", manage)

    def test_agent_package_import_has_no_settings_side_effect(self):
        init_text = self._text("launcher/agent/__init__.py")
        self.assertNotIn("ensure_legacy_bridges", init_text)
        self.assertNotIn("settings_store", init_text)

    def test_launcher_install_guidance_references_real_entrypoint(self):
        launcher_main = self._text("launcher/__main__.py")
        self.assertNotIn("install.py", launcher_main)
        self.assertIn("python -m installer", launcher_main)
        self.assertIn("INSTALL.bat", launcher_main)

    def test_legacy_agent_config_is_not_tracked_as_source(self):
        self.assertFalse(
            (REPO_ROOT / "launcher" / "agent" / "settings" / "user_config.json").is_file()
        )


if __name__ == "__main__":
    unittest.main()
