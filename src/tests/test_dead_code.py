"""아무도 닿지 못하는 모듈과 아무도 부르지 않는 이름은 남겨 두지 않는다.

둘 다 컴파일도 테스트도 통과하기 때문에 그냥 쌓인다. 문제는 용량이 아니라
**두 번째 정답**이 생긴다는 점이다. 실제로 이런 것들이 있었다.

  * `core/models/` — `MODEL_INDEX.json` 과 나란히 존재하는 두 번째 모델
    인벤토리 계약. 어느 쪽이 정본인지 코드만 봐서는 알 수 없었다.
  * `services/container/` — DockerService 가 정본이라고 문서에 적어 둔
    바로 그 자리를 감싸는, 아무도 안 쓰는 어댑터.
  * `config.net_proxy_env()` 계열 — network_policy 가 대체한 NET_MODE 기반
    프록시 env 생성기. 누가 실수로 부르면 지금 선택한 네트워크 모드를 무시한
    환경변수가 나간다.

동적 참조(`importlib.import_module("launcher.config")`, `_c("active_socks_proxy")`)
도 사용으로 친다. 문자열까지 훑기 때문이다.
"""
import ast
import unittest
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1]

# 지울 수도, 연결할 수도 없는 이름이 생기면 여기에 이유와 함께 적는다.
# 비워 두는 것이 정상이다 — 채우기 전에 먼저 지우거나 호출부를 만들 것.
KEPT_WITHOUT_CALLERS: dict[str, str] = {}


def _modules():
    return {_name(path): path for path in sorted(SRC_ROOT.rglob("*.py"))}


def _name(path: Path) -> str:
    parts = list(path.relative_to(SRC_ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _absolute(path: Path, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    parts = list(path.relative_to(SRC_ROOT).parent.parts)
    if node.level > 1:
        parts = parts[:len(parts) - (node.level - 1)]
    if node.module:
        parts.append(node.module)
    return ".".join(parts)


def _edges(path: Path, known: set[str]) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _absolute(path, node)
            found.add(base)
            found.update(base + "." + alias.name for alias in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.add(node.value)          # importlib / runpy / self.load('...')
    return found & known


def _parents(module: str, known: set[str]) -> set[str]:
    parts = module.split(".")
    return {".".join(parts[:index]) for index in range(1, len(parts))} & known


class ReachabilityTests(unittest.TestCase):
    def test_every_module_is_reachable_from_an_entrypoint_or_a_test(self):
        modules = _modules()
        known = set(modules)
        graph = {name: _edges(path, known) for name, path in modules.items()}

        roots = {name for name, path in modules.items()
                 if name.startswith("tests") or path.name == "__main__.py"}
        seen, stack = set(), list(roots)
        while stack:
            module = stack.pop()
            if module in seen:
                continue
            seen.add(module)
            stack.extend(graph.get(module, set()) - seen)
            stack.extend(_parents(module, known) - seen)

        unreachable = sorted(
            modules[name].relative_to(SRC_ROOT).as_posix() for name in known - seen)
        self.assertEqual(unreachable, [], "진입점에서도 테스트에서도 닿지 않는 모듈:\n  "
                                          + "\n  ".join(unreachable))


class UnusedDefinitionTests(unittest.TestCase):
    def test_no_top_level_definition_is_left_without_a_single_reference(self):
        texts = {path: path.read_text(encoding="utf-8")
                 for path in sorted(SRC_ROOT.rglob("*.py"))}
        orphans = []
        for path, text in texts.items():
            if path.parent.name == "tests":
                continue          # 테스트 헬퍼는 pytest 가 직접 부른다
            where = path.relative_to(SRC_ROOT).as_posix()
            for node in ast.parse(text).body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                if node.name.startswith("__"):
                    continue
                key = where + ":" + node.name
                if key in KEPT_WITHOUT_CALLERS:
                    continue
                if not _mentioned(node.name, texts, path, node.lineno):
                    orphans.append("%s:%d  %s" % (where, node.lineno, node.name))
        self.assertEqual(orphans, [], "정의만 있고 아무도 부르지 않는다 "
                                      "(지우거나 호출부를 만들 것):\n  " + "\n  ".join(orphans))


def _mentioned(name: str, texts, own_path: Path, own_line: int) -> bool:
    """정의한 줄 하나를 뺀 나머지 어디에든 이름이 나오는가.

    `getattr(cfg, "active_socks_proxy")` 같은 문자열 참조도 사용으로 친다.
    """
    token = name
    for path, text in texts.items():
        for number, line in enumerate(text.splitlines(), 1):
            if path == own_path and number == own_line:
                continue
            index = line.find(token)
            while index != -1:
                before = line[index - 1] if index else " "
                after_index = index + len(token)
                after = line[after_index] if after_index < len(line) else " "
                if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                    return True
                index = line.find(token, index + 1)
    return False


if __name__ == "__main__":
    unittest.main()
