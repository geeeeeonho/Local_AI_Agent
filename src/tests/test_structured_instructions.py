from launcher.agent import profiles
from launcher.agent.instructions import build_structured_instructions


def test_host_structured_instructions_keep_privacy_without_docker_claim():
    text = build_structured_instructions("You are a coding agent.", sandbox=False)
    assert text.startswith("You are a coding agent.")
    assert "개인정보 보호" in text
    assert "API 키" in text
    assert "외부 서비스" in text
    assert "Docker sandbox" not in text
    assert "PreTool" not in text


def test_sandbox_structured_instructions_use_native_oi_and_mcp_search_guidance():
    text = build_structured_instructions("You are a coding agent.", sandbox=True)
    assert "개인정보 보호" in text
    assert "Local_AI_Agent Docker sandbox" in text
    assert "Do not attempt to escape the container" in text
    assert "Open Interpreter built-in web search is disabled" in text
    assert "local_search" in text
    assert "MCP" in text
    assert "SearXNG" in text
    assert "private local content" in text
    assert "PreTool" not in text


def test_active_profiles_do_not_reference_pretool():
    assert profiles.PROFILES
    assert all("PreTool" not in profile.system_message for profile in profiles.PROFILES)


def test_instructions_forbid_answering_current_questions_from_memory():
    for sandbox in (True, False):
        text = build_structured_instructions("You are a coding agent.", sandbox=sandbox)
        assert "사실 근거" in text
        assert "추측하지 마십시오" in text
        assert "출처 URL" in text
        assert "만들어내지 마십시오" in text


def test_instructions_require_reporting_tool_failure_instead_of_guessing():
    text = build_structured_instructions("agent", sandbox=True)
    assert "실패했다는 사실을 그대로 보고" in text
    assert "확실하지 않다고 밝히고" in text


def test_host_instructions_state_the_missing_isolation():
    host = build_structured_instructions("agent", sandbox=False)
    assert "컨테이너 격리 없이" in host
    assert "Docker sandbox" not in host

    sandbox = build_structured_instructions("agent", sandbox=True)
    assert "Local_AI_Agent Docker sandbox" in sandbox
    assert "호스트 직접 실행" not in sandbox


def test_privacy_clause_is_defined_once(tmp_path):
    """Two copies of a safety clause drift. There must be exactly one."""
    import ast
    from pathlib import Path

    src_root = Path(__file__).resolve().parents[1]
    from launcher.agent.instructions import PRIVACY_CLAUSE

    marker = "[개인정보 보호"
    definitions = []
    for path in src_root.rglob("*.py"):
        if "__pycache__" in path.parts or path.name == "test_structured_instructions.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if marker in node.value:
                    definitions.append(f"{path}:{node.lineno}")
    assert len(definitions) == 1, definitions
    assert marker in PRIVACY_CLAUSE


def test_host_session_addendum_carries_the_deny_list(monkeypatch):
    """folder_policy documents the deny-list as the host-mode guard.

    Host mode previously received no addendum at all, so nothing enforced it.
    """
    from launcher.agent import folder_policy

    monkeypatch.setattr(folder_policy, "list_allowed", lambda: ["C:/work/project"])
    monkeypatch.setattr(folder_policy, "list_denied", lambda: ["C:/Users/me/Documents"])

    text = profiles.build_host_session_addendum("C:/work/project")

    assert "작업 폴더: C:/work/project" in text
    assert "컨테이너 격리가 없습니다" in text
    assert "C:/Users/me/Documents" in text
    assert "접근 금지 폴더" in text
    assert "수행하지 말고" in text


def test_sandbox_session_addendum_also_states_denied_paths(monkeypatch):
    from launcher.agent import folder_policy

    monkeypatch.setattr(folder_policy, "mounts_for", lambda: [("C:/work", "/home/agent/allowed/work")])
    monkeypatch.setattr(folder_policy, "list_denied", lambda: ["C:/work/secrets"])

    text = profiles.build_session_addendum("C:/work")

    assert "/home/agent/allowed/work" in text
    assert "C:/work/secrets" in text


def test_addendums_are_empty_without_a_policy(monkeypatch):
    from launcher.agent import folder_policy

    monkeypatch.setattr(folder_policy, "mounts_for", lambda: [])
    monkeypatch.setattr(folder_policy, "list_allowed", lambda: [])
    monkeypatch.setattr(folder_policy, "list_denied", lambda: [])

    assert profiles.build_session_addendum() == ""
    assert profiles.build_host_session_addendum() == ""


def test_host_backend_applies_addendum_and_permission_profile(tmp_path, monkeypatch):
    from launcher.agent import folder_policy
    from launcher.agent.backend import AgentConfig
    from launcher.agent.native_backend import NativeOpenInterpreterBackend

    monkeypatch.setattr(folder_policy, "list_allowed", lambda: [])
    monkeypatch.setattr(folder_policy, "list_denied", lambda: ["C:/private"])

    backend = NativeOpenInterpreterBackend(client_factory=lambda *args: None)
    config = AgentConfig(
        workspace=tmp_path,
        mode="host",
        model="m",
        network_mode="direct",
        profile_name="universal",
        instructions="profile text",
    )
    params = backend._thread_params(config)
    instructions = params["developerInstructions"]

    assert "profile text" in instructions
    assert "C:/private" in instructions
    assert str(tmp_path) in instructions
    assert "sandbox" not in params
    assert params["config"]["default_permissions"] == "local-ai-host"
