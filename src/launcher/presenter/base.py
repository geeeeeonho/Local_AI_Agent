"""presenter.base — UI 추상화 인터페이스.

핵심 개념
─────────
모든 액션(actions/*) 은 Presenter 인터페이스만 사용한다.
TUI 든 GUI 든 같은 메서드를 호출하므로 액션 코드는 UI 종류에 무지(無知)하다.

이를 통해:
  - GUI 추가가 액션 코드 0줄 변경으로 가능
  - 단위 테스트 시 Mock Presenter 주입 가능
  - 향후 웹 UI / 음성 UI 등 추가 가능
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set


# ─────────────────────────────────────────────
#  도메인 모델 (UI 와 무관한 데이터)
# ─────────────────────────────────────────────

# 위험도 상수 — checkbox.Option 호환
RISK_SAFE = 0
RISK_MEDIUM = 1
RISK_HIGH = 2


@dataclass
class Option:
    """체크박스 옵션 정의 — 기존 launcher.checkbox.Option 호환."""
    id: str
    label: str
    default: bool = False
    risk: int = RISK_SAFE
    description: str = ""
    locked: bool = False
    excludes: List[str] = field(default_factory=list)


@dataclass
class MenuItem:
    """메뉴 항목."""
    key: str                        # '1'..'9', 'q' 등
    title: str
    description: str = ""
    badge: str = ""                 # "권장" / "위험"
    badge_kind: str = ""            # "" | "good" | "warn" | "danger"
    separator_above: bool = False


# ─────────────────────────────────────────────
#  Presenter 인터페이스
# ─────────────────────────────────────────────

class Presenter(ABC):
    """모든 UI 가 구현해야 할 인터페이스.

    메서드는 동기 호출 — 사용자 응답이 나올 때까지 블록.
    """

    # ── 정보 출력 ──
    @abstractmethod
    def info(self, msg: str) -> None: ...

    @abstractmethod
    def ok(self, msg: str) -> None: ...

    @abstractmethod
    def warn(self, msg: str) -> None: ...

    @abstractmethod
    def error(self, msg: str) -> None: ...

    @abstractmethod
    def section(self, title: str, subtitle: str = "") -> None:
        """새 화면/섹션 시작 (TUI: clear+header, GUI: 윈도 타이틀)."""

    @abstractmethod
    def pause(self, msg: str = "") -> None:
        """사용자가 확인할 때까지 대기."""

    # ── 입력 ──
    @abstractmethod
    def prompt_text(self, prompt: str = "> ", default: str = "") -> str:
        """자유 텍스트 입력. 사용자가 취소하면 빈 문자열."""

    @abstractmethod
    def prompt_choice(self, prompt: str, choices: List[str]) -> Optional[str]:
        """단일 선택. None = 취소."""

    @abstractmethod
    def prompt_path(
        self, title: str, default: Path,
        last_used: Optional[Path] = None,
        must_exist: bool = True,
    ) -> Optional[Path]:
        """폴더 경로 입력. None = 취소."""

    # ── 메뉴 / 체크박스 ──
    @abstractmethod
    def show_menu(
        self, title: str, subtitle: str,
        items: List[MenuItem],
        last_choice: Optional[str] = None,
    ) -> str:
        """메인 메뉴. 사용자가 고른 키 반환. 닫기/취소 → 'q'."""

    @abstractmethod
    def show_checkbox(
        self, title: str, subtitle: str,
        options: List[Option],
        extra_lines: Optional[List[str]] = None,
        override_defaults: Optional[Set[str]] = None,
    ) -> Optional[Set[str]]:
        """체크박스 메뉴.

        반환:
          set: 사용자가 켠 옵션 id 집합 (실행 의사)
          None: 취소/뒤로
        """

    @abstractmethod
    def confirm_dangerous(
        self, label: str, description: str, risk: int,
    ) -> bool:
        """위험 옵션 활성화 동의. risk: RISK_MEDIUM/HIGH."""

    # ── 진행 표시 ──
    def progress(self, msg: str) -> None:
        """진행 상황 한 줄. info 와 동일하게 동작 가능."""
        self.info(msg)

    # ── 진입점 (entrypoint) — optional, 기본 no-op (TUI 등에서 무시) ──
    def reserve_entrypoint(self, label: str) -> None:
        """액션 시작 시 진입점(URL/콘솔) 자리만 잡아둠.

        GUI 에선 회색 placeholder 버튼으로 표시.
        TUI 에선 무시 (기본 구현).
        """
        pass

    def enable_entrypoint(
        self, callback, button_text=None,
    ) -> None:
        """진입점 준비됨 — 클릭 가능하게 활성화.

        GUI 에선 파란 버튼으로 변경.
        TUI 에선 callback 정보를 안내 메시지로 표시.
        """
        # 기본 구현: 버튼 텍스트를 info 로 출력
        if button_text:
            self.info(f"진입점: {button_text}")

    def watch_process(
        self, proc, on_terminated=None, restart_callback=None,
    ) -> None:
        """외부 프로세스 종료 감지 (선택). 기본 no-op."""
        pass

    def is_cancelled(self) -> bool:
        """액션이 외부에서 취소됐는지. TUI 등은 항상 False (취소 메커니즘 없음)."""
        return False
