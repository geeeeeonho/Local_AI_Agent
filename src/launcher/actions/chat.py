"""actions.chat — [1] AnythingLLM 채팅/RAG 서비스.

AnythingLLM is the single active ChatService. Ollama remains on the host,
SearXNG is started only when public egress is enabled, and network semantics
come exclusively from ``launcher.network_policy``.
"""
from __future__ import annotations

import os
import webbrowser
from pathlib import Path

from ..presenter.base import MenuItem, Presenter
from ..services.ollama import OllamaService


def _select_network_mode(p: Presenter) -> str | None:
    """Select and persist the canonical AnythingLLM network posture."""
    from .. import network_policy

    forced = os.environ.get("LOCAL_AI_ANYTHINGLLM_NET", "").strip().lower()
    if forced:
        if forced not in {mode.value for mode in network_policy.NetworkMode}:
            p.error("지원하지 않는 AnythingLLM 인터넷 모드: " + forced)
            return None
        return network_policy.set_mode(forced).value

    items = [
        MenuItem("warp", "WARP 경유 (빠름, 권장)"),
        MenuItem("tor", "Tor 경유 (최고 익명, 느림)"),
        MenuItem("direct", "직접 연결 (호스트 IP 노출)"),
        MenuItem("block", "차단 (로컬 채팅/RAG만 사용)"),
    ]
    choice = p.show_menu(
        title="AnythingLLM 인터넷 모드",
        subtitle="공용 웹 트래픽 경로를 선택하세요. Block은 로컬 채팅/RAG만 허용합니다.",
        items=items,
        last_choice=network_policy.current_mode().value,
    )
    if choice not in {mode.value for mode in network_policy.NetworkMode}:
        return None
    return network_policy.set_mode(str(choice)).value


def _ensure_ollama(env: Path, p: Presenter) -> bool:
    """Reuse/start only the project-managed Ollama with the shared model store."""
    return bool(OllamaService(env, logger=p).ensure_running())


def _ensure_docker(p: Presenter) -> bool:
    """Ensure Docker Desktop is usable, preserving the existing auto-start UX."""
    from ..services.docker import DockerService

    cancel_check = p.is_cancelled if hasattr(p, "is_cancelled") else None
    return bool(
        DockerService.ensure_daemon(
            logger=p,
            timeout=90,
            cancel_check=cancel_check,
        )
    )


def _keep_chat_running() -> bool:
    """Whether this terminal Chat session should leave its container running."""
    truthy = {"1", "true", "yes", "on"}
    current = os.environ.get("LOCAL_AI_KEEP_CHAT", "").strip().lower()
    return current in truthy


def run(env: Path, p: Presenter):
    from .. import anythingllm_runtime as runtime
    from .. import config, network_policy

    mode = _select_network_mode(p)
    if not mode:
        return

    p.section("AnythingLLM 채팅/RAG")
    p.info("인터넷 모드: " + network_policy.display_label(mode))

    keep = _keep_chat_running()
    started_searxng = False
    try:
        if not _ensure_ollama(env, p):
            return

        if not _ensure_docker(p):
            p.error("Docker Desktop을 준비할 수 없습니다. 상태를 확인한 뒤 다시 시도하세요.")
            return

        if not runtime.image_exists():
            if mode == network_policy.NetworkMode.BLOCK.value:
                p.error(
                    "Block 모드에서는 새 이미지를 다운로드하지 않습니다. "
                    "RUN.bat --install에서 AnythingLLM 이미지를 먼저 설치하세요."
                )
                return
            p.warn("AnythingLLM 이미지가 없습니다. 지금 다운로드합니다 (약 3~5GB).")
            ok = runtime.pull(
                log=p.progress_callback() if hasattr(p, "progress_callback") else p.info,
                cancel_check=p.is_cancelled if hasattr(p, "is_cancelled") else None,
            )
            if not ok:
                p.error("AnythingLLM 이미지 다운로드 실패")
                return

        if mode != network_policy.NetworkMode.BLOCK.value:
            try:
                from .. import searxng_runtime
                if searxng_runtime.image_exists():
                    p.info("SearXNG 검색 서비스 시작 중...")
                    # start(env, ...) 는 env 가 필수다. 인자 없이 부르면 TypeError 가
                    # 나고 바로 아래 except 가 삼켜서, 검색이 조용히 꺼진 채로
                    # Chat 이 시작됐다.
                    started_searxng = bool(searxng_runtime.start(env))
                    if not started_searxng:
                        p.warn("SearXNG를 시작하지 못했습니다. 로컬 채팅/RAG는 계속 사용할 수 있습니다.")
                else:
                    p.warn("SearXNG 이미지가 없습니다. 웹 검색 기능은 비활성 상태로 시작합니다.")
            except Exception as exc:
                p.warn("SearXNG 시작 건너뜀: " + str(exc))
        else:
            p.info("Block 모드: 공용 웹 검색은 비활성화됩니다.")

        # TOKEN_LIMITS_v1: config 가 정본이다. 예전 코드는 존재하지 않는
        # model_roles.chat_context_window() 를 부르고 실패를 삼켜, 정본 대신
        # 하드코딩된 4096 이 늘 쓰였다.
        ctx = int(config.CHAT_CONTEXT_WINDOW)

        # TUI entrypoints resolve against the same live Ollama
        # inventory as the desktop Chat path. A static default that is not
        # installed otherwise makes a healthy AnythingLLM connection fail.
        from ..models import model_roles
        from integrations.ollama.client import is_cloud_tag
        model, note = model_roles.auto_match_installed(
            getattr(config, "MODEL_TAG", ""), role_name="balanced"
        )
        if not model or is_cloud_tag(model):
            installed = model_roles.installed_models() or set()
            local = sorted(tag for tag in installed if not is_cloud_tag(tag))
            model = local[0] if local else None
            note = ("로컬 모델 자동 선택: " + model) if model else note
        if not model:
            p.error(note or "설치된 로컬 Ollama 모델이 없습니다.")
            return
        if note:
            p.info(note)

        p.info("AnythingLLM 시작 중...")
        ok = runtime.start(
            log=p.progress_callback() if hasattr(p, "progress_callback") else p.info,
            model_tag=model,
            token_limit=ctx,
            cancel_check=p.is_cancelled if hasattr(p, "is_cancelled") else None,
        )
        if not ok:
            p.error("AnythingLLM 시작 실패")
            return

        p.ok("AnythingLLM 준비 완료: " + runtime.URL)
        p.info("처음 실행이면 브라우저에서 관리자 계정/워크스페이스를 생성하세요.")
        try:
            opened = webbrowser.open(runtime.URL)
            if opened is False:
                p.warn("브라우저 자동 열기에 실패했습니다. 직접 여세요: " + runtime.URL)
        except Exception as exc:
            p.warn("브라우저 자동 열기 실패: %s · 직접 여세요: %s" % (exc, runtime.URL))
        p.pause("브라우저를 닫아도 서비스는 이 메뉴가 열려 있는 동안 유지됩니다. 종료하려면 Enter")
    finally:
        if not keep:
            try:
                runtime.stop()
            except Exception:
                pass
            if started_searxng:
                try:
                    from .. import searxng_runtime
                    searxng_runtime.stop()
                except Exception:
                    pass


__all__ = ["run"]
