"""새 데스크톱 계층이 '이름' 으로 찾아가는 구 런처 경로는 실제로 존재해야 한다.

`importlib` 으로 만드는 모듈 경로와 `cfg.NAME` 같은 상수 이름은
`compileall` 에도, AST import 검사에도, 가짜 모듈을 주입하는 단위 테스트에도
잡히지 않는다. 그래서 이름이 틀려도 셸은 정상적으로 컴파일되고 가짜 백엔드
테스트는 모두 통과하는데, 사용자가 그 버튼을 처음 누르는 순간
`ModuleNotFoundError` / `AttributeError` 가 난다. 실제로 두 건이 배포됐다.

  * `launcher.actions.settings_action` / `searxng_action`
    — 패키지가 별칭으로 재수출할 뿐 모듈이 아니다.
      Setup 화면 유지보수 버튼 4개 중 2개가 눌리는 즉시 실패했다.
  * `config.MODEL_CONTEXT` + `model_roles.chat_context_window()`
    — 둘 다 존재한 적이 없다. try/except 가 앞을 가리고 fallback 이 터져
      Studio/Chat 에서 Chat 이 아예 시작되지 않았다.

그래서 여기서는 스텁이 아니라 진짜 모듈을 상대로 이름을 확인한다.
"""
import ast
import importlib
import importlib.util
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[1]
ADAPTER = SRC_ROOT / "integrations" / "legacy" / "desktop.py"


def _adapter_tree():
    return ast.parse(ADAPTER.read_text(encoding="utf-8"))


def _module_exists(name: str) -> bool:
    """모듈이 있는지만 본다. Tk 같은 외부 의존성 부재와 구분한다."""
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError as exc:
        # 부모 패키지가 Tk 를 불러오지 못한 것은 '이 모듈이 없다' 와 다르다.
        if exc.name == name:
            return False
        return True


def test_every_maintenance_key_maps_to_a_real_action_module():
    from integrations.legacy.desktop import LegacyBackend
    from services.system.desktop import SetupService

    assert set(LegacyBackend.MAINTENANCE_MODULES) == set(SetupService.MAINTENANCE_KEYS)
    for key, module in LegacyBackend.MAINTENANCE_MODULES.items():
        assert _module_exists(module), f"{key} -> {module} (모듈 없음)"
        assert hasattr(importlib.import_module(module), "run"), module


def test_setup_view_only_offers_allowlisted_maintenance_keys():
    from services.system.desktop import SetupService

    source = (SRC_ROOT / "apps" / "shared" / "views.py").read_text(encoding="utf-8")
    setup_view = next(node for node in ast.parse(source).body
                      if isinstance(node, ast.FunctionDef) and node.name == "setup")
    offered = {
        element.elts[0].value
        for node in ast.walk(setup_view)
        if isinstance(node, ast.List)
        for element in node.elts
        if isinstance(element, ast.Tuple) and element.elts
        and isinstance(element.elts[0], ast.Constant)
        and isinstance(element.elts[0].value, str)
    }
    assert offered, "유지보수 버튼 목록을 찾지 못했다 — 검사 자체가 무의미해진다"
    assert offered <= set(SetupService.MAINTENANCE_KEYS)


def test_adapter_only_binds_cfg_to_the_real_launcher_config():
    """`cfg` 는 이 파일에서 언제나 launcher.config 여야 아래 검사가 성립한다."""
    bindings = [
        node.value
        for node in ast.walk(_adapter_tree())
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "cfg" for t in node.targets)
    ]
    assert bindings
    for value in bindings:
        assert isinstance(value, ast.Call)
        assert [ast.literal_eval(arg) for arg in value.args] == ["launcher.config"]


def test_adapter_reads_only_constants_that_launcher_config_defines():
    config = importlib.import_module("launcher.config")
    names = sorted({
        node.attr
        for node in ast.walk(_adapter_tree())
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name) and node.value.id == "cfg"
    })
    assert names
    missing = [name for name in names if not hasattr(config, name)]
    assert not missing, f"launcher.config 에 없는 이름: {missing}"


RETIRED_CONTEXT_NAMES = {"MODEL_CONTEXT", "chat_context_window"}


def test_chat_context_window_has_exactly_one_live_source():
    """주석은 옛 이름을 설명해도 되지만, 코드가 다시 부르면 안 된다."""
    config = importlib.import_module("launcher.config")
    assert isinstance(config.CHAT_CONTEXT_WINDOW, int)
    stale = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        if path.resolve() == Path(__file__).resolve():
            continue
        where = path.relative_to(SRC_ROOT).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr in RETIRED_CONTEXT_NAMES:
                stale.append(f"{where}:{node.lineno}: .{node.attr}")
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "getattr" and len(node.args) > 1
                    and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value in RETIRED_CONTEXT_NAMES):
                stale.append(f"{where}:{node.lineno}: getattr({node.args[1].value})")
    assert not stale, "존재하지 않는 컨텍스트 이름이 남아 있다:\n  " + "\n  ".join(stale)


@pytest.mark.parametrize("module,name", [
    ("launcher.actions.agent_chat", "_ensure_gui"),
    ("launcher.actions.agent_chat", "_select_setup"),
    ("launcher.actions.agent_chat", "_match_installed_model"),
    ("launcher.actions.agent_chat", "_approval_description"),
    ("launcher.actions.agent_chat", "_open_folder"),
    ("launcher.agent.runtime_coordinator", "prepare_runtime"),
    ("launcher.agent.runtime_coordinator", "RuntimeCoordinator"),
    ("launcher.agent.runtime_config", "resolve_resource_limits"),
    ("launcher.agent.runtime_config", "build_cmd_for_mode"),
    ("launcher.agent.chat_session_controller", "ChatSessionController"),
    ("launcher.anythingllm_runtime", "CONTAINER"),
    ("launcher.anythingllm_runtime", "URL"),
    ("launcher.network_policy", "container_proxy_env"),
    ("launcher.network_policy", "ensure_block_network"),
    ("launcher.presenter.base", "RISK_HIGH"),
    ("launcher.models.model_files", "build_index"),
    ("launcher.models.model_files", "refresh"),
])
def test_named_launcher_entrypoints_used_by_the_desktop_layer_exist(module, name):
    assert hasattr(importlib.import_module(module), name)
