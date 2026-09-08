from pathlib import Path


def test_protocol_method_names_and_client_identity_are_canonical():
    from launcher.agent import app_server_protocol as protocol

    assert protocol.INITIALIZE == "initialize"
    assert protocol.INITIALIZED == "initialized"
    assert protocol.THREAD_START == "thread/start"
    assert protocol.THREAD_RESUME == "thread/resume"
    assert protocol.TURN_START == "turn/start"
    assert protocol.TURN_INTERRUPT == "turn/interrupt"
    assert protocol.initialize_params() == {
        "clientInfo": {
            "name": "local_ai_agent",
            "title": "Local_AI_Agent",
            "version": "1",
        },
        "capabilities": {"experimentalApi": False},
    }


def test_backend_uses_canonical_protocol_constants_instead_of_method_literals():
    root = Path(__file__).resolve().parents[1] / "launcher" / "agent"
    backend = (root / "interpreter_backend.py").read_text(encoding="utf-8")

    assert "from .app_server_protocol import" in backend
    for literal in (
        '"initialize"',
        '"initialized"',
        '"thread/start"',
        '"thread/resume"',
        '"turn/start"',
        '"turn/interrupt"',
    ):
        assert literal not in backend
