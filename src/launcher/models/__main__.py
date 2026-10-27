# -*- coding: utf-8 -*-
"""모델 목록을 그대로 찍는다.

    set PYTHONPATH=%CD%\\src
    python -m launcher.models              현재 여유 메모리 기준
    python -m launcher.models --plan       기본 설치 세트(상·중 5종)만
    python -m launcher.models --free 12    특정 여유 메모리를 가정

문서에 표를 베껴 두면 카탈로그와 갈라진다. 목록이 필요할 때는 항상 이걸 찍는다.
"""
from __future__ import annotations

import sys

from . import model_catalog as catalog
from . import model_classes as classes


def _plan_lines():
    plan = catalog.plan_by_level()
    total = 0.0
    out = ["메모리 예산 %.0fGB · 적재 상한 %.1fGB — 상·중만 권장 (하 단계는 수동 설치)"
           % (catalog.MEMORY_BUDGET_GB, catalog.MAX_MODEL_GB)]
    for key in catalog.LEVEL_KEYS:
        tags = plan.get(key) or []
        if not tags:
            continue
        gb = catalog.download_gb(tags)
        total += gb
        out.append("")
        out.append("  [%s] 받기 %.1fGB" % (catalog.level_label(key), gb))
        for tag in tags:
            entry = catalog.by_tag()[tag]
            out.append("     %-50s 받기 %5.1f / 적재 %5.1fGB  %s"
                       % (tag, entry.size_gb, entry.memory_gb, entry.note))
    out.append("")
    out.append("  합계 %.1fGB" % total)
    return out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--plan" in argv:
        print("\n".join(_plan_lines()))
        return 0
    free = None
    if "--free" in argv:
        try:
            free = float(argv[argv.index("--free") + 1])
        except (IndexError, ValueError):
            print("--free 뒤에 GB 숫자를 적으세요 (예: --free 12)")
            return 2
    print(classes.format_text(free_gb=free))
    return 0


if __name__ == "__main__":
    sys.exit(main())
