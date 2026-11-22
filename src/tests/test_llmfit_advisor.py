"""GPU-first recommendation and llmfit read-only contract regression tests."""
from __future__ import annotations

import json
from unittest.mock import Mock

from integrations.llmfit import client
from services.models.advisor import fit_for, projection


def test_llmfit_does_not_infer_ollama_tag_from_hf_model_name():
    rows = client._models([
        {"name": "Qwen/Qwen3-8B", "memory_required_gb": 5.9, "run_mode": "GPU"},
        {"name": "Qwen/Qwen3-8B", "ollama_name": "qwen3:8b",
         "memory_required_gb": 5.9, "run_mode": "GPU",
         "fit_level": "Good", "score": 82},
    ])
    assert list(rows) == ["qwen3:8b"]
    assert rows["qwen3:8b"]["mode"] == "gpu"


def test_llmfit_failure_does_not_override_curated_fallback(monkeypatch):
    client.clear_cache()
    monkeypatch.setattr(client, "executable", lambda: None)
    result = client.analyze(context=4096)
    assert result["available"] is False
    estimate = fit_for("gemma4:12b", 11.0, result)
    assert estimate["source"] == "catalogue"
    assert estimate["need_gib"] == 11.0


def test_llmfit_result_is_json_only_bounded_and_cached(monkeypatch):
    client.clear_cache()
    calls = []
    monkeypatch.setattr(client, "executable", lambda: __import__("pathlib").Path("llmfit"))
    def run(command, **kwargs):
        calls.append(command)
        return Mock(returncode=0, stdout=json.dumps({"models": [{
            "name": "Gemma", "ollama_name": "gemma4:12b",
            "memory_required_gb": 10.2, "run_mode": "GPU",
            "fit_level": "good", "best_quant": "Q4_K_M"
        }]}))
    monkeypatch.setattr(client.subprocess, "run", run)
    first = client.analyze(context=4096, gpu_capacity_gib=14.0)
    second = client.analyze(context=4096, gpu_capacity_gib=14.0)
    assert first is second
    assert first["models"]["gemma4:12b"]["memory_gb"] == 10.2
    assert len(calls) == 1
    assert "--max-context" in calls[0] and "fit" in calls[0]
    assert "--memory=14.00GiB" in calls[0]


def test_real_vram_and_model_estimate_use_separate_100_percent_bars():
    gpu = {"total_gib": 16.0, "free_gib": 12.0}
    estimate = fit_for("sample", 10.0)
    view = projection(gpu, estimate)
    assert view["used_gib"] == 4
    assert view["used_pct"] == 25
    assert view["need_pct"] == 62.5
    assert view["projected_gib"] == 14
    assert view["projected_pct"] == 87.5
    assert view["over_capacity"] is False  # 10GB <= 12 - 1.6 reserve


def test_loaded_same_model_is_not_counted_twice():
    view = projection({"total_gib": 16, "free_gib": 2},
                      fit_for("sample", 10), same_model_loaded=True)
    assert view["projected_gib"] == 14
    assert view["over_capacity"] is False


def test_bar_clamps_overflow_but_keeps_real_number():
    view = projection({"total_gib": 16, "free_gib": 4}, fit_for("sample", 10))
    assert view["projected_gib"] == 22
    assert view["projected_pct"] == 100
    assert view["overflow_gib"] == 6


def test_unknown_gpu_is_not_an_empty_gpu():
    assert projection(None, fit_for("x", 7))["available"] is False


def test_cpu_offload_memory_is_not_claimed_as_gpu_vram():
    analyzed = {"models": {"demo:latest": {
        "memory_gb": 15.0, "mode": "offload", "fit": "good",
        "score": 60, "source": "llmfit",
    }}}
    estimate = fit_for("demo:latest", 12.0, analyzed)
    assert estimate["source"] == "llmfit"
    assert estimate["need_gib"] is None
    assert estimate["total_memory_gib"] == 15.0
    assert projection({"total_gib": 16, "free_gib": 8}, estimate)["need_pct"] is None


def test_llmfit_cannot_undercut_conservative_known_ollama_memory():
    analyzed = {"models": {"model:q8": {
        "memory_gb": 7.0, "mode": "gpu", "fit": "good",
        "source": "llmfit",
    }}}
    estimate = fit_for("model:q8", 11.0, analyzed)
    assert estimate["need_gib"] == 11.0
