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
import sys
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1]
FIRST_PARTY_ROOTS = {"launcher", "installer", "tools", "tests"}


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
