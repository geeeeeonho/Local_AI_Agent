"""checkbox — 위험 옵션 확인 절차 포함 인터랙티브 체크박스 메뉴.

설계:
  - 각 옵션마다 위험도(SAFE/MEDIUM/HIGH) 부여
  - SAFE 옵션은 자유롭게 토글
  - MEDIUM 옵션은 켤 때 'ENABLE' 입력 요구
  - HIGH 옵션은 켤 때 'I-UNDERSTAND' 입력 요구
  - 끄기는 항상 자유 (위험을 제거하는 방향이므로)
  - locked=True 옵션은 토글 자체 불가
  - excludes 로 상호 배제 옵션 그룹 정의
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Set

from . import ui

# ─── 위험도 상수 ───
SAFE   = 0
MEDIUM = 1
HIGH   = 2


@dataclass
class Option:
    id: str                          # 고유 식별자
    label: str                       # 표시 라벨
    default: bool = False            # 기본 체크 여부
    risk: int = SAFE                 # SAFE / MEDIUM / HIGH
    description: str = ""            # 추가 설명 (여러 줄 가능)
    locked: bool = False             # 토글 금지
    excludes: List[str] = field(default_factory=list)  # 같이 켤 수 없는 id


# ─── 표시 헬퍼 ───
def _risk_marker(risk: int) -> str:
    if risk == HIGH:    return ui.C.R + "⚠⚠" + ui.C.E
    if risk == MEDIUM:  return ui.C.Y + "⚠ " + ui.C.E
    return "  "


def _check_marker(checked: bool, locked: bool) -> str:
    if locked and checked:
        return ui.C.DIM + "[✓]" + ui.C.E
    if locked:
        return ui.C.DIM + "[ ]" + ui.C.E
    return ui.C.G + "[✓]" + ui.C.E if checked else "[ ]"


# ─── 위험 옵션 확인 절차 ───
def _confirm_dangerous(opt: Option) -> bool:
    """위험 옵션을 켤 때 명시적 키워드 입력 요구."""
    ui.clear()

    if opt.risk == HIGH:
        head_color = ui.C.R
        keyword = "I-UNDERSTAND"
        head_text = "⚠⚠ 매우 위험한 옵션 활성화 ⚠⚠"
    else:
        head_color = ui.C.Y
        keyword = "ENABLE"
        head_text = "⚠ 주의 필요한 옵션 활성화 ⚠"

    print(head_color + ui.C.BD + head_text + ui.C.E)
    ui.hr()
    print()
    print(f"  옵션: {ui.C.BD}{opt.label}{ui.C.E}")
    print()

    if opt.description:
        print(f"  {ui.C.DIM}설명:{ui.C.E}")
        for line in opt.description.split("\n"):
            print(f"    {line}")
        print()

    if opt.risk == HIGH:
        print(f"  {ui.C.R}이 옵션은 시스템에 심각한 영향을 줄 수 있습니다.{ui.C.E}")
    else:
        print(f"  {ui.C.Y}이 옵션은 추가 위험이 있습니다.{ui.C.E}")

    print()
    print(f"  활성화하려면 정확히 {ui.C.BD}'{keyword}'{ui.C.E}를 입력하세요.")
    print(f"  {ui.C.DIM}그 외 입력은 취소로 처리됩니다.{ui.C.E}")
    print()

    response = ui.prompt("> ")
    return response == keyword


# ─── 메인 함수 ───
def run(
    title: str,
    subtitle: str,
    options: List[Option],
    extra_lines: Optional[List[str]] = None,
    override_defaults: Optional[Set[str]] = None,
) -> Optional[Set[str]]:
    """체크박스 메뉴 실행.

    Args:
        override_defaults: 옵션 기본값을 덮어쓸 ID 집합. None 이면 Option.default 사용.
            저장된 설정으로 초기화할 때 사용. 위험 옵션은 호출자가 미리 걸러서 전달해야 함.

    Returns:
        켜진 옵션의 id set. 'b'/'q' 누르면 None.
    """
    # 기본값 결정: override 가 있으면 그걸로, 없으면 Option.default
    if override_defaults is not None:
        state = {opt.id: (opt.id in override_defaults) for opt in options}
        # locked 옵션은 항상 자기 default 강제 (override 무시)
        for opt in options:
            if opt.locked:
                state[opt.id] = opt.default
    else:
        state = {opt.id: opt.default for opt in options}

    last_msg: Optional[str] = None

    while True:
        ui.header(title, subtitle)

        if extra_lines:
            for line in extra_lines:
                print("  " + line)
            print()

        # 옵션 목록
        for i, opt in enumerate(options, 1):
            mark = _check_marker(state[opt.id], opt.locked)
            risk = _risk_marker(opt.risk)
            num  = f"{ui.C.DIM}{i:2d}.{ui.C.E}"

            print(f"  {num}  {mark} {risk} {opt.label}")

            if opt.description:
                first = opt.description.split("\n")[0]
                print(f"           {ui.C.DIM}{first}{ui.C.E}")

        print()
        ui.hr(color=ui.C.DIM)
        print(f"  {ui.C.DIM}번호 입력: 토글 (예: '3' 또는 '3 5'){ui.C.E}")
        print(f"  {ui.C.DIM}go: 실행  |  b: 뒤로  |  q: 종료{ui.C.E}")

        if last_msg:
            print()
            print(f"  {last_msg}")
            last_msg = None

        print()
        cmd = ui.prompt("> ").lower()

        # 명령어 처리
        if cmd in ("q", "quit"):
            return None
        if cmd in ("b", "back"):
            return None
        if cmd in ("go", "g", "r", "run"):
            return {oid for oid, on in state.items() if on}

        # 숫자 토글
        try:
            indices = [int(t) - 1 for t in cmd.split()]
        except ValueError:
            last_msg = ui.C.Y + "잘못된 입력 — 번호 또는 명령어를 입력하세요" + ui.C.E
            continue

        for idx in indices:
            if not (0 <= idx < len(options)):
                last_msg = ui.C.Y + f"범위 밖: {idx + 1}" + ui.C.E
                continue

            opt = options[idx]

            if opt.locked:
                last_msg = ui.C.Y + f"'{opt.label}'은(는) 잠긴 항목입니다" + ui.C.E
                continue

            currently_on = state[opt.id]

            if not currently_on:
                # ── 켜기 ──
                if opt.risk >= MEDIUM:
                    if not _confirm_dangerous(opt):
                        last_msg = ui.C.DIM + f"'{opt.label}' 활성화 취소됨" + ui.C.E
                        continue

                # 상호 배제 처리
                for ex_id in opt.excludes:
                    if state.get(ex_id):
                        state[ex_id] = False

                state[opt.id] = True

            else:
                # ── 끄기 (위험 제거 방향이므로 자유) ──
                state[opt.id] = False
