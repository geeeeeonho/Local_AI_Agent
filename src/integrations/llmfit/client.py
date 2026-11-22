"""Read-only llmfit CLI bridge.

llmfit is a native executable, not an inference runtime.  This module never
downloads models, starts a server or changes Ollama state.  Failure is a
normal capability state: the existing LocalAI catalogue remains authoritative.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time

_CACHE: dict[tuple[int, float | None], tuple[float, dict]] = {}
_LOCK = threading.RLock()
CACHE_SECONDS = 600
MAX_OUTPUT_BYTES = 8 * 1024 * 1024


def executable() -> Path | None:
    """Prefer LocalAI's shared, pinned binary, never a per-user cache."""
    override = os.environ.get("LOCAL_AI_LLMFIT_EXE", "").strip()
    if override:
        chosen = Path(override)
        return chosen if chosen.is_file() else None
    try:
        from project_paths import ENV_DIR
        managed = Path(ENV_DIR) / "llmfit" / ("llmfit.exe" if os.name == "nt" else "llmfit")
        if managed.is_file():
            return managed
    except ImportError:
        pass
    found = shutil.which("llmfit")
    return Path(found) if found else None


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _tag(name):
    return str(name or "").strip().casefold()


def _models(data):
    """Accept current CLI envelope and bare-array JSON without guessing tags."""
    rows = data if isinstance(data, list) else data.get("models", []) if isinstance(data, dict) else []
    if not isinstance(rows, list):
        return {}
    result = {}
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        # HuggingFace family names are NOT interchangeable with Ollama tags.
        tag = _tag(raw.get("ollama_name"))
        if not tag or not isinstance(raw.get("name"), str):
            continue
        memory = _number(raw.get("memory_required_gb"))
        if memory is None or memory <= 0:
            continue
        mode = str(raw.get("run_mode") or "").strip().casefold()
        mode = mode.replace(" ", "").replace("-", "")
        mode = "gpu" if mode == "gpu" else "offload" if any(
            key in mode for key in ("cpu+gpu", "gpu+cpu", "offload", "moe")
        ) else "cpu" if mode == "cpu" else "unknown"
        fit = str(raw.get("fit_level") or "").strip().casefold().replace(" ", "_")
        parsed = {
            "memory_gb": memory,
            "mode": mode,
            "fit": fit,
            "quant": str(raw.get("best_quant") or ""),
            "score": _number(raw.get("score")),
            "tps": _number(raw.get("estimated_tps")),
            "context": _number(raw.get("effective_context_length")),
            "confidence": str(raw.get("estimate_confidence") or ""),
            "source": "llmfit",
        }
        old = result.get(tag)
        if old is None or (parsed["mode"] == "gpu", parsed["score"] or 0) > (
            old["mode"] == "gpu", old["score"] or 0
        ):
            result[tag] = parsed
    return result


def analyze(*, context=8192, gpu_capacity_gib=None, refresh=False, timeout=15.0):
    """Return {available, models, reason}; bounded and cached.

    gpu_capacity_gib overrides GPU capacity only for *installation* planning.
    Omit it for current-load predictions, where llmfit uses free VRAM.
    """
    context = max(512, min(262144, int(context)))
    capacity = _number(gpu_capacity_gib) if gpu_capacity_gib is not None else None
    if capacity is not None and capacity <= 0:
        capacity = None
    key = (context, round(capacity, 2) if capacity is not None else None)
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and not refresh and time.monotonic() - cached[0] < CACHE_SECONDS:
            return cached[1]

        # The catalogue and GPU widget can request the same analysis at once.
        # Keep the inexpensive lookup and bounded CLI call under one reentrant
        # lock, avoiding two parallel native binary processes on a small PC.
        binary = executable()
        if binary is None:
            return {"available": False, "models": {}, "reason": "LLMfit 실행 파일 없음"}
        command = [str(binary), "--max-context", str(context)]
        if capacity is not None:
            command.append("--memory=%.2fGiB" % capacity)
        command.extend(["fit", "--json"])
        options = {
            "capture_output": True, "text": True, "encoding": "utf-8",
            "errors": "replace", "timeout": max(1.0, min(30.0, float(timeout))),
            "check": False,
        }
        if os.name == "nt":
            options["creationflags"] = 0x08000000
        try:
            completed = subprocess.run(command, **options)
            if completed.returncode != 0:
                raise ValueError("LLMfit 종료 코드 %d" % completed.returncode)
            if len(completed.stdout.encode("utf-8")) > MAX_OUTPUT_BYTES:
                raise ValueError("LLMfit 응답 크기 초과")
            models = _models(json.loads(completed.stdout))
            if not models:
                raise ValueError("LLMfit 모델 매핑 결과 없음")
            result = {"available": True, "models": models, "reason": ""}
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError) as exc:
            result = {"available": False, "models": {}, "reason": str(exc)[:200]}
        with _LOCK:
            _CACHE[key] = (time.monotonic(), result)
        return result


def clear_cache():
    with _LOCK:
        _CACHE.clear()
