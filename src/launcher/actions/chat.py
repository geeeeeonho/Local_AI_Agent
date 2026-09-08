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

    choice = p.show_menu(
        [
            MenuItem("warp", "WARP 경유 (빠름, 권장)"),
            MenuItem("tor", "Tor 경유 (최고 익명, 느림)"),
            MenuItem("direct", "직접 연결 (호스트 IP 노출)"),
            MenuItem("block", "차단 (로컬 채팅/RAG만 사용)"),
        ],
        "AnythingLLM 인터넷 모드",
    )
    if not choice:
        return None
    return network_policy.set_mode(str(choice)).value


def _ensure_ollama(env: Path, p: Presenter) -> bool:
    ollama = OllamaService(env)
    if ollama.is_running():
        return True
    p.info("Ollama 시작 중...")
    if ollama.start() and ollama.wait_ready(timeout=60):
        return True
    p.error("Ollama 시작 실패")
    return False


def run(env: Path, p: Presenter):
    from .. import anythingllm_runtime as runtime
    from .. import config, network_policy
    from ..services.docker import DockerService

    mode = _select_network_mode(p)
    if not mode:
        return

    p.section("AnythingLLM 채팅/RAG")
    p.info("인터넷 모드: " + network_policy.display_label(mode))

    keep = os.environ.get("LOCAL_AI_KEEP_CHAT", "0") == "1"
    started_searxng = False
    try:
        if not _ensure_ollama(env, p):
            return

        docker = DockerService()
        if not docker.is_running():
            p.error("Docker Desktop이 실행 중이 아닙니다. Docker를 시작한 뒤 다시 시도하세요.")
            return

        if not runtime.image_exists():
            if mode == network_policy.NetworkMode.BLOCK.value:
                p.error(
                    "Block 모드에서는 새 이미지를 다운로드하지 않습니다. "
                    "SETUP.bat에서 AnythingLLM 이미지를 먼저 설치하세요."
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
                    started_searxng = bool(searxng_runtime.start())
                    if not started_searxng:
                        p.warn("SearXNG를 시작하지 못했습니다. 로컬 채팅/RAG는 계속 사용할 수 있습니다.")
                else:
                    p.warn("SearXNG 이미지가 없습니다. 웹 검색 기능은 비활성 상태로 시작합니다.")
            except Exception as exc:
                p.warn("SearXNG 시작 건너뜀: " + str(exc))
        else:
            p.info("Block 모드: 공용 웹 검색은 비활성화됩니다.")

        try:
            from ..models import model_roles
            ctx = int(model_roles.chat_context_window())
        except Exception:
            ctx = int(getattr(config, "MODEL_CONTEXT", 4096))

        p.info("AnythingLLM 시작 중...")
        ok = runtime.start(
            log=p.progress_callback() if hasattr(p, "progress_callback") else p.info,
            model_tag=getattr(config, "MODEL_TAG", ""),
            token_limit=ctx,
            cancel_check=p.is_cancelled if hasattr(p, "is_cancelled") else None,
        )
        if not ok:
            p.error("AnythingLLM 시작 실패")
            return

        p.success("AnythingLLM 준비 완료: " + runtime.URL)
        p.info("처음 실행이면 브라우저에서 관리자 계정/워크스페이스를 생성하세요.")
        try:
            webbrowser.open(runtime.URL)
        except Exception:
            pass
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
