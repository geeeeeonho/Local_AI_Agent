"""GPU-first model estimates and display math.

Catalog selection is not runtime loading: checking several downloads must not
sum their VRAM. Only the inspected model is projected on the GPU budget.
"""
from __future__ import annotations

import math

DEFAULT_CONTEXT = 4096


def fit_for(tag, fallback_gib, analysis=None):
    rows = (analysis or {}).get("models") or {}
    row = rows.get(str(tag).casefold())
    try:
        fallback = float(fallback_gib)
        if not math.isfinite(fallback) or fallback <= 0:
            fallback = None
    except (TypeError, ValueError):
        fallback = None
    if not row:
        return {
            "need_gib": fallback, "mode": "unknown", "fit": "unknown",
            "source": "catalogue" if fallback is not None else "unknown",
            "tps": None, "quant": "", "context": None,
        }
    # In offload modes memory_required_gb is a combined memory estimate,
    # not a per-GPU VRAM measurement. Do not label it as GPU consumption.
    return {
        "need_gib": row["memory_gb"] if row["mode"] == "gpu" else None,
        "total_memory_gib": row["memory_gb"],
        "mode": row["mode"],
        "fit": row["fit"], "source": "llmfit",
        "tps": row.get("tps"), "quant": row.get("quant", ""),
        "context": row.get("context"),
    }


def projection(gpu, estimate, *, same_model_loaded=False):
    """Return percentages of one GPU, without doubling loaded model weights.

    The used number is a measured GPU figure. Predicted usage is an estimate
    for an *additional* model, not a claim about per-process memory ownership.
    If the selected model is already loaded, its consumption is included in
    measured usage. We cannot subtract it without reliable per-process data.
    """
    if not gpu:
        return {"available": False, "reason": "GPU VRAM 정보를 확인할 수 없음"}
    total = float(gpu["total_gib"])
    free = float(gpu["free_gib"])
    if not (math.isfinite(total) and total > 0 and math.isfinite(free)):
        return {"available": False, "reason": "GPU VRAM 값이 유효하지 않음"}
    free = min(total, max(0.0, free))
    used = total - free
    reserve = max(1.5, total * 0.10)
    need = estimate.get("need_gib")
    need = float(need) if need is not None else None
    if need is not None and (not math.isfinite(need) or need <= 0):
        need = None
    projected = used + (0.0 if same_model_loaded else need or 0.0)
    capacity = max(0.0, free - reserve)
    return {
        "available": True, "total_gib": total, "free_gib": free,
        "used_gib": used, "used_pct": min(100.0, used / total * 100),
        "need_gib": need,
        "need_pct": None if need is None else min(100.0, need / total * 100),
        "projected_gib": projected if need is not None else None,
        "projected_pct": None if need is None else min(100.0, projected / total * 100),
        "over_capacity": None if need is None else (
            False if same_model_loaded else need > capacity
        ),
        "reserve_gib": reserve, "budget_gib": capacity,
        "already_loaded": bool(same_model_loaded),
        "overflow_gib": max(0.0, projected - total),
    }


def preference_key(entry, fit, gpu_budget):
    """Order eligible models: GPU fit, then score; never bypass role eligibility."""
    need = fit.get("need_gib")
    full_gpu = need is not None and need <= gpu_budget and fit.get("mode") != "cpu"
    return (not full_gpu, -(fit.get("tps") or 0), -(entry.get("recommended") or 0))
