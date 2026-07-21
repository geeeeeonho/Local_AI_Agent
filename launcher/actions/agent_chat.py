"""actions.agent_chat — [9] GUI 통합 대화 모드.

지시사항 [1~4단계] 통합:
  - 프로젝트 프로필 선택 (range_dev/Python/web/Unity/...)
  - subprocess.PIPE 로 docker 안 interpreter 실행
  - 단일 윈도우 내 대화창에서 양방향 상호작용
  - 화면 캡처 시도 자동 차단 (system_message + env + ErrorGuard)
  - [중단] 버튼으로 즉시 종료

GUI 전용 — TUI 에서 호출 시 안내 후 폴백.
"""
# v7_2_diag
from __future__ import annotations

import os
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .. import config
from ..presenter.base import MenuItem, Presenter
from ..services.docker import DockerService
from ..services.ollama import OllamaService


def _resolve_resource_limits(env: Path) -> tuple[str, str]:
    """시스템 사양 기반 (memory, cpus) 결정."""
    try:
        from installer.resources import detect, compute_safety_profile
        spec = detect(env)
        profile = compute_safety_profile(spec)
        return profile.container_memory, profile.container_cpus
    except Exception:
        return config.DEFAULT_CONTAINER_MEM, config.DEFAULT_CONTAINER_CPUS


def _select_profile(p: Presenter):
    """프로필 선택 — 메뉴 표시."""
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
    if choice in ("b", "q"):
        return None

    return profiles.by_key(choice) or profiles.default()


def _ask_workspace(p: Presenter, env: Path) -> Optional[Path]:
    """작업 폴더 선택. 허용 폴더가 있으면 그중에서 고르게 하고, 아니면 직접 선택. FOLDER_WS_v1."""
    default = env / "agent" / "workspace"

    last_used = None
    try:
        from .. import settings_store
        cfg = settings_store.load()
        if cfg.last_workspace:
            lp = Path(cfg.last_workspace)
            if lp.exists():
                last_used = lp
    except Exception:
        pass

    # FOLDER_WS_v1: 허용 폴더가 있으면 그중에서 '작업 폴더'를 고르게 (의도: 허용 폴더에서 작업)
    allowed = []
    try:
        from launcher.agent import folder_policy as _fp
        allowed = [a for a in _fp.list_allowed()
                   if Path(a).exists() and Path(a).is_dir()]
    except Exception:
        allowed = []
    if allowed:
        try:
            items = []
            for i, a in enumerate(allowed, 1):
                items.append(MenuItem(key=str(i), title=Path(a).name, description=a))
            items.append(MenuItem(key="o", title="직접 다른 폴더 선택", separator_above=True))
            items.append(MenuItem(key="b", title="취소"))
            c = p.show_menu(
                title="작업 폴더 선택",
                subtitle="허용 폴더 중에서 작업할 폴더를 고르세요 (나머지 허용 폴더도 함께 접근 가능)",
                items=items,
            )
            if c in ("b", "q", None):
                return None
            if c != "o":
                try:
                    idx = int(c) - 1
                    if 0 <= idx < len(allowed):
                        return Path(allowed[idx])
                except Exception:
                    pass
        except Exception:
            pass

    return p.prompt_path(
        title="GUI 통합 대화 — 작업 폴더",
        default=default,
        last_used=last_used,
        must_exist=False,
    )


def _open_folder_in_explorer(folder: Path) -> None:
    """탐색기로 폴더 열기 (Windows/맥/리눅스 호환)."""
    try:
        if os.name == "nt":
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except Exception:
        pass


def _v63_trace(stage: str) -> None:
    """lifelog 가 있으면 trace 기록. 없으면 무시."""
    try:
        from launcher.core import lifelog as _ll
        _ll.log("TRACE", "[agent_chat] " + stage)
    except Exception:
        pass



# ─────────────────────────────────────────────
#  v7_1_unified: 통합 자동화 에이전트 진입점
# ─────────────────────────────────────────────
def _select_execution_mode(p):
    """실행 모드 선택 — 샌드박스(권장) vs 호스트 직접(위험).

    Returns: "sandbox" | "host" | None(취소)
    """
    from ..presenter.base import MenuItem
    items = [
        MenuItem(
            key="sandbox", title="샌드박스 (권장)",
            description="Docker 컨테이너에서 격리 실행 — 안전",
            badge="권장", badge_kind="good",
        ),
        MenuItem(
            key="host", title="호스트 직접 (위험)",
            description="호스트 PC 에 직접 접근 — 격리 없음",
            badge="위험", badge_kind="danger",
        ),
    ]
    choice = p.show_menu(
        title="실행 모드 선택",
        subtitle="에이전트를 어디서 실행할지 선택하세요",
        items=items,
    )
    if choice in ("sandbox", "host"):
        return choice
    return None


# LLM_AGENT_MODEL_ROLE_v1: 역할 기반 메모리 적응형 모델 선택
def _select_agent_model(env, p):
    """에이전트가 쓸 모델을 역할 기반으로 선택 + 메모리 적응 해석.

    Returns: {"tag","reason","label"} 또는 None(취소).
    model_roles 가 없으면 config.MODEL_TAG 로 안전 폴백.
    """
    from .. import config
    try:
        from launcher.models import model_roles as mr
    except Exception:
        try:
            from launcher.models import model_roles as mr  # 절대 경로 폴백
        except Exception:
            return {"tag": config.MODEL_TAG, "reason": "기본 모델", "label": "기본"}

    try:
        from ..presenter.base import MenuItem
    except Exception:
        return {"tag": config.MODEL_TAG, "reason": "기본 모델", "label": "기본"}

    # 코드 실행 에이전트에 적합한 역할만 (무검열 검색/번역은 채팅용 → 실행기에서 제외)
    exec_keys = ("5", "2", "3", "4")  # MODEL_FINAL_v8: 에이전트(권장)/코딩/맥락/균형
    roles = [mr.by_key(k) for k in exec_keys if mr.by_key(k)]
    if not roles:
        return {"tag": config.MODEL_TAG, "reason": "기본 모델", "label": "기본"}

    items = []
    for r in roles:
        _badge = "권장" if r.key == "5" else None  # MODEL_FINAL_v8
        items.append(MenuItem(
            key=r.key, title=r.label, description=r.description,
            badge=_badge, badge_kind=("good" if _badge else None),
        ))
    items.append(MenuItem(key="b", title="취소", separator_above=True))

    free = mr.detect_free_memory_gb()
    free_txt = ("여유 메모리 " + format(free, ".1f") + "GB") if free is not None else "여유 메모리 탐지 실패"
    choice = p.show_menu(
        title="에이전트 모델 역할 선택",
        subtitle=free_txt + " · 코딩은 부족하면 7b 자동",
        items=items,
    )
    if choice in ("b", "q"):
        return None
    role = mr.by_key(choice) or mr.by_key("2")
    res = mr.resolve(role, free)
    tag, reason = res.model, res.reason
    # MODEL_ROLLBACK_v1: 사다리(다단계 양자화) 기반 메모리 적응 선택 우선
    _lad = getattr(mr, "LADDERS", {})
    if getattr(role, "name", "") in _lad and hasattr(mr, "resolve_ladder"):
        _picked = mr.resolve_ladder(role.name, free)
        if _picked:
            if _picked != tag:
                reason = "사다리 선택(여유 적응): " + _picked
            tag = _picked
    return {"tag": tag, "reason": reason, "label": role.label}


def _select_internet_mode(p):  # TOR_TOGGLE_v1
    """샌드박스 인터넷: 차단(기본) vs Tor 경유. Returns True=Tor, False=차단."""
    try:
        from ..presenter.base import MenuItem
    except Exception:
        return False
    items = [
        MenuItem(key="block", title="인터넷 차단 (기본·권장)",
                 description="샌드박스에서 외부 인터넷 차단 — 가장 안전",
                 badge="권장", badge_kind="good"),
        MenuItem(key="tor", title="Tor 경유 인터넷 허용",
                 description="외부 트래픽을 Tor(9050)로 프록시 · Tor 데몬 필요 · "
                             "Ollama 는 직접 연결 유지",
                 badge="주의", badge_kind="danger"),
    ]
    items.append(MenuItem(key="b", title="취소", separator_above=True))
    choice = p.show_menu(
        title="샌드박스 인터넷 설정",
        subtitle="기본은 차단. Tor 경유는 Tor(9050)가 실행 중일 때만 동작합니다.",
        items=items,
    )
    return choice == "tor"


def _build_cmd_for_mode(mode, env, profile, workspace, container_name,
                        context_window, run_mem, run_cpus, model_tag=None,
                        tor_proxy=False):
    """모드별 PIPE 명령 조립.

    Returns: (cmd, is_host) 또는 (None, _) 실패 시
    """
    from .. import config
    if mode == "sandbox":
        from launcher.agent.agent_runner import build_sandbox_pipe_cmd
        from launcher.agent import profiles as _profiles  # FOLDER_WS_v1: 작업 폴더 + 허용 폴더 안내 주입
        _sysmsg = profile.system_message + _profiles.build_session_addendum(workspace)
        cmd = build_sandbox_pipe_cmd(
            image=config.SANDBOX_IMAGE,
            container_name=container_name,
            workspace=workspace,
            workspace_mount=config.SANDBOX_WORKSPACE_MOUNT,
            model_tag=(model_tag or config.MODEL_TAG),
            ollama_port=config.OLLAMA_PORT,
            profile_system_message=_sysmsg,
            context_window=context_window,
            memory_limit=run_mem,
            cpu_limit=run_cpus,
            block_internet=(not tor_proxy),  # TOR_TOGGLE_v1
            tor_proxy=tor_proxy,
            auto_run=True,   # 샌드박스 안이라 안전
        )
        return cmd, False
    else:  # host
        from launcher.agent.agent_runner import build_host_pipe_cmd
        interp = env / "agent" / "venv" / "Scripts" / "interpreter.exe"
        if not interp.exists():
            return None, True
        cmd = build_host_pipe_cmd(
            interpreter_exe=str(interp),
            model_tag=(model_tag or config.MODEL_TAG),
            ollama_url=config.OLLAMA_URL,
            profile_system_message=profile.system_message,
            context_window=context_window,
            auto_run=False,  # 호스트는 매 명령 확인 (안전)
        )
        return cmd, True


def run(env, p):
    """[2] 통합 자동화 에이전트 진입점 (v7_1_unified).

    프로필 선택 -> 워크스페이스 선택 -> 실행 모드 선택
    -> GUI 내장 ChatPanel 로 양방향 대화 (샌드박스/호스트 공통).
    """
    from .. import config
    import secrets

    p.section("자동화 에이전트")
    # MODEL_CLASSES_ENTRY_v1: 진입 시 클래스별 사다리 + 현재 메모리 추천
    try:
        try:
            from ..models import model_classes as _mcls
        except Exception:
            from launcher.models import model_classes as _mcls
        p.info(_mcls.format_text())
    except Exception:
        pass
    _v63_trace("통합 run() 진입")

    # GUI 전용 가드
    try:
        from ..presenter.gui import TkPresenter
        if not isinstance(p, TkPresenter):
            p.warn("이 메뉴는 GUI (TkPresenter) 전용입니다.")
            p.info("터미널 모드에서는 별도 콘솔에서 실행하세요.")
            p.pause()
            return
    except Exception:
        pass

    # ── 1) 프로필 선택 ──
    _v63_trace("프로필 선택 직전")
    profile = _select_profile(p)
    _v63_trace("프로필 선택 완료: " + (profile.name if profile else "None"))
    if profile is None:
        return

    # LLM_AGENT_MODEL_ROLE_v1: 역할(모델) 선택 — 메모리 적응형
    # UNIFIED_ENTRY_v1: 모델/실행모드/인터넷을 한 창에서 선택 (실패 시 순차 메뉴 폴백)
    _uni = False
    try:
        from ..agent import entry_dialog as _ed
        _uni = _ed.agent_setup(env, p)  # ENTRY_INWINDOW_v1
    except Exception:
        _uni = False
    if _uni is None:
        p.info("취소")
        return
    if isinstance(_uni, dict):
        _model_sel = _uni
    else:
        _model_sel = _select_agent_model(env, p)
    if _model_sel is None:
        return
    agent_model_tag = _model_sel["tag"]
    p.info("에이전트 모델: " + agent_model_tag + "  (" + _model_sel["reason"] + ")")

    # ── 2) 워크스페이스 선택 ──
    _v63_trace("워크스페이스 선택 직전")
    # FOLDER_POLICY_v1: 허용/금지 폴더 설정(설정 버튼)
    try:
        from launcher.agent import folder_policy as _fp
        _fp.maybe_manage(p, env)
    except Exception:
        pass
    workspace = _ask_workspace(p, env)
    _v63_trace("워크스페이스 선택 완료: " + str(workspace))
    if workspace is None:
        return

    # ── 3) 실행 모드 선택 ──
    _v63_trace("실행 모드 선택 직전")
    mode = _uni["mode"] if isinstance(_uni, dict) else _select_execution_mode(p)  # UNIFIED_ENTRY_v1
    _v63_trace("실행 모드 선택 완료: " + str(mode))
    if mode is None:
        return

    # ── 4) 호스트 직접이면 확인 게이트 ──
    if mode == "host":
        from ..presenter.base import RISK_HIGH
        p.section("호스트 직접 모드 — 위험 확인")
        p.error("호스트 PC 에 직접 접근합니다. 격리가 없습니다.")
        p.warn("모델 실수가 PC 에 직접 영향을 줄 수 있습니다.")
        if not p.confirm_dangerous(
            label="호스트 직접 모드 진입",
            description=(
                "에이전트가 호스트 PC 의 모든 파일·명령에 직접 접근합니다.\n"
                "복구 불가능한 손상이 발생할 수 있습니다."
            ),
            risk=RISK_HIGH,
        ):
            p.info("취소 (권장: 샌드박스 모드 사용)")
            p.pause()
            return

    # ── 5) Ollama 확인 ──
    try:
        from ..services.ollama import OllamaService
        if not OllamaService(env, logger=p).ensure_running():
            p.error("Ollama 서비스를 시작할 수 없습니다.")
            p.pause()
            return
    except Exception:
        pass

    # MODEL_ROLLBACK_v1: Ollama 확인 후 실제 적재 probe -> OOM/실패 시 자동 강등
    try:
        from launcher.models import model_roles as _mr8
        if hasattr(_mr8, "resolve_with_rollback") and hasattr(_mr8, "LADDERS"):
            _free8 = _mr8.detect_free_memory_gb()
            _rname8 = None
            for _k8, _lad8 in _mr8.LADDERS.items():
                if any(_m8 == agent_model_tag for _m8, _nb8 in _lad8):
                    _rname8 = _k8
                    break
            if _rname8:
                _rolled8 = _mr8.resolve_ladder(_rname8, _free8)  # PREWARM_UI_v1: 전환 전 적재 안 함
                if _rolled8 and _rolled8 != agent_model_tag:
                    p.warn("적재 실패 감지 -> " + _rolled8 + " 로 롤백")
                    agent_model_tag = _rolled8
    except Exception:
        pass

    # MODEL_INSTALLED_MATCH_v1: 실제 설치된 모델과 자동 매치 (404 'model not found' 사전 차단)
    try:
        from launcher.models import model_roles as _mri
        from .. import config as _cfgm
        if hasattr(_mri, "auto_match_installed"):
            _hosti = "127.0.0.1:" + str(getattr(_cfgm, "OLLAMA_PORT", 11434))
            _rn = None
            try:
                for _k, _l in getattr(_mri, "LADDERS", {}).items():
                    if any(_m == agent_model_tag for _m, _nb in _l):
                        _rn = _k
                        break
            except Exception:
                _rn = None
            _freei = None
            try:
                _freei = _mri.detect_free_memory_gb()
            except Exception:
                pass
            _matched, _note = _mri.auto_match_installed(agent_model_tag, _rn, _freei, host=_hosti)
            if _matched is None:
                p.error(_note or "설치된 모델이 없습니다 — MANAGE.bat [2] 에서 받으세요.")
                p.pause()
                return
            if _matched != agent_model_tag:
                p.warn(_note or ("설치된 " + _matched + " 로 자동 전환"))
                agent_model_tag = _matched
    except Exception:
        pass

    # ── 6) 명령 조립 ──
    run_mem, run_cpus = _resolve_resource_limits(env)
    container = config.SANDBOX_CONTAINER_PREFIX + "chat_" + secrets.token_hex(4)
    context_window = 4096
    try:
        from .. import runtime_guard
        rt = runtime_guard.compute_runtime_params()
        context_window = rt.context_window
    except Exception:
        pass

    _tor_on = (_uni.get("tor", False) if isinstance(_uni, dict)
               else (_select_internet_mode(p) if mode == "sandbox" else False))  # UNIFIED_ENTRY_v1
    cmd, is_host = _build_cmd_for_mode(
        mode, env, profile, workspace, container,
        context_window, run_mem, run_cpus,
        model_tag=agent_model_tag,
        tor_proxy=_tor_on,
    )
    if cmd is None:
        if is_host:
            p.error("Open Interpreter (호스트) 가 설치되지 않았습니다.")
            p.info("샌드박스 모드를 사용하거나 INSTALL 을 다시 실행하세요.")
        else:
            p.error("명령 조립 실패")
        p.pause()
        return

    # ── 7) GUI 통합 대화창 실행 (v7.0 스레드 마샬링) ──
    _v63_trace("_run_gui_chat 호출 직전 (통합)")
    _run_gui_chat_unified(env, p, profile, workspace, cmd, container, is_host,
                          run_mem, run_cpus, tor_proxy=_tor_on)  # HOST_TOR_ENV_v1
    _v63_trace("_run_gui_chat 반환됨 (통합)")


def _net_mode_label(cmd):  # NETMODE_LOG_v1
    j = " ".join(str(c) for c in cmd)
    if "--dns=0.0.0.0" in j:
        return "차단 (인터넷 없음)"
    if "socks5h://" in j or "ALL_PROXY=" in j or "HTTP_PROXY=" in j:
        return "Tor 경유"
    return "개방 (직접 연결)"


def _net_flags(cmd):  # NETMODE_LOG_v1
    toks = [str(c) for c in cmd]
    out = []
    for i, t in enumerate(toks):
        if t == "--dns=0.0.0.0" or t.startswith("--add-host"):
            out.append(t)
        elif t == "-e" and i + 1 < len(toks) and "PROXY" in toks[i + 1]:
            out.append(toks[i + 1])
    return " ".join(out) if out else "(네트워크 플래그 없음)"


def _run_gui_chat_unified(env, p, profile, workspace, cmd, container, is_host,
                          run_mem, run_cpus, tor_proxy=False):  # HOST_TOR_ENV_v1
    """통합 GUI 대화창 — 샌드박스/호스트 공통.

    v7_0_threadfix 스레드 마샬링 내장.
    """
    from launcher.agent.agent_runner import UnifiedAgent
    from launcher.agent.agent_runner import LEVEL_TERMINATED
    from ..presenter.gui.chat_panel import ChatPanel

    main_window = getattr(p, "_window", None)
    if main_window is None:
        p.error("GUI 환경이 아닙니다.")
        p.pause()
        return

    agent = UnifiedAgent()

    # 호스트 모드면 lifelog 에 프로세스 정리 등록
    if is_host:
        try:
            from launcher.core import lifelog as _ll
            if hasattr(_ll, "register_host_process_cleanup"):
                def _get_pid():
                    try:
                        proc = getattr(agent, "_proc", None)
                        return proc.pid if proc else None
                    except Exception:
                        return None
                _ll.register_host_process_cleanup(_get_pid)
        except Exception:
            pass

    panel_holder = {"panel": None}
    nonlocal_container = [container]

    def build_panel(parent):
        mode_label = "호스트 직접 (위험)" if is_host else "샌드박스 (격리)"
        _plabel = getattr(profile, "label", None) or getattr(profile, "name", "에이전트")
        panel = ChatPanel(
            parent,
            title="에이전트 대화 — " + str(_plabel),
            subtitle="모드: " + mode_label + "  |  마운트: " + str(workspace),
            workspace=workspace,
        )
        try:  # MODEL_DISPLAY_v1: 현재 모델을 드롭다운 라벨에 표시
            _mc0 = list(cmd)
            if "--model" in _mc0:
                _mt0 = _mc0[_mc0.index("--model") + 1]
                if isinstance(_mt0, str) and _mt0.startswith("ollama/"):
                    _mt0 = _mt0[len("ollama/"):]
                if hasattr(panel, "set_current_model"):
                    panel.set_current_model(_mt0)
        except Exception:
            pass

        # FOLDER_POLICY_LIVE_v1: 세션 중 허용/금지 폴더 변경 + 컨테이너 재기동(대화 보존)
        _cmd_holder = [cmd]

        def _post(level, txt):
            try:
                panel.append_message(level, txt)
            except Exception:
                pass

        def _rebuild_policy_cmd(base):
            # base 에서 기존 allowed 마운트/tmpfs 마스크 제거 -> 현재 정책으로 재삽입 + --name 회전
            out = []
            i = 0
            while i < len(base):
                t = base[i]
                if t == "-v" and i + 1 < len(base) and ":/home/agent/allowed/" in base[i + 1]:
                    i += 2
                    continue
                if t == "--tmpfs" and i + 1 < len(base) and base[i + 1].startswith("/home/agent/allowed/"):
                    i += 2
                    continue
                out.append(t)
                i += 1
            new_name = config.SANDBOX_CONTAINER_PREFIX + "chat_" + secrets.token_hex(4)
            try:
                ni = out.index("--name")
                out[ni + 1] = new_name
                insert_at = ni + 2
            except (ValueError, IndexError):
                try:
                    insert_at = out.index("run") + 1
                except ValueError:
                    insert_at = len(out)
            fresh = []
            try:
                from launcher.agent import folder_policy as _fp
                for _h, _c in _fp.mounts_for():
                    fresh += ["-v", _h + ":" + _c]
                if hasattr(_fp, "tmpfs_masks_for"):
                    for _m in _fp.tmpfs_masks_for():
                        fresh += ["--tmpfs", _m]
            except Exception:
                pass
            out[insert_at:insert_at] = fresh
            # FOLDER_WS_RELOAD_v1: 시스템 메시지(허용 폴더 안내)도 현재 정책으로 갱신
            try:
                from launcher.agent import profiles as _profiles
                _sm = profile.system_message + _profiles.build_session_addendum(workspace)
                _si = out.index("--system_message")
                out[_si + 1] = _sm
            except Exception:
                pass
            return out, new_name

        def _allowed_sig(c):  # FOLDER_WS_RELOAD_v1: 허용 마운트/마스크 집합의 서명
            sig = []
            i = 0
            while i < len(c):
                if c[i] == "-v" and i + 1 < len(c) and ":/home/agent/allowed/" in c[i + 1]:
                    sig.append("v:" + c[i + 1])
                    i += 2
                    continue
                if c[i] == "--tmpfs" and i + 1 < len(c) and c[i + 1].startswith("/home/agent/allowed/"):
                    sig.append("t:" + c[i + 1])
                    i += 2
                    continue
                i += 1
            return sorted(sig)

        def _restart_apply():
            if is_host:
                _post("warn", "호스트 모드는 폴더 격리가 없어 재기동으로 바뀌지 않습니다. 세션을 다시 시작하세요.")
                return
            try:
                new_cmd, _name = _rebuild_policy_cmd(_cmd_holder[0])
            except Exception as _e:
                _post("error", "정책 반영 실패: " + str(_e))
                return
            if _allowed_sig(new_cmd) == _allowed_sig(_cmd_holder[0]):  # FOLDER_WS_RELOAD_v1
                _post("system", "[변경 없음 - 재기동 생략] 현재 마운트 유지")
                return
            _cmd_holder[0] = new_cmd
            _nmounts = sum(1 for _x in new_cmd if _x == "-v")
            _post("system", "[정책 반영 - 컨테이너 재기동...] 마운트 " + str(_nmounts) + "개")
            try:
                agent.stop(timeout=2.0)
            except Exception:
                pass
            agent.start(new_cmd)
            try:
                panel.enable_send()
            except Exception:
                pass
            try:
                panel.refresh_files(workspace)
            except Exception:
                pass

        def _policy_summary_text():
            try:
                from launcher.agent import folder_policy as _fp
                al = _fp.list_allowed()
                dl = _fp.list_denied()
                lines = ["[허용]"] + (["  " + x for x in al] if al else ["  (없음)"])
                lines += ["[금지]"] + (["  " + x for x in dl] if dl else ["  (없음)"])
                lines += ["마운트 예정 " + str(len(_fp.mounts_for())) + "개 · 변경 반영: /reload"]
                return "\n".join(lines)
            except Exception as _e:
                return "정책 조회 실패: " + str(_e)

        def _handle_slash(text):
            s = (text or "").strip()
            if not s.startswith("/"):
                return False
            parts = s.split(None, 1)
            c0 = parts[0].lower()
            arg = parts[1].strip().strip('"').strip("'") if len(parts) > 1 else ""
            if c0 in ("/help", "/?", "/명령"):
                _post("system",
                      "폴더 명령: /folders 목록 · /allow <경로> · /deny <경로> · "
                      "/unallow <경로> · /undeny <경로> · /reload 변경반영 · /model <태그> 모델변경")
                return True
            try:
                from launcher.agent import folder_policy as _fp
            except Exception:
                _post("error", "folder_policy 를 불러올 수 없습니다")
                return True
            if c0 in ("/folders", "/폴더", "/list"):
                _post("system", _policy_summary_text())
                return True
            if c0 in ("/reload", "/적용", "/remount"):
                _restart_apply()
                return True
            if c0 in ("/model", "/모델"):  # ENTRY_INWINDOW_v1
                if not arg:
                    _post("system", "사용법: /model <태그>  예: /model qwen2.5-coder:7b")
                    return True
                _cnew = list(_cmd_holder[0])
                if "--model" in _cnew:
                    _mi = _cnew.index("--model")
                    if _mi + 1 < len(_cnew):
                        _cnew[_mi + 1] = "ollama/" + arg
                    _cmd_holder[0] = _cnew
                    _post("system", "[모델 변경 - 컨테이너 재기동...] " + arg)
                    try:
                        agent.stop(timeout=2.0)
                    except Exception:
                        pass
                    try:
                        agent.start(_cnew)
                        _post("system", "모델 변경 완료: " + arg + "  (첫 응답은 적재로 다소 걸릴 수 있음)")
                    except Exception as _e:
                        _post("error", "모델 변경 실패: " + str(_e))
                    try:
                        panel.enable_send()
                    except Exception:
                        pass
                else:
                    _post("error", "현재 명령에 --model 이 없어 변경할 수 없습니다.")
                return True
            if c0 in ("/allow", "/허용"):
                if not arg:
                    _post("warn", "사용법: /allow <폴더경로>")
                    return True
                r = _fp.add_allowed(arg)
                _post("system", {"ok": "허용 추가됨: " + arg + "  (반영: /reload)",
                                 "exists": "이미 허용에 있음",
                                 "denied": "금지 목록과 충돌 - 추가 불가",
                                 "fail": "저장 실패"}.get(r, str(r)))
                return True
            if c0 in ("/deny", "/금지"):
                if not arg:
                    _post("warn", "사용법: /deny <폴더경로>")
                    return True
                r = _fp.add_denied(arg)
                _post("system", {"ok": "금지 추가됨: " + arg + "  (반영: /reload)",
                                 "exists": "이미 금지에 있음",
                                 "fail": "저장 실패"}.get(r, str(r)))
                return True
            if c0 in ("/unallow", "/허용해제"):
                if not arg:
                    _post("warn", "사용법: /unallow <폴더경로>")
                    return True
                _post("system", ("허용 제거됨: " + arg + "  (반영: /reload)") if _fp.remove_allowed(arg) else "저장 실패")
                return True
            if c0 in ("/undeny", "/금지해제"):
                if not arg:
                    _post("warn", "사용법: /undeny <폴더경로>")
                    return True
                _post("system", ("금지 제거됨: " + arg + "  (반영: /reload)") if _fp.remove_denied(arg) else "저장 실패")
                return True
            _post("warn", "알 수 없는 명령: " + c0 + "  (/help)")
            return True

        def on_user_input(text):
            if _handle_slash(text):
                return
            ok = agent.send_input(text)
            if not ok:
                panel.append_message("warn", "에이전트가 실행 중이 아닙니다")

        def on_stop():
            panel.append_message("system", "[중단 요청...]")
            agent.stop(timeout=2.0)
            panel.disable_send()

        def on_restart():
            panel.append_message("system", "[재시작 요청...]")
            agent.stop(timeout=2.0)
            if not is_host:
                try:
                    new_cmd, _ = _rebuild_policy_cmd(_cmd_holder[0])  # FOLDER_POLICY_LIVE_v1
                    _cmd_holder[0] = new_cmd
                except Exception:
                    pass
            _renv = None  # HOST_TOR_ENV_v1
            if is_host and tor_proxy:
                try:
                    from launcher.agent.agent_runner import build_tor_env
                    _renv = build_tor_env()
                except Exception:
                    _renv = None
            agent.start(_cmd_holder[0], env=_renv)
            panel.enable_send()

        def on_open():
            _open_folder_in_explorer(workspace)

        panel.set_input_callback(on_user_input)
        panel.set_stop_callback(on_stop)
        panel.set_restart_callback(on_restart)
        panel.set_open_folder_callback(on_open)
        panel.refresh_files(workspace)
        panel.set_status(
            "프로필: " + str(_plabel) + "\n"
            "모드: " + mode_label + "\n"
            "메모리: " + str(run_mem).upper() + "\n"
            "CPU: " + str(run_cpus) + " 코어"
        )
        panel_holder["panel"] = panel
        return panel

    # v7_0_threadfix: ChatPanel 생성을 메인 스레드로 마샬링
    import threading as _thr
    _panel_ready = _thr.Event()
    _build_error = [None]

    def _build_on_main():
        try:
            from launcher.core import lifelog as _ll
            _ll.log("TRACE", "[agent_chat] (메인) host.replace 시작")
        except Exception:
            pass
        try:
            main_window.host.replace(build_panel)
        except Exception as _e:
            _build_error[0] = _e
            try:
                import traceback as _tb
                from launcher.core import lifelog as _ll2
                _ll2.log("FAIL", "[agent_chat] host.replace 예외: " + repr(_e))
                _ll2.log("DEBUG", _tb.format_exc())
            except Exception:
                pass
        finally:
            _panel_ready.set()
            try:
                from launcher.core import lifelog as _ll3
                _ll3.log("TRACE", "[agent_chat] (메인) host.replace 종료")
            except Exception:
                pass

    try:
        main_window.root.after(0, _build_on_main)
    except Exception:
        _build_on_main()

    if not _panel_ready.wait(timeout=10.0):
        try:
            from launcher.core import lifelog as _ll
            _ll.log("FAIL", "[agent_chat] 통합 패널 생성 10초 타임아웃")
        except Exception:
            pass
        return
    if _build_error[0] is not None:
        try:
            from launcher.core import lifelog as _ll
            _ll.log("FAIL", "[agent_chat] 패널 생성 예외로 중단: "
                   + repr(_build_error[0]))
            p.error("대화창 생성 실패: " + str(_build_error[0]))
            p.pause()
        except Exception:
            pass
        return

    panel = panel_holder["panel"]
    if panel is None:
        return

    # 메인 스레드 마샬링 append
    def _safe_append(level, txt):
        try:
            main_window.root.after(0, lambda: panel.append_message(level, txt))
        except Exception:
            try:
                panel.append_message(level, txt)
            except Exception:
                pass

    try:
        _pl = getattr(profile, "label", None) or getattr(profile, "name", "에이전트")
    except Exception:
        _pl = "에이전트"
    _safe_append("system", "에이전트를 시작합니다... (프로필: " + str(_pl) + ")")
    _safe_append("system", "폴더 명령: /folders 목록 · /allow <경로> · /deny <경로> · /reload 반영  (/help)")  # FOLDER_POLICY_LIVE_v1
    try:  # SESSION_HINT_v1
        from launcher.core import user_data as _udh
        import glob as _glbh
        _nsess = len(_glbh.glob(os.path.join(str(_udh.interpreter_dir("sandbox")),
                                              "session_*.json")))
        if _nsess > 0:
            _safe_append("system", "이전 대화 %d개 저장됨 — 우측 [이전 대화] 버튼으로 "
                         "이어갈 수 있습니다." % _nsess)
    except Exception:
        pass
    if is_host:
        _safe_append("warn", "호스트 직접 모드 — 매 명령 확인이 필요합니다")
    try:
        from launcher.core import lifelog as _ll
        _ll.log("TRACE", "[agent_chat] agent.start 호출 직전")
        _ll.log("INFO", "[agent_chat] 명령: " + " ".join(str(c) for c in cmd[:8]))
        _ll.log("INFO", "[agent_chat] 인터넷 모드: " + _net_mode_label(cmd)
                + " | " + _net_flags(cmd))  # NETMODE_LOG_v1
    except Exception:
        pass
    try:
        _safe_append("system", "[인터넷] " + _net_mode_label(cmd)
                     + "  (" + _net_flags(cmd) + ")")  # NETMODE_LOG_v1
    except Exception:
        pass
    if not is_host and _net_mode_label(cmd) == "Tor 경유":  # TOR_AUTOSTART_v1
        try:
            try:
                from .. import tor_runtime as _tr
            except Exception:
                from launcher import tor_runtime as _tr
            def _qlog(m):  # TOR_QUIET_v1: 준비 과정은 로그 파일로만
                try:
                    try:
                        from ..core import lifelog as _llq
                    except Exception:
                        from launcher.core import lifelog as _llq
                    _llq.log("INFO", "[tor/docker] " + str(m))
                except Exception:
                    pass
            try:  # TOR_DOCKER_ORDER_v1: Tor 는 Docker 필요 -> 데몬 먼저 보장
                from ..services.docker import DockerService as _DSt
                if not _DSt.daemon_alive():
                    _qlog("Docker 데몬 확인 중 (Tor 준비)...")
                    _safe_append("system", "환경 준비 중... (최대 1분)")
                    class _DLt:
                        def info(self, m): _qlog(m)
                        def ok(self, m): _qlog(m)
                        def warn(self, m): _qlog(m)
                        def error(self, m): _safe_append("error", str(m))
                    _DSt.ensure_daemon(logger=_DLt(), timeout=90)
            except Exception:
                pass
            try:  # DOCKER_READY_v1: 데몬 응답 != 런타임 준비 -> docker ps 성공까지 대기
                import subprocess as _spR, time as _tmR
                _ready = False
                for _i in range(20):
                    try:
                        if _spR.run(["docker", "ps"], capture_output=True, timeout=10, creationflags=(0x08000000 if os.name == "nt" else 0)).returncode == 0:
                            _ready = True
                            break
                    except Exception:
                        pass
                    if _i == 0:
                        _safe_append("system", "환경 준비 중... (최대 1분)")
                    _qlog("Docker 런타임 준비 대기 %d" % _i)
                    _tmR.sleep(3)
                if not _ready:
                    _safe_append("warn", "Docker 런타임이 아직 준비되지 않았습니다. 잠시 후 다시 시도하세요.")
            except Exception:
                pass
            try:  # OLLAMA_READY_v1: 재시작 churn 후 Ollama 응답까지 대기
                import urllib.request as _urqO, time as _tmO
                _oport = 11434
                try:
                    from .. import config as _cfgO
                    _oport = int(getattr(_cfgO, "OLLAMA_PORT", 11434))
                except Exception:
                    pass
                _ourl = "http://127.0.0.1:%d/api/version" % _oport
                _oready = False
                for _i in range(20):
                    try:
                        _urqO.urlopen(_ourl, timeout=5).read()
                        _oready = True
                        break
                    except Exception:
                        pass
                    if _i == 0:
                        _safe_append("system", "Ollama 준비 확인 중...")
                    _qlog("Ollama 응답 대기 %d" % _i)
                    _tmO.sleep(3)
                if not _oready:
                    _safe_append("warn", "Ollama 가 응답하지 않습니다 (127.0.0.1:%d). Ollama 를 먼저 실행하세요." % _oport)
            except Exception:
                pass
            _qlog("Tor 프록시 확인/기동 중... (9050)")  # TOR_QUIET_v1
            _tor_ok = _tr.start(env, log=_qlog)
            if _tor_ok:
                _qlog("Tor 경유 준비 완료 — 외부 트래픽이 Tor 로 우회됩니다.")
            else:
                _safe_append("warn", "Tor 미기동 — 대시보드 'Tor 이미지 받기'로 이미지를 "
                             "받았는지 확인하세요. 지금은 외부 인터넷 연결이 실패할 수 있습니다.")
        except Exception as _e_tor:
            _safe_append("warn", "Tor 기동 예외: %r" % _e_tor)

    # v8_3_dockergate: Docker 미응답 시 Docker Desktop 자동 시작 후 대기 (수동 시작 불필요)
    if not is_host:
        try:
            from ..services.docker import DockerService as _DS
            if not _DS.daemon_alive():
                _safe_append("system", "Docker 데몬이 응답하지 않습니다 — Docker Desktop 자동 시작 시도 중...")
                _safe_append("warn", "완전히 켜질 때까지 30초~1분 걸릴 수 있습니다. 잠시만 기다려 주세요.")
                class _DLog:
                    def info(self, m): _safe_append("system", str(m))
                    def ok(self, m): _safe_append("system", str(m))
                    def warn(self, m): _safe_append("warn", str(m))
                    def error(self, m): _safe_append("error", str(m))
                if _DS.ensure_daemon(logger=_DLog(), timeout=90):
                    _safe_append("system", "Docker 준비 완료 — 에이전트를 시작합니다.")
                else:
                    _safe_append("error", "Docker 를 시작하지 못했습니다. Docker Desktop 을 직접 켠 뒤 [재시작] 을 누르세요.")
        except Exception:
            pass

    # PREWARM_UI_v1: 모델 적재/롤백을 대화창(워커 스레드)에서 진행 표시
    if not is_host:
        try:
            from .. import model_roles as _mrp
            if "--model" in cmd:
                _mi = cmd.index("--model")
                if _mi + 1 < len(cmd) and str(cmd[_mi + 1]).startswith("ollama/"):
                    _curtag = str(cmd[_mi + 1])[len("ollama/"):]
                    _role = None
                    for _kk, _lad in getattr(_mrp, "LADDERS", {}).items():
                        if any(_m == _curtag for _m, _n in _lad):
                            _role = _kk
                            break
                    if _role and hasattr(_mrp, "resolve_with_rollback"):
                        _safe_append("system", "모델 적재 확인 중... (여유 메모리 점검 · 최초 1회 다소 걸릴 수 있음)")

                        class _PWPresenter:
                            def warn(self, _m):
                                _safe_append("warn", str(_m))

                            def info(self, _m):
                                _safe_append("system", str(_m))

                        try:
                            _free_pw = _mrp.detect_free_memory_gb()
                        except Exception:
                            _free_pw = None
                        _rolled = _mrp.resolve_with_rollback(_role, _free_pw, presenter=_PWPresenter())
                        if _rolled and _rolled != _curtag:
                            cmd[_mi + 1] = "ollama/" + _rolled
                            _safe_append("system", "적재 실패 감지 -> " + _rolled + " 로 자동 변경")
                        else:
                            _safe_append("system", "모델 적재 확인 완료: " + _curtag)
        except Exception:
            pass

    try:  # SYSMSG_FILE_v1: 긴 시스템 메시지를 파일로 (WinError 206 방지)
        if "--system_message" in cmd and any("/home/agent/.agent_state" in str(_x) for _x in cmd):
            _si = cmd.index("--system_message")
            if _si + 1 < len(cmd) and not str(cmd[_si + 1]).startswith("@FILE:") and len(str(cmd[_si + 1])) > 1500:
                from ..core import user_data as _udS
                import os as _osS
                _sdir = str(_udS.interpreter_dir("sandbox"))
                _osS.makedirs(_sdir, exist_ok=True)
                _spath = _osS.path.join(_sdir, "system_message.txt")
                with open(_spath, "w", encoding="utf-8") as _sf:
                    _sf.write(str(cmd[_si + 1]))
                cmd[_si + 1] = "@FILE:/home/agent/.agent_state/system_message.txt"
    except Exception:
        pass
    try:  # PRETOOL_PATH_v1: PreTool 를 모든 코드블록에서 import 가능하게
        if any("/home/agent/.agent_state" in str(_xp) for _xp in cmd) \
                and not any("PYTHONPATH=" in str(_xp) for _xp in cmd):
            _pos = (cmd.index("--rm") + 1) if "--rm" in cmd else (cmd.index("run") + 1 if "run" in cmd else 2)
            cmd[_pos:_pos] = ["-e", "PYTHONPATH=/home/agent/.agent_state"]
    except Exception:
        pass
    try:  # PRETOOL_SYNC_v1: PreTool/sitecustomize 를 실제 마운트 폴더로 복사
        from ..core import user_data as _udP
        import os as _osP, shutil as _shP
        _dstP = str(_udP.interpreter_dir("sandbox"))
        _rootP = _osP.path.dirname(_osP.path.dirname(_osP.path.dirname(_osP.path.abspath(__file__))))
        _srcP = _osP.path.join(_rootP, "PreTool")
        if _osP.path.isdir(_srcP):
            _shP.copytree(_srcP, _osP.path.join(_dstP, "PreTool"), dirs_exist_ok=True)
            _scS = _osP.path.join(_srcP, "sitecustomize.py")
            if _osP.path.exists(_scS):
                _shP.copy2(_scS, _osP.path.join(_dstP, "sitecustomize.py"))
    except Exception:
        pass
    try:  # SEARXNG_AUTOSTART_v1: 로컬 검색엔진 기동(web_search 가 8888 로 붙음)
        if any("HTTP_PROXY=" in str(_xs) or "--add-host" in str(_xs) for _xs in cmd):
            from .. import searxng_runtime as _sxr
            def _sxlog(m):
                try:
                    try:
                        from ..core import lifelog as _llx
                    except Exception:
                        from launcher.core import lifelog as _llx
                    _llx.log("INFO", "[searxng] " + str(m))
                except Exception:
                    pass
            if not _sxr.is_running():
                _safe_append("system", "로컬 검색엔진(SearXNG) 준비 중...")
                _sxlog("SearXNG 기동 시도")
                try:
                    _sxok = _sxr.start(env, log_path=None)
                    _sxlog("SearXNG 기동 %s" % ("완료" if _sxok else "실패(폴백 사용)"))
                except Exception as _esx:
                    _sxlog("SearXNG 기동 예외: %s" % _esx)
    except Exception:
        pass
    try:  # AGENT_NET_v1: 공유 네트워크로 Tor/SearXNG 를 컨테이너명으로 도달
        if any("--add-host" in str(_xn) for _xn in cmd):
            import subprocess as _spN
            _NET = os.environ.get("LLM_NETWORK", "llm_net")
            _nw = (0x08000000 if os.name == "nt" else 0)
            try:
                _ri = _spN.run(["docker", "network", "inspect", _NET], capture_output=True, timeout=10, creationflags=_nw)
                if _ri.returncode != 0:
                    _spN.run(["docker", "network", "create", _NET], capture_output=True, timeout=15, creationflags=_nw)
            except Exception:
                pass
            for _cn in ("llm_tor", "llm_searxng"):  # NET_CONNECT_RETRY_v1: Removing 레이스 흡수
                import time as _tR
                _joined = False
                _last = ""
                for _try in range(8):  # 최대 ~8초: Removing -> Removed -> 재생성 창 흡수
                    try:
                        _rcC = _spN.run(["docker", "network", "connect", _NET, _cn],
                                        capture_output=True, timeout=10, creationflags=_nw)
                        _errC = (_rcC.stderr or b"").decode("utf-8", "ignore").strip()
                    except Exception as _eC:
                        _rcC = None
                        _errC = str(_eC)
                    _low = _errC.lower()
                    if (_rcC is not None and _rcC.returncode == 0) or ("already" in _low):
                        _joined = True
                        break
                    _last = _errC
                    _transient = any(_s in _low for _s in (
                        "marked for removal", "being removed", "removal in progress",
                        "no such container", "is not running", "not found", "notfound"))
                    if not _transient:
                        break
                    if _cn == "llm_tor" and ("no such container" in _low or "not found" in _low):
                        try:  # 프록시 핵심 컨테이너 소멸 시 멱등 재기동
                            from .. import tor_runtime as _trR
                            _trR.start(env)
                        except Exception:
                            pass
                    _tR.sleep(1.0)
                if _joined:
                    _safe_append("system", "[net] %s -> %s 연결 OK" % (_cn, _NET))
                elif _cn == "llm_tor":
                    _safe_append("warn", "[net] %s 연결 재확인 실패: %s (검색 불안정 가능 - Tor 이미지/기동 확인)" % (_cn, (_last or "?")[:120]))
                else:
                    _safe_append("system", "[net] %s 연결 생략: %s" % (_cn, (_last or "?")[:80]))
            if "--network" not in cmd:
                _posN = (cmd.index("--rm") + 1) if "--rm" in cmd else 2
                cmd[_posN:_posN] = ["--network", _NET]
            for _iN in range(len(cmd)):
                _vN = str(cmd[_iN])
                if "host.docker.internal:8118" in _vN or "host.docker.internal:9050" in _vN:
                    cmd[_iN] = _vN.replace("host.docker.internal:8118", "llm_tor:8118").replace("host.docker.internal:9050", "llm_tor:9050")
    except Exception:
        pass
    _start_env = None  # HOST_TOR_ENV_v1
    if is_host and tor_proxy:
        try:
            from launcher.agent.agent_runner import build_tor_env
            _start_env = build_tor_env()
            _safe_append("system", "[net] 호스트 인터프리터 Tor 프록시 적용 (127.0.0.1:8118 / 9050)")
        except Exception as _ete:
            _safe_append("warn", "[net] Tor env 적용 실패: %s" % _ete)
    started = agent.start(cmd, env=_start_env)
    try:
        from launcher.core import lifelog as _ll2
        _ll2.log("TRACE", "[agent_chat] agent.start 반환: " + str(started))
    except Exception:
        pass
    if not started:  # AGENT_RETRY_v1: 일시적 실패(도커 재시작 직후 등) 재시도
        import time as _trR
        for _rai in range(2):
            _safe_append("system", "에이전트 재시도 중... (%d/2)" % (_rai + 1))
            _trR.sleep(3)
            try:
                started = agent.start(cmd, env=_start_env)  # HOST_TOR_ENV_v1
            except Exception:
                started = False
            if started:
                _safe_append("system", "재시도 성공 — 에이전트를 시작합니다.")
                break
    if not started:
        _safe_append("error", "에이전트 시작 실패. Docker/Ollama 상태를 확인하세요.")
        try:  # START_DIAG_v1: 실제 원인 진단(프록시 우회)
            import urllib.request as _urqD, json as _jsnD, subprocess as _spD
            _oport = 11434
            try:
                from .. import config as _cfgD
                _oport = int(getattr(_cfgD, "OLLAMA_PORT", 11434))
            except Exception:
                pass
            try:
                _opn = _urqD.build_opener(_urqD.ProxyHandler({}))
                _d = _jsnD.loads(_opn.open("http://127.0.0.1:%d/api/tags" % _oport, timeout=5).read().decode("utf-8"))
                _ms = [m.get("name") or m.get("model") for m in (_d.get("models") or [])]
                if _ms:
                    _safe_append("system", "진단: Ollama 설치 모델 %d개 (%s)" % (len(_ms), ", ".join([x for x in _ms[:5] if x])))
                else:
                    _safe_append("error", "진단: Ollama 에 설치된 모델이 0개입니다 — MANAGE.bat [2] 모델 관리에서 받으세요.")
            except Exception as _eD:
                _safe_append("error", "진단: Ollama 무응답 (127.0.0.1:%d) — Ollama 를 먼저 실행하세요." % _oport)
            try:
                _img = "llm-agent-sandbox"
                try:
                    from .. import config as _cfgD2
                    _img = getattr(_cfgD2, "SANDBOX_IMAGE", _img)
                except Exception:
                    pass
                if _spD.run(["docker", "image", "inspect", _img], capture_output=True, timeout=10, creationflags=(0x08000000 if os.name == "nt" else 0)).returncode != 0:
                    _safe_append("error", "진단: 샌드박스 이미지 '%s' 없음 — 이미지를 빌드/받으세요." % _img)
            except Exception:
                pass
            try:  # START_DIAG2_v1: 컨테이너 실제 출력/오류 캡처
                import subprocess as _spC
                _rcC = _spC.run(cmd, stdin=_spC.DEVNULL, stdout=_spC.PIPE, stderr=_spC.STDOUT,
                                timeout=15, creationflags=(0x08000000 if os.name == "nt" else 0))
                _outC = (_rcC.stdout or b"").decode("utf-8", "ignore").strip()
                if _outC:
                    _safe_append("error", "진단(컨테이너 출력, rc=%s): %s" % (_rcC.returncode, _outC[-600:]))
                else:
                    _safe_append("system", "진단: 컨테이너가 출력 없이 종료 (rc=%s) — 이미지/엔트리포인트 확인" % _rcC.returncode)
            except Exception as _eC:
                _safe_append("system", "진단: 컨테이너 재현 실패: %s" % _eC)
        except Exception:
            pass
        try:
            from launcher.core import lifelog as _ll3
            _ll3.log("FAIL", "[agent_chat] agent.start 실패")
        except Exception:
            pass
        return

    # 폴링 루프
    poll_interval_ms = 80
    files_refresh_counter = [0]

    def poll():
        try:
            msgs = agent.drain_messages(max_n=100)
            for m in msgs:
                if m.level == LEVEL_TERMINATED:
                    panel.append_message("terminated", m.text)
                    panel.disable_send()
                else:
                    panel.append_message(m.level, m.text)
            files_refresh_counter[0] += 1
            if files_refresh_counter[0] >= 25:
                files_refresh_counter[0] = 0
                panel.refresh_files(workspace)
        except Exception:
            pass
        try:
            main_window.root.after(poll_interval_ms, poll)
        except Exception:
            pass

    main_window.root.after(poll_interval_ms, poll)

