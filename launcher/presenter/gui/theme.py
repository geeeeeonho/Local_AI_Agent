"""theme — GUI 색상 / 폰트 / 위험도 정책.

단일 진실의 원천. 색조 변경은 이 파일만 고치면 됨.
색조: VS Code 스타일 다크 테마 (블루 회색, 베이지 톤 X).
"""
from __future__ import annotations

from ..base import RISK_HIGH, RISK_MEDIUM


# ─────────────────────────────────────────────
#  색상 — VS Code Dark Modern 기반
# ─────────────────────────────────────────────
class Theme:
    # 배경 계조 (어두운 -> 밝은)
    BG          = "#1e1e1e"   # 메인 배경
    BG_ALT      = "#252526"   # 사이드바 / 패널
    BG_INPUT    = "#3c3c3c"   # 입력란
    BG_HOVER    = "#2a2d2e"   # 호버 (사이드바 항목)
    BG_SELECTED = "#37373d"   # 선택된 항목
    # v7_3_panel: chat_panel.py 가 참조하는 패널 배경 (BG_ALT 별칭)
    PANEL       = "#252526"   # 패널 배경 (= BG_ALT)
    BG_TOOLTIP  = "#252526"   # 툴팁

    # 테두리
    BORDER      = "#3c3c3c"
    BORDER_FOCUS = "#0e639c"

    # 전경 (텍스트)
    FG          = "#cccccc"   # 본문
    FG_DIM      = "#858585"   # 보조
    FG_BRIGHT   = "#ffffff"   # 강조

    # 액센트 (한 가지 색상만 사용 — VS Code 표준)
    ACCENT      = "#0e639c"   # 버튼 / 강조 (파랑)
    ACCENT_HOVER = "#1177bb"

    # 의미 색상
    OK          = "#73c991"   # 성공 (초록)
    INFO        = "#3794ff"   # 정보 (밝은 파랑)
    DANGER      = "#f48771"   # 위험 (코랄/주황빨강 — 노란색 X)
    DIM         = "#6e6e6e"

    # 사이드바 active 표시 (좌측 보더)
    SIDEBAR_ACTIVE_BORDER = "#0098ff"

    # ─── 폰트 ───
    F_BASE   = ("Segoe UI", 10)
    F_BOLD   = ("Segoe UI", 10, "bold")
    F_SMALL  = ("Segoe UI", 9)
    F_TINY   = ("Segoe UI", 8)
    F_TITLE  = ("Segoe UI", 16, "bold")
    F_SUB    = ("Segoe UI", 11)
    F_MENU   = ("Segoe UI", 10)
    F_MONO   = ("Consolas", 10)


# ─────────────────────────────────────────────
#  위험옵션 키워드 (정책)
# ─────────────────────────────────────────────
RISK_KEYWORDS = {
    RISK_HIGH: "I-UNDERSTAND",
    RISK_MEDIUM: "ENABLE",
}


def risk_color(risk: int) -> str:
    """위험도별 색상."""
    if risk == RISK_HIGH:
        return Theme.DANGER
    if risk == RISK_MEDIUM:
        return Theme.FG_DIM   # 노란색 대신 회색 (사용자 요구)
    return Theme.OK


def risk_label(risk: int) -> str:
    if risk == RISK_HIGH:
        return "위험"
    if risk == RISK_MEDIUM:
        return "주의"
    return "안전"


def risk_icon(risk: int) -> str:
    """텍스트 아이콘 (Tk 표준 폰트 호환)."""
    if risk == RISK_HIGH:
        return "⚠"
    if risk == RISK_MEDIUM:
        return "ⓘ"
    return "✓"
