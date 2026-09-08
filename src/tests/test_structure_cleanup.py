from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import tempfile
import unittest

from launcher import settings_store


REPO_ROOT = next(
    parent for parent in Path(__file__).resolve().parents
    if (parent / ".gitignore").is_file()
)


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
                json.dumps({"logging_enabled": False}), encoding="utf-8"
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

    def test_src_layout_is_the_only_tracked_program_layout(self):
        for name in ("launcher", "installer", "tools", "tests", "docs"):
            self.assertTrue((REPO_ROOT / "src" / name).is_dir(), name)
            self.assertFalse((REPO_ROOT / name).exists(), name)
        self.assertTrue((REPO_ROOT / "user_data").is_dir())

    def test_only_unified_batch_entrypoints_remain(self):
        self.assertTrue((REPO_ROOT / "SETUP.bat").is_file())
        self.assertTrue((REPO_ROOT / "RUN.bat").is_file())
        self.assertFalse((REPO_ROOT / "INSTALL.bat").exists())
        self.assertFalse((REPO_ROOT / "MANAGE.bat").exists())
        self.assertFalse((REPO_ROOT / "RUN_TUI.bat").exists())

    def test_batch_entrypoints_load_src_and_forward_arguments(self):
        setup = self._text("SETUP.bat")
        run = self._text("RUN.bat")

        for text in (setup, run):
            self.assertIn("PYTHONPATH", text)
            self.assertIn("%~dp0src", text)
            self.assertIn("%*", text)

        managed_python = "llm_environment\\venv\\Scripts\\python.exe"
        self.assertIn(managed_python, setup)
        self.assertIn(managed_python, run)
        self.assertIn("-m installer", setup)
        self.assertIn("-m launcher", run)

    def test_project_paths_keep_runtime_data_at_repository_root(self):
        path_module = REPO_ROOT / "src" / "project_paths.py"
        self.assertTrue(path_module.is_file())
        text = path_module.read_text(encoding="utf-8")
        self.assertIn('USER_DATA_DIR = PROJECT_ROOT / "user_data"', text)
        self.assertIn('ENV_DIR = PROJECT_ROOT / "llm_environment"', text)

    def test_no_shadowed_gui_module(self):
        self.assertFalse((REPO_ROOT / "src" / "launcher" / "presenter" / "gui.py").exists())
        self.assertTrue((REPO_ROOT / "src" / "launcher" / "presenter" / "gui" / "__init__.py").is_file())

    def test_patch_redefinitions_are_flattened(self):
        self.assertEqual(self._function_count("src/launcher/app.py", "_build_menu_items"), 1)
        self.assertEqual(self._function_count("src/installer/steps/python_tools.py", "install_open_webui"), 0)

    def test_open_webui_has_no_active_installer_entrypoint(self):
        python_tools = self._text("src/installer/steps/python_tools.py").lower()
        installer_main = self._text("src/installer/__main__.py").lower()
        self.assertNotIn("install_open_webui", python_tools)
        self.assertNotIn("_install_open_webui", python_tools)
        self.assertNotIn("open-webui.exe", python_tools)
        self.assertNotIn("install_open_webui", installer_main)
        self.assertNotIn('components.append("open_webui")', installer_main)
        self.assertIn("install_anythingllm", installer_main)

    def test_open_webui_has_no_active_launcher_switch(self):
        chat = self._text("src/launcher/actions/chat.py").lower()
        app = self._text("src/launcher/app.py").lower()
        self.assertNotIn("local_ai_chat_engine", chat)
        self.assertNotIn("openwebui", chat)
        self.assertNotIn("open webui", chat)
        self.assertNotIn("openwebui", app)
        self.assertNotIn("open webui", app)

    def test_installer_copy_describes_anythingllm_as_the_chat_service(self):
        installer_init = self._text("src/installer/__init__.py")
        i18n = self._text("src/installer/i18n.py")
        self.assertNotIn("Open WebUI", installer_init)
        self.assertNotIn("Open WebUI", i18n)
        self.assertIn("AnythingLLM", installer_init)
        self.assertIn("AnythingLLM", i18n)

    def test_open_webui_identifiers_remain_only_as_explicit_legacy_cleanup(self):
        maint = self._text("src/launcher/core/docker_maint.py")
        self.assertIn("_LEGACY_OPENWEBUI_NAME_PATTERNS", maint)
        self.assertIn("_LEGACY_OPENWEBUI_IMAGE_PATTERNS", maint)
        self.assertNotIn('"llm_openwebui"', maint.split("_LEGACY_OPENWEBUI_NAME_PATTERNS", 1)[0])

    def test_agent_package_import_has_no_settings_side_effect(self):
        init_text = self._text("src/launcher/agent/__init__.py")
        self.assertNotIn("ensure_legacy_bridges", init_text)
        self.assertNotIn("settings_store", init_text)

    def test_launcher_install_guidance_references_setup_entrypoint(self):
        launcher_main = self._text("src/launcher/__main__.py")
        self.assertNotIn("INSTALL.bat", launcher_main)
        self.assertNotIn("MANAGE.bat", launcher_main)
        self.assertIn("SETUP.bat", launcher_main)

    def test_legacy_agent_config_is_not_tracked_as_source(self):
        self.assertFalse(
            (REPO_ROOT / "src" / "launcher" / "agent" / "settings" / "user_config.json").is_file()
        )

    def test_retired_runtime_and_compat_shims_are_gone(self):
        for relative in (
            "src/launcher/agent/agent_runner.py",
            "src/launcher/agent/legacy_backend.py",
            "src/launcher/handlers.py",
            "src/launcher/menu.py",
            "src/launcher/ui.py",
            "src/launcher/actions/agent_sandbox.py",
            "src/launcher/actions/agent_direct.py",
        ):
            self.assertFalse((REPO_ROOT / relative).exists(), relative)

    def test_actions_package_exposes_only_reachable_actions(self):
        from launcher import actions
        from launcher.app import _build_action_map

        exported = {name for name in actions.__all__}
        reachable = set()
        for run in _build_action_map().values():
            reachable.add(run.__module__.rsplit(".", 1)[-1])
        for name in exported:
            module = getattr(actions, name)
            self.assertIn(module.__name__.rsplit(".", 1)[-1], reachable, name)

    def test_settings_store_no_longer_links_into_the_source_tree(self):
        text = self._text("src/launcher/settings_store.py")
        self.assertNotIn("mklink", text)
        self.assertNotIn("ensure_agent_settings_compat", text)
        self.assertNotIn("symlink_to", text)

    def test_ci_compiles_every_module_instead_of_a_hand_listed_subset(self):
        workflow = self._text(".github/workflows/tests.yml")
        self.assertIn("compileall", workflow)
        self.assertNotIn("legacy_backend.py", workflow)

    def test_open_interpreter_transition_modules_are_explicit(self):
        for relative in (
            "src/launcher/agent/execution_policy.py",
            "src/launcher/agent/app_server_protocol.py",
            "src/launcher/agent/setup_flow.py",
            "src/launcher/agent/runtime_config.py",
            "src/launcher/agent/chat_session_controller.py",
        ):
            self.assertTrue((REPO_ROOT / relative).is_file(), relative)

    def test_there_is_one_active_docker_service_class(self):
        definitions = []
        for path in (REPO_ROOT / "src").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == "DockerService":
                    definitions.append(path.relative_to(REPO_ROOT).as_posix())
        self.assertEqual(definitions, ["src/launcher/services/docker.py"])

    def test_open_interpreter_version_has_one_assignment_source(self):
        assignments = []
        for path in (REPO_ROOT / "src").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    if any(isinstance(target, ast.Name) and target.id == "OPEN_INTERPRETER_VERSION" for target in targets):
                        assignments.append(path.relative_to(REPO_ROOT).as_posix())
        self.assertEqual(assignments, ["src/runtime_versions.py"])
        self.assertIn('OPEN_INTERPRETER_VERSION = "0.0.38"', self._text("src/runtime_versions.py"))

    def test_active_chat_panel_does_not_own_legacy_session_files(self):
        panel = self._text("src/launcher/presenter/gui/chat_panel.py")
        self.assertNotIn("session_*.json", panel)
        self.assertNotIn("interpreter_dir(", panel)
        self.assertIn("/resume ", panel)

    def test_readme_documents_final_runtime_and_hard_block_contract(self):
        readme = self._text("README.md")
        self.assertIn("AnythingLLM", readme)
        self.assertIn("Open Interpreter App Server", readme)
        self.assertIn("llm_block_net", readme)
        self.assertIn("verify_block_egress", readme)
        self.assertIn("Host Block", readme)
        self.assertIn("JSONL", readme)

    def test_native_tools_doc_matches_the_current_module_ownership(self):
        doc = self._text("src/docs/open-interpreter-native-tools.md")
        self.assertIn("execution_policy.py", doc)
        self.assertIn("app_server_protocol.py", doc)
        self.assertIn("chat_session_controller.py", doc)
        self.assertIn("llm_block_net", doc)
        self.assertIn("verify_block_egress", doc)
        self.assertNotIn("agent_runner.py", doc)


if __name__ == "__main__":
    unittest.main()
