"""저장소 안의 모듈을 가리키는 import 는 실제로 존재하는 모듈이어야 한다.

이 프로젝트는 선택 기능을 `try: from ... import x / except Exception: pass` 로
감싼 곳이 많다. 편리한 대신, 모듈 경로가 틀리면 ImportError 가 그대로 삼켜져
그 기능이 "조용히 없어진" 상태로 몇 달을 간다. 실제로 두 종류가 있었다.

  * launcher.presenter.lifelog / launcher.presenter.agent_lifecycle
    (src 레이아웃 이전 경로) → GUI 를 X 로 닫을 때 정리 훅이 등록되지 않고,
    종료 시 활성 에이전트 일괄 정리가 돌지 않았다.
  * launcher.runtime_guard
    (아예 존재한 적 없는 모듈) → 컨텍스트 길이가 늘 하드코딩 값으로 떨어졌다.

컴파일도 테스트도 통과하므로 AST 로 직접 확인한다.
"""
import ast
import builtins
import symtable
import sys
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1]


def _first_party_roots():
    """src/ 에 실제로 있는 최상위 이름에서 뽑는다.

    손으로 적어 둔 목록은 새 패키지(apps / services / core / integrations)가
    생겼을 때 조용히 낡는다. 정작 검사가 가장 필요한 새 코드가 빠진다.
    """
    roots = set()
    for entry in SRC_ROOT.iterdir():
        if entry.is_dir() and any(entry.rglob("*.py")):
            roots.add(entry.name)
        elif entry.is_file() and entry.suffix == ".py" and entry.stem != "__init__":
            roots.add(entry.stem)
    return roots


FIRST_PARTY_ROOTS = _first_party_roots()

# 모듈 전역으로 읽히지만 어디에도 정의되지 않은 이름을 걸러낼 때, 모듈 수준에
# 대입되지 않아도 항상 존재하는 이름들.
MODULE_DUNDERS = {
    "__file__", "__name__", "__doc__", "__package__", "__spec__",
    "__loader__", "__builtins__", "__debug__", "__path__",
}


def _module_index():
    """src/ 아래에 실제로 존재하는 모듈/패키지 이름 집합."""
    modules, packages = set(), set()
    for path in SRC_ROOT.rglob("*.py"):
        parts = list(path.relative_to(SRC_ROOT).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
            if parts:
                packages.add(".".join(parts))
        if parts:
            modules.add(".".join(parts))
    return modules, packages


def _package_level_names(package: str):
    """패키지 __init__.py 가 최상위에 정의/재수출하는 이름들."""
    init = SRC_ROOT.joinpath(*package.split(".")) / "__init__.py"
    if not init.is_file():
        return set()
    names = set()
    tree = ast.parse(init.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
    return names


def _absolute_module(path: Path, node: ast.ImportFrom) -> str:
    """상대 import 를 src/ 기준 절대 모듈 경로로 편다."""
    if not node.level:
        return node.module or ""
    package_parts = list(path.relative_to(SRC_ROOT).parent.parts)
    if node.level > 1:
        package_parts = package_parts[:len(package_parts) - (node.level - 1)]
    if node.module:
        package_parts.append(node.module)
    return ".".join(package_parts)


class PhantomImportTests(unittest.TestCase):
    def test_no_import_points_at_a_module_that_does_not_exist(self):
        modules, packages = _module_index()
        stdlib = set(sys.stdlib_module_names)
        broken = []

        for path in sorted(SRC_ROOT.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            where = path.relative_to(SRC_ROOT)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    # `import launcher.foo` 도 같은 방식으로 조용히 사라진다.
                    for alias in node.names:
                        root = alias.name.split(".")[0]
                        if (root in FIRST_PARTY_ROOTS and alias.name not in stdlib
                                and alias.name not in modules):
                            broken.append("%s:%d  import %s"
                                          % (where, node.lineno, alias.name))
                    continue
                if not isinstance(node, ast.ImportFrom):
                    continue
                module = _absolute_module(path, node)
                if not module:
                    continue
                root = module.split(".")[0]
                if root not in FIRST_PARTY_ROOTS:
                    continue
                if module in stdlib:
                    continue
                if module not in modules:
                    broken.append("%s:%d  from %s import ..." % (where, node.lineno, module))
                    continue
                if module not in packages:
                    continue  # 모듈에서 꺼내는 이름은 런타임 몫
                exported = _package_level_names(module)
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    if alias.name in exported:
                        continue
                    if module + "." + alias.name in modules:
                        continue
                    broken.append("%s:%d  from %s import %s"
                                  % (where, node.lineno, module, alias.name))

        self.assertEqual(broken, [], "존재하지 않는 모듈을 가리키는 import:\n  "
                                     + "\n  ".join(broken))


class UndefinedNameTests(unittest.TestCase):
    """함수 안에서 읽히는데 어디에도 없는 이름은 그 줄에서 NameError 가 된다.

    컴파일도 import 도 통과하므로, 그 함수가 실제로 불릴 때까지 드러나지
    않는다. 게다가 이 저장소는 선택 기능을 try/except 로 감싸는 자리가 많아
    NameError 가 그대로 삼켜지고 기능만 조용히 사라진다. 실제로
    `installer.steps.model_select_gui.select_models` 가 그랬다 — 설치할 모델을
    고르는 창이 한 번도 뜬 적이 없고, 권장 세트(100GB 이상)가 매번 자동으로
    받아졌다.
    """

    def test_no_function_reads_a_global_that_is_never_defined(self):
        undefined = []
        for path in sorted(SRC_ROOT.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            table = symtable.symtable(source, str(path), "exec")
            module_names = set(table.get_identifiers()) | MODULE_DUNDERS
            where = path.relative_to(SRC_ROOT)

            def visit(scope, trail):
                for symbol in scope.get_symbols():
                    name = symbol.get_name()
                    if (symbol.is_global() and not symbol.is_assigned()
                            and name not in module_names
                            and not hasattr(builtins, name)):
                        undefined.append("%s  %s: %s" % (where, trail, name))
                for child in scope.get_children():
                    visit(child, (trail + "." if trail else "") + child.get_name())

            visit(table, "")

        self.assertEqual(undefined, [], "정의된 적 없는 이름을 읽는다:\n  "
                                        + "\n  ".join(undefined))


class WindowCleanupHookTests(unittest.TestCase):
    """GUI 종료 경로가 붙잡는 정리 함수는 실제로 있어야 한다."""

    def test_lifecycle_helpers_used_by_the_window_exist(self):
        from launcher.agent import agent_lifecycle
        from launcher.core import lifelog

        self.assertTrue(callable(lifelog.log))
        self.assertTrue(callable(lifelog.shutdown_then_exit))
        self.assertTrue(callable(agent_lifecycle.cleanup_all))

    def test_window_imports_the_canonical_paths(self):
        source = (SRC_ROOT / "launcher" / "presenter" / "gui" / "window.py").read_text(
            encoding="utf-8")
        self.assertIn("from launcher.core import lifelog", source)
        self.assertIn("from launcher.agent import agent_lifecycle", source)


if __name__ == "__main__":
    unittest.main()


class DynamicLegacyReferenceTests(unittest.TestCase):
    """Names the transition adapter loads by string must exist for real.

    The adapter reaches the retained launcher through ``importlib`` and plain
    attribute access, so neither compileall nor the AST check above can see the
    reference. Unit tests stub those modules, which is exactly how a renamed or
    missing constant survived to the desktop: ``launcher.config.MODEL_CONTEXT``
    and ``launcher.actions.searxng_action`` never existed outside the stubs.
    """

    def test_maintenance_keys_resolve_to_real_action_modules(self):
        import importlib
        from integrations.legacy.desktop import LegacyBackend
        from services.system.desktop import MAINTENANCE_OPERATIONS

        self.assertEqual(sorted(MAINTENANCE_OPERATIONS),
                         sorted(LegacyBackend.MAINTENANCE_MODULES))
        for key, name in LegacyBackend.MAINTENANCE_MODULES.items():
            module = importlib.import_module(name)
            self.assertTrue(callable(getattr(module, "run", None)),
                            "%s -> launcher.actions.%s has no run()" % (key, name))

    def test_adapter_only_reads_attributes_the_real_modules_expose(self):
        import importlib

        required = {
            "launcher.config": (
                "OLLAMA_PORT", "MODEL_TAG", "SANDBOX_CONTAINER_PREFIX",
                "SEARXNG_IMAGE", "SEARXNG_CONTAINER", "SEARXNG_HOST_PORT",
                "SEARXNG_CONTAINER_PORT", "LLM_NETWORK",
            ),
            "launcher.network_policy": (
                "current_mode", "set_mode", "ensure_block_network",
                "container_proxy_env",
            ),
            "launcher.services.docker": ("DockerService",),
            "launcher.services.ollama": ("OllamaService",),
            "launcher.anythingllm_runtime": (
                "is_running", "image_exists", "start", "URL", "CONTAINER",
            ),
            "launcher.warp_runtime": ("image_exists", "start"),
            "launcher.tor_runtime": ("image_exists", "start"),
            "launcher.presenter.base": ("RISK_HIGH",),
            "launcher.agent.runtime_coordinator": ("prepare_runtime", "RuntimeCoordinator"),
            "launcher.agent.runtime_config": ("resolve_resource_limits", "build_cmd_for_mode"),
            "launcher.agent.chat_session_controller": ("ChatSessionController",),
            "launcher.actions.agent_chat": (
                "_ensure_gui", "_select_setup", "_match_installed_model",
                "_approval_description", "_open_folder",
            ),
        }
        try:
            importlib.import_module("tkinter")
        except ImportError:
            pass  # A Python without Tk cannot answer for the presenter modules.
        else:
            required["launcher.presenter.gui"] = ("TkPresenter",)
            required["launcher.presenter.gui.chat_panel"] = ("ChatPanel",)
        missing = []
        for name, attributes in required.items():
            module = importlib.import_module(name)
            missing.extend("%s.%s" % (name, a) for a in attributes
                           if not hasattr(module, a))
        self.assertEqual(missing, [], "adapter reads names that do not exist:\n  "
                                      + "\n  ".join(missing))
