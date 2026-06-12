"""agent_lifecycle — 활성 UnifiedAgent global registry + bulk cleanup.

v4 lifecycle patch (v4_lifecycle).

문제
────
이전 버전: _run_gui_chat() 가 agent 를 폴링 클로저에 가둬서, 사용자가
사이드바를 클릭해 패널을 떠나도 docker 컨테이너가 살아남는다.

해결
────
모든 UnifiedAgent 가 시작 시 register() 호출, 종료 시 unregister() 호출.
런처 종료 시 cleanup_all() 로 일괄 정리.

Thread-safety: 모든 함수는 어느 스레드에서나 호출 가능 (내부 RLock).
"""
from __future__ import annotations

import threading
import weakref
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent_runner import UnifiedAgent

__all__ = ["register", "unregister", "cleanup_all", "count_active"]


_lock = threading.RLock()
# weakref.WeakSet -- agent 가 GC 되면 자동 제거
_active: "weakref.WeakSet[UnifiedAgent]" = weakref.WeakSet()


def register(agent: "UnifiedAgent") -> None:
    """에이전트를 활성 목록에 등록."""
    with _lock:
        _active.add(agent)


def unregister(agent: "UnifiedAgent") -> None:
    """에이전트를 활성 목록에서 제거."""
    with _lock:
        _active.discard(agent)


def count_active() -> int:
    """현재 활성 에이전트 수."""
    with _lock:
        return len(_active)


def cleanup_all(timeout: float = 3.0) -> int:
    """활성 에이전트 모두 종료. 종료된 개수 반환.

    런처 종료(WM_DELETE_WINDOW) 시 호출. 각 에이전트의 stop() 을 부른다.
    """
    with _lock:
        agents = list(_active)
    n = 0
    for ag in agents:
        try:
            ag.stop(timeout=timeout)
            n += 1
        except Exception:
            pass
    return n
