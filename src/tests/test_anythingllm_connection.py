from types import SimpleNamespace


def test_managed_chat_env_updates_model_without_erasing_user_settings(monkeypatch, tmp_path):
    from launcher import anythingllm_runtime as runtime

    env = tmp_path / ".env"
    env.write_text(
        'JWT_SECRET="keep-me"\n'
        'CUSTOM_UI_SETTING="keep-too"\n'
        'LLM_PROVIDER="ollama"\n'
        'OLLAMA_BASE_PATH="http://host.docker.internal:11434"\n'
        'OLLAMA_MODEL_PREF="old:tag"\n'
        'OLLAMA_MODEL_TOKEN_LIMIT="4096"\n'
        'OLLAMA_RESPONSE_TIMEOUT="7200000"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "env_file", lambda: env)

    before = runtime.config_signature("direct")
    assert runtime.sync_managed_llm_env("new:tag", 8192) is True
    after = runtime.config_signature("direct")

    text = env.read_text(encoding="utf-8")
    assert 'JWT_SECRET="keep-me"' in text
    assert 'CUSTOM_UI_SETTING="keep-too"' in text
    assert 'LLM_PROVIDER="ollama"' in text
    assert 'OLLAMA_MODEL_PREF="new:tag"' in text
    assert 'OLLAMA_MODEL_TOKEN_LIMIT="8192"' in text
    assert runtime.configured_model() == "new:tag"
    assert before != after


def test_container_ollama_probe_targets_host_gateway_and_selected_model(monkeypatch):
    from launcher import anythingllm_runtime as runtime

    seen = {}

    def fake_run(args, timeout=60):
        seen["args"] = args
        seen["timeout"] = timeout
        return SimpleNamespace(returncode=0, stdout="ollama-ok:picked:tag\n", stderr="")

    monkeypatch.setattr(runtime, "is_running", lambda: True)
    monkeypatch.setattr(runtime, "_run", fake_run)

    ok, detail = runtime.probe_ollama_connection("picked:tag")

    assert ok is True
    assert "ollama-ok:picked:tag" in detail
    assert seen["args"][:4] == ["docker", "exec", runtime.CONTAINER, "node"]
    script = seen["args"][-1]
    assert "host.docker.internal" in script
    assert "/api/tags" in script
    assert "picked:tag" in script


def test_strong_chat_readiness_requires_ollama_model_probe(monkeypatch):
    from launcher import anythingllm_runtime as runtime

    monkeypatch.setattr(runtime, "is_running", lambda: True)
    monkeypatch.setattr(runtime, "_host_http_ready", lambda: True)
    monkeypatch.setattr(
        runtime, "probe_ollama_connection",
        lambda model_tag=None: (False, "model-missing:expected:tag"),
    )

    assert runtime.is_ready("expected:tag") is False



def test_anythingllm_run_command_exposes_host_ollama_gateway(monkeypatch, tmp_path):
    from launcher import anythingllm_runtime as runtime

    monkeypatch.setattr(runtime, "storage_dir", lambda: tmp_path)
    monkeypatch.setattr(runtime, "write_node_proxy_bootstrap", lambda mode=None: None)
    monkeypatch.setattr(runtime, "proxy_env_for_container", lambda mode=None: {})
    monkeypatch.setattr(runtime, "chromium_args", lambda mode=None: "")
    monkeypatch.setattr(runtime, "node_options", lambda mode=None: "")
    monkeypatch.setattr(runtime, "config_signature", lambda mode=None: "sig")

    command = runtime.build_run_cmd(memory=None, cpus=None)

    idx = command.index("--add-host")
    assert command[idx + 1] == "host.docker.internal:host-gateway"
