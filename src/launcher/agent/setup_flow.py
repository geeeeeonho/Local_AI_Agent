"""User-facing setup selections for the automation agent.

This module owns setup choices only. Runtime command construction belongs to
``runtime_config`` and live App Server/session behavior belongs to the session
controller.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from launcher import network_policy
from launcher.presenter.base import MenuItem, Presenter


def select_profile(p: Presenter):
    from launcher.agent import profiles

    items = [
        MenuItem(
            key=prof.key,
            title=prof.label,
            description=prof.description,
        )
        for prof in profiles.PROFILES
    ]
    items.append(MenuItem(key="b", title="취소", separator_above=True))
    choice = p.show_menu(
        title="프로젝트 프로필 선택",
        subtitle="에이전트의 '전문가 자아' 를 결정합니다",
        items=items,
    )
    if choice in ("b", "q", None):
        return None
    return profiles.by_key(choice) or profiles.default()


def ask_workspace(p: Presenter, env: Path) -> Optional[Path]:
    del env
    import project_paths
    default = project_paths.workspace_dir()

    last_used = None
    try:
        from launcher import settings_store
        cfg = settings_store.load()
        if cfg.last_workspace:
            candidate = Path(cfg.last_workspace)
            if candidate.exists():
                last_used = candidate
    except Exception:
        pass

    allowed: list[str] = []
    try:
        from launcher.agent import folder_policy
        allowed = [
            value for value in folder_policy.list_allowed()
            if Path(value).exists() and Path(value).is_dir()
        ]
    except Exception:
        allowed = []

    if allowed:
        items = [
            MenuItem(key=str(index), title=Path(value).name, description=value)
            for index, value in enumerate(allowed, 1)
        ]
        items.append(MenuItem(key="o", title="직접 다른 폴더 선택", separator_above=True))
        items.append(MenuItem(key="b", title="취소"))
        choice = p.show_menu(
            title="작업 폴더 선택",
            subtitle="허용 폴더 중에서 작업할 폴더를 고르세요 (나머지 허용 폴더도 함께 접근 가능)",
            items=items,
        )
        if choice in ("b", "q", None):
            return None
        if choice != "o":
            try:
                index = int(choice) - 1
                if 0 <= index < len(allowed):
                    return Path(allowed[index])
            except (TypeError, ValueError):
                pass

    return p.prompt_path(
        title="GUI 통합 대화 — 작업 폴더",
        default=default,
        last_used=last_used,
        must_exist=False,
    )


def select_execution_mode(p: Presenter) -> str | None:
    choice = p.show_menu(
        title="실행 모드 선택",
        subtitle="에이전트를 어디서 실행할지 선택하세요",
        items=[
            MenuItem(
                key="sandbox",
                title="샌드박스 (권장)",
                description="Docker 컨테이너에서 격리 실행 — 안전",
                badge="권장",
                badge_kind="good",
            ),
            MenuItem(
                key="host",
                title="호스트 직접 (위험)",
                description="호스트 PC 에 직접 접근 — 격리 없음",
                badge="위험",
                badge_kind="danger",
            ),
        ],
    )
    return choice if choice in ("sandbox", "host") else None


def select_agent_model(env: Path, p: Presenter):
    """Select the execution-agent model role using the existing model ladder."""
    del env
    from launcher import config
    try:
        from launcher.models import model_roles as mr
    except Exception:
        return {"tag": config.MODEL_TAG, "reason": "기본 모델", "label": "기본"}

    exec_keys = ("5", "2", "3", "4")
    roles = [mr.by_key(key) for key in exec_keys if mr.by_key(key)]
    if not roles:
        return {"tag": config.MODEL_TAG, "reason": "기본 모델", "label": "기본"}

    items = []
    for role in roles:
        badge = "권장" if role.key == "5" else None
        items.append(MenuItem(
            key=role.key,
            title=role.label,
            description=role.description,
            badge=badge,
            badge_kind="good" if badge else None,
        ))
    items.append(MenuItem(key="b", title="취소", separator_above=True))

    free = mr.detect_free_memory_gb()
    free_text = (
        "여유 메모리 " + format(free, ".1f") + "GB"
        if free is not None
        else "여유 메모리 탐지 실패"
    )
    choice = p.show_menu(
        title="에이전트 모델 역할 선택",
        subtitle=free_text + " · 하 단계 모델은 기본 설치에서 제외 (필요하면 수동 설치)",
        items=items,
    )
    if choice in ("b", "q", None):
        return None

    role = mr.by_key(choice) or mr.by_key("2")
    resolved = mr.resolve(role, free)
    tag, reason = resolved.model, resolved.reason
    ladders = getattr(mr, "LADDERS", {})
    if getattr(role, "name", "") in ladders and hasattr(mr, "resolve_ladder"):
        picked = mr.resolve_ladder(role.name, free)
        if picked is None:
            p.warn("모델을 적재할 메모리가 부족합니다. "
                   "Models에서 하 단계 모델을 수동으로 설치하거나 메모리를 확보하세요.")
            return None
        if picked != tag:
            reason = "사다리 선택(여유 적응): " + picked
        tag = picked
    return {"tag": tag, "reason": reason, "label": role.label}


def select_internet_mode(p: Presenter) -> bool:
    """Compatibility picker that persists one canonical network mode.

    Returns ``True`` only for proxy-backed WARP/Tor because older callers still
    use a boolean ``tor_proxy`` parameter. Direct and Block both return False,
    while their distinct canonical meanings remain persisted in network_policy.
    """
    items = [
        MenuItem(
            key="warp",
            title="WARP 경유 (빠름·기본)",
            description="Cloudflare WARP 로 IP 보호 · 빠르고 차단 적음",
            badge="권장",
            badge_kind="good",
        ),
        MenuItem(
            key="tor",
            title="Tor 경유 (최고 익명)",
            description="Tor 로 우회 · 가장 익명적이나 느림",
            badge="익명",
        ),
        MenuItem(
            key="direct",
            title="직접 연결",
            description="호스트 네트워크로 직접 연결 — IP 노출",
        ),
        MenuItem(
            key="block",
            title="인터넷 차단",
            description="관리형 공용 egress 차단 — 가장 안전",
        ),
        MenuItem(key="b", title="취소", separator_above=True),
    ]
    # Open on the mode that is already prepared. Starting somewhere else meant
    # a user who changed nothing still picked a different mode than the window
    # had pinned, and the Agent was refused before anything ran.
    active = network_policy.current_mode().value
    choice = p.show_menu(
        title="에이전트 인터넷 설정",
        subtitle="현재 준비된 모드: " + active
                 + " · 다른 모드는 Network 화면에서 먼저 바꾸세요.",
        items=items,
        last_choice=active,
    )
    if choice not in {mode.value for mode in network_policy.NetworkMode}:
        return False
    selected = network_policy.set_mode(choice)
    return selected in (network_policy.NetworkMode.WARP, network_policy.NetworkMode.TOR)


__all__ = [
    "select_profile",
    "ask_workspace",
    "select_execution_mode",
    "select_agent_model",
    "select_internet_mode",
]
