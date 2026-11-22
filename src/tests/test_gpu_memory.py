"""VRAM estimator is read-only, bounded and never starts a model."""
from types import SimpleNamespace

from core import gpu_memory


def test_nvidia_smi_parser_chooses_best_individual_gpu():
    sample = "16376, 12288\n24576, 10240\ninvalid\n"
    gpu = gpu_memory.parse_nvidia_smi(sample)
    assert gpu is not None
    assert gpu.free_gib == 12.0
    assert 10.0 < gpu.budget_gib < gpu.free_gib


def test_invalid_nvidia_smi_is_not_trusted():
    assert gpu_memory.parse_nvidia_smi("8192, 9999\nnot a number") is None
    assert gpu_memory.parse_nvidia_smi("") is None


def test_gpu_probe_runs_only_nvidia_smi_and_returns_none_on_timeout(monkeypatch):
    import subprocess
    monkeypatch.setattr(gpu_memory.shutil, "which", lambda _name: "/bin/nvidia-smi")
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="16384, 8192\n")

    monkeypatch.setattr(gpu_memory.subprocess, "run", run)
    snapshot = gpu_memory.detect_gpu_memory(timeout=0.4)
    assert snapshot is not None
    assert snapshot.free_gib == 8.0
    assert len(calls) == 1
    assert calls[0][0][1] == "--query-gpu=memory.total,memory.free"
    assert calls[0][1]["timeout"] == 0.4

    def slow(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("nvidia-smi", 0.4)

    monkeypatch.setattr(gpu_memory.subprocess, "run", slow)
    assert gpu_memory.detect_gpu_memory(timeout=0.4) is None


def test_gpu_fit_selects_smaller_installed_candidate_when_idle(monkeypatch):
    from launcher.models import model_roles
    monkeypatch.setitem(model_roles.LADDERS, "__vram_probe__",
                        [("big:test", 12.0), ("small:test", 4.0)])
    assert model_roles.resolve_ladder(
        "__vram_probe__", free_gb=32, installed={"big:test", "small:test"},
        gpu_budget_gb=6.0) == "small:test"
    # Keep original large-model behavior if no GPU candidate fits.
    assert model_roles.resolve_ladder(
        "__vram_probe__", free_gb=32, installed={"big:test"},
        gpu_budget_gb=6.0) == "big:test"
    assert model_roles.resolve_ladder(
        "__vram_probe__", free_gb=32, installed={"big:test", "small:test"},
        gpu_budget_gb=None) == "big:test"


def test_loaded_models_api_rejects_malformed_response():
    import pytest
    from integrations.ollama.client import OllamaClient

    client = object.__new__(OllamaClient)
    client._json = lambda _path: {"models": [{"name": "model"}]}
    assert len(client.loaded_models()) == 1
    client._json = lambda _path: {"models": "bad"}
    with pytest.raises(ValueError):
        client.loaded_models()
