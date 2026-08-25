"""i18n — 다국어 메시지 (installer + launcher 공용).

사용:
    from installer.i18n import t, set_language
    print(t("install.start"))

언어 변경:
    set_language("ko")  # 한국어
    set_language("en")  # 영어

영속화:
    launcher/settings/user_config.json 의 'language' 필드.
    설치 단계에서 묻고, 실행 단계에서도 메뉴 [8]에서 변경 가능.

새 메시지 추가:
    1. _MESSAGES dict 의 모든 언어에 키 추가
    2. 누락된 언어는 자동으로 영어로 폴백
"""
from __future__ import annotations

import os
from typing import Dict


# ─── 지원 언어 ───
SUPPORTED_LANGUAGES = ("en", "ko")
DEFAULT_LANGUAGE = "en"

# 환경변수로 강제 설정 가능 (RUN.bat / INSTALL.bat 가 사용)
ENV_VAR = "LLM_LOCAL_SETUP_LANG"

_current_lang = os.environ.get(ENV_VAR, DEFAULT_LANGUAGE)
if _current_lang not in SUPPORTED_LANGUAGES:
    _current_lang = DEFAULT_LANGUAGE


def set_language(lang: str):
    """현재 언어 변경. 지원 안 하는 코드면 무시."""
    global _current_lang
    if lang in SUPPORTED_LANGUAGES:
        _current_lang = lang


def get_language() -> str:
    return _current_lang


def t(key: str, **kwargs) -> str:
    """번역. 키 미정의 시 키 자체 반환. {var} 포맷팅 지원."""
    msgs = _MESSAGES.get(_current_lang, {})
    text = msgs.get(key)
    if text is None:
        # 폴백: 영어
        text = _MESSAGES.get(DEFAULT_LANGUAGE, {}).get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


# ──────────────────────────────────────────────────────────────
# 메시지 사전
# ──────────────────────────────────────────────────────────────
# 키 명명 규칙: <영역>.<용도>
#   common.*    : 공통 (info/ok/warn/err 라벨, yes/no 등)
#   lang.*      : 언어 선택 메뉴
#   install.*   : 설치 단계
#   menu.*      : run.py 메인 메뉴
#   chat.*      : 채팅 UI
#   agent.*     : 에이전트
#   sandbox.*   : 샌드박스 옵션
#   searxng.*   : SearXNG 제어
#   settings.*  : 설정 관리
#   guard.*     : 자원 가드
# ──────────────────────────────────────────────────────────────

_MESSAGES: Dict[str, Dict[str, str]] = {

# ════════════════════════════════════════════════════════════
"en": {
    # ── 공통 ──
    "common.continue": "Press Enter to continue...",
    "common.exit_prompt": "Press Enter to exit...",
    "common.back": "Back",
    "common.quit": "Quit",
    "common.yes": "Yes",
    "common.no": "No",
    "common.ok": "OK",

    # ── 언어 선택 ──
    "lang.select_title": "Select language / 언어 선택",
    "lang.option_en": "English",
    "lang.option_ko": "한국어 (Korean)",
    "lang.prompt": "Choice [1/2]: ",
    "lang.saved": "Language set to {lang}. You can change this later in Settings.",

    # ── 설치 시작 ──
    "install.title": "LLM Integrated Environment Installer (Windows / Portable)",
    "install.location": "Install location: {path}",
    "install.python_ver": "Python: {ver}",

    # ── 사전 검사 ──
    "install.preflight_windows_ok": "Windows verified",
    "install.preflight_windows_fail": "Windows only (current: {os})",
    "install.preflight_python_ok": "Python {ver}",
    "install.preflight_python_fail": "Python {min_ver}+ required (current: {ver})",
    "install.preflight_disk_ok": "Disk free: {gb:.1f}GB",
    "install.preflight_disk_fail": "Insufficient disk space: {gb:.1f}GB / required {need}GB",
    "install.preflight_disk_unknown": "Could not check disk space — continuing",

    # ── 자원 감지 ──
    "install.resources_section": "System resource detection",
    "install.safety_profile": "Safety profile: {profile}",
    "install.cant_run_full": "System below recommended specs — some features may not work properly",
    "install.proceeding_in_5": "Continuing in 5 seconds...",

    # ── 환경 폴더 ──
    "install.create_dirs": "Creating role-based folders",

    # ── Ollama ──
    "install.ollama_section": "Ollama Portable Installation",
    "install.ollama_already": "Already installed: {path}",
    "install.ollama_extracting": "Extracting...",
    "install.ollama_done": "Portable install complete: {path}",
    "install.ollama_service_section": "Starting Ollama service",
    "install.ollama_running": "Already running on port 11434",
    "install.ollama_starting_bg": "Starting in background (log: {path})",
    "install.ollama_started": "Service confirmed ({sec}s)",
    "install.ollama_failed": "Ollama failed to start — check log",

    # ── 모델 ──
    "install.model_section": "Model download: {tag}",
    "install.model_size_warn": "About 14GB. Takes 10-60 minutes depending on network.",
    "install.model_try1": "Attempt 1: {tag}",
    "install.model_try2": "Attempt 2 (HuggingFace direct): {tag}",
    "install.model_done": "Download complete",
    "install.model_failed": "Both download paths failed",
    "install.model_manual": "Manual: ollama pull {tag}",

    # ── Python 도구 ──
    "install.webui_section": "Open WebUI installation (chat + web search)",
    "install.interpreter_section": "Open Interpreter installation (host direct mode)",
    "install.pip_upgrade": "Upgrading pip / wheel...",
    "install.pip_label_install": "Installing {label} (parallelism={jobs}, memory protection on)...",
    "install.pip_first_failed": "{label} first attempt failed (rc={rc}) — retrying with conservative mode",
    "install.pip_second_ok": "{label} conservative install succeeded",
    "install.pip_final_failed": "{label} final install failed (rc={rc})",
    "install.pip_manual": "Manual: {pip} install {package}",
    "install.tool_done": "Install complete: {path}",
    "install.webui_dep_warn": "Open WebUI has many dependencies — 5-20 minutes (longer on low-end systems)",

    # ── 샌드박스 ──
    "install.sandbox_section": "Docker sandbox installation",
    "install.docker_check_ok": "Docker ready",
    "install.dockerfile_written": "Dockerfile written: {path}",
    "install.image_build_section": "Image build: {name}",
    "install.image_build_warn": "Takes 5-10 minutes",
    "install.image_build_limits": "Build resource limits: memory {mem}, CPU {cpus} cores",
    "install.image_build_ok": "Image build complete",
    "install.image_build_fail": "Build failed",
    "install.image_skip": "Image build skipped (can build later from menu)",
    "install.sandbox_skip": "Skipping sandbox: {reason}",
    "install.sandbox_skip_later": "Run install again after Docker is set up",

    # ── SearXNG ──
    "install.searxng_section": "SearXNG (self-hosted search engine) installation",
    "install.searxng_config_dir": "Config folder: {path}",
    "install.searxng_settings_reused": "Existing settings.yml reused: {path}",
    "install.searxng_settings_created": "settings.yml created (SafeSearch=0): {path}",
    "install.searxng_limiter_created": "limiter.toml created: {path}",
    "install.searxng_pulling": "Pulling Docker image: {image}",
    "install.searxng_pull_size": "About 200MB. 1-3 minutes.",
    "install.searxng_pull_ok": "Image pull complete",
    "install.searxng_pull_fail": "Image pull failed",
    "install.searxng_ready": "SearXNG ready. Container: {name}, port: {port}",
    "install.searxng_skip": "Skipping SearXNG (Docker required): {reason}",
    "install.searxng_skip_optional": "Skipping SearXNG (--skip-search)",

    # ── 마무리 ──
    "install.complete": "Installation complete",
    "install.next_step": "Next step: run RUN.bat",
    "install.user_interrupt": "Interrupted by user",

    # ════════════════════════════════════════════════════════
    # ── run.py / 메뉴 ──
    "menu.no_install": "Installation folder not found: {path}",
    "menu.run_install_first": "Please run install first.",
    "menu.title": "LLM Environment Menu",
    "menu.install_path": "Install location: {path}",
    "menu.last_choice": "(last: {choice})",
    "menu.opt1": "Chat UI (Open WebUI)",
    "menu.opt1_desc": "Browser chat + automatic web search",
    "menu.opt2": "Automation Agent — Sandbox",
    "menu.opt2_recommended": "RECOMMENDED",
    "menu.opt2_desc": "Run inside Docker container with options",
    "menu.opt3": "Automation Agent — Host Direct",
    "menu.opt3_dangerous": "DANGEROUS",
    "menu.opt3_desc": "Direct host access. Explicit confirmation required.",
    "menu.opt4": "Ollama service start/check",
    "menu.opt5": "Installed model info",
    "menu.opt6": "Docker image build/rebuild",
    "menu.opt7": "SearXNG search engine control",
    "menu.opt8": "Settings (view/reset/language)",
    "menu.optq": "Quit",
    "menu.exiting": "Exiting.",

    # ── 채팅 UI ──
    "chat.title": "Chat UI start (Open WebUI + SearXNG)",
    "chat.webui_missing": "Open WebUI not installed: {path}",
    "chat.run_install_again": "Please run install again",
    "chat.searxng_starting": "Starting SearXNG search engine...",
    "chat.searxng_failed": "SearXNG start failed — continuing without search",
    "chat.searxng_not_installed": "SearXNG not installed — search disabled",
    "chat.searxng_install_hint": "(Re-run install to add SearXNG automatically)",
    "chat.searxng_connected": "Search auto-connected: {url}",
    "chat.browser_url": "Browser: http://localhost:8080",
    "chat.search_usage": "Use search: chat input + button -> 'Web Search' toggle",
    "chat.exit_hint": "Exit: Ctrl+C",

    # ── 에이전트 - 워크스페이스 ──
    "agent.workspace_title": "Sandbox agent — Select work folder",
    "agent.workspace_desc1": "This folder will be mounted at /home/agent/workspace inside the container.",
    "agent.workspace_desc2": "Files are exchanged between host and container through this folder.",
    "agent.workspace_last": "Last used: {path} (saved)",
    "agent.workspace_default": "Default: {path}",
    "agent.workspace_enter": "Enter: use the path above",
    "agent.workspace_input": "Type a path: mount different folder",
    "agent.workspace_back": "b: back",
    "agent.workspace_not_exist": "Folder does not exist: {path}",

    # ── 에이전트 - 샌드박스 ──
    "sandbox.image_missing_title": "Sandbox not ready",
    "sandbox.image_missing": "Docker image '{name}' not found",
    "sandbox.build_hint": "Build via main menu [6], or re-run install",
    "sandbox.options_title": "Sandbox agent — Options",
    "sandbox.options_subtitle": "Toggle by number, 'go' to run",
    "sandbox.options_help_safe": "Safe options restored from saved values (✓).",
    "sandbox.options_help_dangerous": "Dangerous options (⚠/⚠⚠) always start unchecked — explicit activation required each time.",
    "sandbox.mount_label": "Mount folder: {path}",
    "sandbox.mount_target": "            -> /home/agent/workspace",
    "sandbox.start_title": "Starting sandbox",
    "sandbox.final_command": "Final command:",
    "sandbox.exit_hint": "Exit: type 'exit' or Ctrl+D inside the container",

    # ── 옵션 라벨 ──
    "opt.isolation": "Container isolation (required)",
    "opt.isolation_desc": "Host system is protected from container changes",
    "opt.block_internet": "Block internet (DNS disabled)",
    "opt.block_internet_desc": "Block external domain resolution. Only host Ollama accessible.",
    "opt.cpu_limit": "CPU limit ({cpus} cores)",
    "opt.cpu_limit_desc": "Limit container CPU usage (protect system responsiveness)",
    "opt.memory_limit": "Memory limit ({mem})",
    "opt.memory_limit_desc": "Limit container memory (prevent swap thrash)",
    "opt.auto_run": "Auto-run (--auto_run)",
    "opt.auto_run_desc1": "Run every command without y/n confirmation.",
    "opt.auto_run_desc2": "Host is safe inside the sandbox.",
    "opt.allow_internet": "Allow internet",
    "opt.allow_internet_desc1": "Enables pip install / API calls.",
    "opt.allow_internet_desc2": "Agent can communicate with outside world.",
    "opt.allow_internet_desc3": "Increased risk of data leak / malicious downloads.",
    "opt.no_resource_limit": "Remove CPU/memory limits",
    "opt.no_resource_limit_desc1": "Run without resource limits.",
    "opt.no_resource_limit_desc2": "Runaway processes may temporarily freeze your PC.",
    "opt.privileged": "Privileged mode (host devices exposed)",
    "opt.privileged_desc1": "Grant container near host-level permissions.",
    "opt.privileged_desc2": "This greatly weakens isolation.",
    "opt.privileged_desc3": "Do not use unless for special debugging.",

    # ── 위험 옵션 확인 ──
    "checkbox.high_risk_header": "DANGEROUS OPTION ACTIVATION",
    "checkbox.medium_risk_header": "OPTION REQUIRING CAUTION",
    "checkbox.option_label": "Option: {label}",
    "checkbox.description": "Description:",
    "checkbox.high_warn": "This option may have serious system impact.",
    "checkbox.medium_warn": "This option carries additional risk.",
    "checkbox.type_keyword": "To activate, type exactly '{kw}'.",
    "checkbox.cancel_default": "Anything else cancels.",
    "checkbox.invalid_input": "Invalid input — type a number or command",
    "checkbox.out_of_range": "Out of range: {idx}",
    "checkbox.locked": "'{label}' is a locked item",
    "checkbox.cancelled": "'{label}' activation cancelled",
    "checkbox.help_toggle": "Number to toggle (e.g. '3' or '3 5')",
    "checkbox.help_commands": "go: run | b: back | q: quit",

    # ── 호스트 직접 모드 ──
    "agent.direct_title_warn": "HOST DIRECT EXECUTION MODE - VERY DANGEROUS",
    "agent.direct_intro": "This mode gives the agent direct access to your PC.",
    "agent.direct_risks": "Risks:",
    "agent.direct_risk1": "- Read/write/delete any file",
    "agent.direct_risk2": "- Execute system commands (including format, shutdown)",
    "agent.direct_risk3": "- Free network usage",
    "agent.direct_risk4": "- No isolation — model mistakes affect PC directly",
    "agent.direct_alternative": "Alternative: Menu [2] sandbox does almost the same things safely.",
    "agent.direct_confirm_prompt": "To continue, type exactly '{kw}':",
    "agent.direct_confirm_strict": "(Exact case-sensitive match required, anything else cancels)",
    "agent.direct_cancelled": "Cancelled (recommended: use menu [2] sandbox mode)",
    "agent.direct_interpreter_missing": "Open Interpreter not installed: {path}",
    "agent.direct_starting": "Direct mode starting — auto_run disabled, y/n confirmation each command",

    # ── 자원 가드 ──
    "guard.auto_stop": "[Auto-Stop] {reason}",
    "guard.ram_critical": "Available RAM critical ({mb}MB) — auto-stop",
    "guard.ram_persisted": "Available RAM low {mb}MB persisted {sec}s — auto-stop",

    # ── Ollama 메뉴 ──
    "ollama.title": "Ollama Service",
    "ollama.running": "Already running on port 11434",
    "ollama.starting": "Starting...",
    "ollama.start_ok": "Started",
    "ollama.start_fail": "Start failed",

    # ── 모델 정보 ──
    "model_info.title": "Installed model info",

    # ── Docker 이미지 빌드 ──
    "build.title": "Docker sandbox image build",
    "build.dockerfile_missing": "Dockerfile not found: {path}",
    "build.run_install_again": "Re-run install",
    "build.daemon_not_running": "Docker daemon not responding",
    "build.start_docker_first": "Start Docker Desktop and try again",
    "build.starting": "Starting build (5-10 minutes)...",
    "build.complete": "Image build complete: {name}",
    "build.failed": "Image build failed",

    # ── SearXNG ──
    "searxng.title": "SearXNG search engine control",
    "searxng.image_missing": "Image not installed",
    "searxng.image_missing_hint": "Re-run install to install SearXNG automatically",
    "searxng.status_running": "Status: Running ({url})",
    "searxng.status_stopped": "Status: Stopped",
    "searxng.config_label": "Config: {path}",
    "searxng.port_label": "Port: {port}",
    "searxng.opt_stop": "Stop",
    "searxng.opt_open_browser": "Open in browser",
    "searxng.opt_start": "Start",
    "searxng.opt_recreate": "Delete + recreate container",
    "searxng.opt_show_settings": "Show settings.yml location (edit with text editor)",
    "searxng.settings_file": "Settings file: {path}",
    "searxng.settings_main_keys": "Main keys:",
    "searxng.settings_safesearch": "  - safe_search: 0  (no filter. 1=moderate, 2=strict)",
    "searxng.settings_engines": "  - engines:        (backend engine on/off)",
    "searxng.settings_recreate_hint": "After editing, recreate via [3]",
    "searxng.recreating": "Recreating...",

    # ── 설정 관리 ──
    "settings.title": "Settings",
    "settings.file_label": "Settings file: {path}",
    "settings.status_exists": "Status: Present ({size} bytes)",
    "settings.status_missing": "Status: None (using defaults)",
    "settings.current_values": "Current values",
    "settings.last_workspace": "  Last workspace: {value}",
    "settings.last_choice": "  Last menu choice: {value}",
    "settings.last_model": "  Last model used: {value}",
    "settings.lang_current": "  Language: {lang}",
    "settings.saved_safe_options": "  Saved safe options:",
    "settings.none": "(none)",
    "settings.dangerous_note": "* Dangerous options are not saved (explicit activation required each time)",
    "settings.opt_show_raw": "Show raw JSON",
    "settings.opt_reset_workspace": "Reset workspace path only",
    "settings.opt_change_lang": "Change language",
    "settings.opt_reset_all": "Reset everything (delete file)",
    "settings.no_file_yet": "Settings file does not exist yet",
    "settings.workspace_reset_ok": "Workspace path reset",
    "settings.reset_warn": "This deletes all saved settings.",
    "settings.reset_confirm": "To confirm, type 'RESET':",
    "settings.reset_done": "Settings reset complete",
    "settings.reset_cancelled": "Cancelled",
},

# ════════════════════════════════════════════════════════════
"ko": {
    # ── 공통 ──
    "common.continue": "엔터를 누르면 계속...",
    "common.exit_prompt": "엔터를 누르면 종료...",
    "common.back": "뒤로",
    "common.quit": "종료",
    "common.yes": "예",
    "common.no": "아니오",
    "common.ok": "확인",

    # ── 언어 선택 ──
    "lang.select_title": "Select language / 언어 선택",
    "lang.option_en": "English",
    "lang.option_ko": "한국어 (Korean)",
    "lang.prompt": "선택 [1/2]: ",
    "lang.saved": "언어가 {lang}으로 설정되었습니다. 설정 메뉴에서 변경 가능합니다.",

    # ── 설치 시작 ──
    "install.title": "LLM 통합 환경 설치 (Windows / Portable)",
    "install.location": "설치 위치: {path}",
    "install.python_ver": "Python: {ver}",

    # ── 사전 검사 ──
    "install.preflight_windows_ok": "Windows 확인",
    "install.preflight_windows_fail": "Windows 전용입니다 (현재 OS: {os})",
    "install.preflight_python_ok": "Python {ver}",
    "install.preflight_python_fail": "Python {min_ver}+ 필요 (현재: {ver})",
    "install.preflight_disk_ok": "디스크 여유: {gb:.1f}GB",
    "install.preflight_disk_fail": "디스크 공간 부족: {gb:.1f}GB / 필요 {need}GB",
    "install.preflight_disk_unknown": "디스크 공간 확인 실패 — 계속",

    # ── 자원 감지 ──
    "install.resources_section": "시스템 자원 감지",
    "install.safety_profile": "안전 프로필: {profile}",
    "install.cant_run_full": "시스템 사양이 권장 최소치 미달 — 일부 기능이 제대로 동작하지 않을 수 있습니다",
    "install.proceeding_in_5": "5초 후 계속 진행합니다...",

    # ── 환경 폴더 ──
    "install.create_dirs": "역할별 폴더 생성",

    # ── Ollama ──
    "install.ollama_section": "Ollama 포터블 설치",
    "install.ollama_already": "이미 설치됨: {path}",
    "install.ollama_extracting": "압축 해제 중...",
    "install.ollama_done": "포터블 설치: {path}",
    "install.ollama_service_section": "Ollama 서비스 시작",
    "install.ollama_running": "이미 11434에서 가동 중",
    "install.ollama_starting_bg": "백그라운드 시작 (로그: {path})",
    "install.ollama_started": "가동 확인 ({sec}초)",
    "install.ollama_failed": "Ollama 시작 실패 — 로그 확인 필요",

    # ── 모델 ──
    "install.model_section": "모델 다운로드: {tag}",
    "install.model_size_warn": "약 14GB. 10~60분 소요됩니다 (네트워크 속도 영향).",
    "install.model_try1": "시도 1: {tag}",
    "install.model_try2": "시도 2 (HuggingFace 직접): {tag}",
    "install.model_done": "다운로드 완료",
    "install.model_failed": "두 경로 모두 실패",
    "install.model_manual": "수동 시도: ollama pull {tag}",

    # ── Python 도구 ──
    "install.webui_section": "Open WebUI 설치 (채팅 + 웹 검색)",
    "install.interpreter_section": "Open Interpreter 설치 (호스트 직접 모드용)",
    "install.pip_upgrade": "pip / wheel 업그레이드...",
    "install.pip_label_install": "{label} 설치 (병렬도={jobs}, 메모리 보호 활성)...",
    "install.pip_first_failed": "{label} 1차 설치 실패 (rc={rc}) — 보수 모드 재시도",
    "install.pip_second_ok": "{label} 보수 모드 설치 성공",
    "install.pip_final_failed": "{label} 설치 최종 실패 (rc={rc})",
    "install.pip_manual": "수동 시도: {pip} install {package}",
    "install.tool_done": "설치 완료: {path}",
    "install.webui_dep_warn": "Open WebUI 의존성 多 → 5~20분 소요 (저사양일수록 길어짐)",

    # ── 샌드박스 ──
    "install.sandbox_section": "Docker 샌드박스 설치",
    "install.docker_check_ok": "Docker 준비 확인",
    "install.dockerfile_written": "Dockerfile 작성: {path}",
    "install.image_build_section": "이미지 빌드: {name}",
    "install.image_build_warn": "5~10분 소요됩니다.",
    "install.image_build_limits": "빌드 자원 제한: 메모리 {mem}, CPU {cpus}코어",
    "install.image_build_ok": "이미지 빌드 완료",
    "install.image_build_fail": "빌드 실패",
    "install.image_skip": "이미지 빌드 건너뜀 (run.py에서 메뉴로 빌드 가능)",
    "install.sandbox_skip": "Docker 샌드박스 건너뜀: {reason}",
    "install.sandbox_skip_later": "Docker 설치 후 install 다시 실행",

    # ── SearXNG ──
    "install.searxng_section": "SearXNG (자체 호스팅 검색 엔진) 설치",
    "install.searxng_config_dir": "설정 폴더: {path}",
    "install.searxng_settings_reused": "기존 settings.yml 재사용: {path}",
    "install.searxng_settings_created": "settings.yml 생성 (SafeSearch=0): {path}",
    "install.searxng_limiter_created": "limiter.toml 생성: {path}",
    "install.searxng_pulling": "Docker 이미지 pull: {image}",
    "install.searxng_pull_size": "약 200MB. 1~3분 소요됩니다.",
    "install.searxng_pull_ok": "이미지 pull 완료",
    "install.searxng_pull_fail": "이미지 pull 실패",
    "install.searxng_ready": "SearXNG 준비 완료. 컨테이너 이름: {name}, 포트: {port}",
    "install.searxng_skip": "SearXNG 건너뜀 (Docker 필요): {reason}",
    "install.searxng_skip_optional": "SearXNG 설치 건너뜀 (--skip-search)",

    # ── 마무리 ──
    "install.complete": "설치 완료",
    "install.next_step": "다음 단계: RUN.bat 실행",
    "install.user_interrupt": "사용자 중단",

    # ════════════════════════════════════════════════════════
    # ── run.py / 메뉴 ──
    "menu.no_install": "설치 폴더가 없습니다: {path}",
    "menu.run_install_first": "먼저 설치를 실행하세요.",
    "menu.title": "LLM 환경 실행 메뉴",
    "menu.install_path": "설치 위치: {path}",
    "menu.last_choice": "(마지막 선택: {choice})",
    "menu.opt1": "채팅 UI (Open WebUI)",
    "menu.opt1_desc": "브라우저 기반 채팅 + 자동 웹 검색",
    "menu.opt2": "자동화 에이전트 — 샌드박스",
    "menu.opt2_recommended": "권장",
    "menu.opt2_desc": "Docker 컨테이너에서 격리 실행 (체크박스로 옵션 선택)",
    "menu.opt3": "자동화 에이전트 — 호스트 직접",
    "menu.opt3_dangerous": "위험",
    "menu.opt3_desc": "호스트에 직접 접근. 명시적 확인 필요",
    "menu.opt4": "Ollama 서비스 시작/확인",
    "menu.opt5": "설치된 모델 정보",
    "menu.opt6": "Docker 이미지 빌드/재빌드",
    "menu.opt7": "SearXNG 검색 엔진 제어",
    "menu.opt8": "설정 관리 (보기/초기화/언어)",
    "menu.optq": "종료",
    "menu.exiting": "종료합니다.",

    # ── 채팅 UI ──
    "chat.title": "채팅 UI 시작 (Open WebUI + SearXNG)",
    "chat.webui_missing": "Open WebUI 미설치: {path}",
    "chat.run_install_again": "install을 다시 실행하세요",
    "chat.searxng_starting": "SearXNG 검색 엔진 시작 시도...",
    "chat.searxng_failed": "SearXNG 시작 실패 — 검색 없이 계속",
    "chat.searxng_not_installed": "SearXNG 미설치 — 검색 비활성",
    "chat.searxng_install_hint": "(install 재실행하면 SearXNG 자동 설치됨)",
    "chat.searxng_connected": "검색 자동 연결: {url}",
    "chat.browser_url": "브라우저: http://localhost:8080",
    "chat.search_usage": "검색 사용: 채팅창 + 버튼 -> 'Web Search' 토글",
    "chat.exit_hint": "종료: Ctrl+C",

    # ── 에이전트 - 워크스페이스 ──
    "agent.workspace_title": "샌드박스 에이전트 — 작업 폴더 선택",
    "agent.workspace_desc1": "컨테이너의 /home/agent/workspace 에 마운트될 호스트 폴더입니다.",
    "agent.workspace_desc2": "이 폴더를 통해 호스트와 컨테이너가 파일을 주고받습니다.",
    "agent.workspace_last": "마지막 사용: {path} (저장됨)",
    "agent.workspace_default": "기본값: {path}",
    "agent.workspace_enter": "엔터: 위 경로 사용",
    "agent.workspace_input": "경로 입력: 다른 폴더 마운트",
    "agent.workspace_back": "b: 뒤로 가기",
    "agent.workspace_not_exist": "폴더가 존재하지 않습니다: {path}",

    # ── 에이전트 - 샌드박스 ──
    "sandbox.image_missing_title": "샌드박스 미준비",
    "sandbox.image_missing": "Docker 이미지 '{name}'이 없습니다",
    "sandbox.build_hint": "메인 메뉴 [6] 으로 빌드하거나, install을 다시 실행하세요",
    "sandbox.options_title": "샌드박스 에이전트 — 옵션 설정",
    "sandbox.options_subtitle": "번호로 토글, go 로 실행",
    "sandbox.options_help_safe": "안전 옵션은 저장된 값으로 복원됩니다 (✓).",
    "sandbox.options_help_dangerous": "위험 옵션(⚠/⚠⚠)은 항상 해제 상태로 시작 — 매번 명시적 활성화 필요.",
    "sandbox.mount_label": "마운트 폴더: {path}",
    "sandbox.mount_target": "            -> /home/agent/workspace",
    "sandbox.start_title": "샌드박스 시작",
    "sandbox.final_command": "최종 명령:",
    "sandbox.exit_hint": "종료하려면 컨테이너 안에서 'exit' 또는 Ctrl+D",

    # ── 옵션 라벨 ──
    "opt.isolation": "컨테이너 격리 (필수)",
    "opt.isolation_desc": "호스트 시스템은 컨테이너의 변경에서 보호됩니다",
    "opt.block_internet": "인터넷 차단 (DNS 비활성화)",
    "opt.block_internet_desc": "외부 도메인 해석 차단. 호스트 Ollama만 접근 가능",
    "opt.cpu_limit": "CPU 제한 ({cpus}코어)",
    "opt.cpu_limit_desc": "컨테이너의 CPU 사용량을 제한 (시스템 응답성 보호)",
    "opt.memory_limit": "메모리 제한 ({mem})",
    "opt.memory_limit_desc": "컨테이너 메모리를 제한 (스왑 폭주 방지)",
    "opt.auto_run": "자동 실행 (--auto_run)",
    "opt.auto_run_desc1": "매 명령마다 y/n 확인 없이 자동 실행.",
    "opt.auto_run_desc2": "샌드박스 안이라 호스트는 안전합니다.",
    "opt.allow_internet": "인터넷 허용",
    "opt.allow_internet_desc1": "pip install / API 호출 가능해집니다.",
    "opt.allow_internet_desc2": "에이전트가 외부와 자유롭게 통신.",
    "opt.allow_internet_desc3": "데이터 유출 / 악성 다운로드 위험 증가.",
    "opt.no_resource_limit": "CPU/메모리 제한 해제",
    "opt.no_resource_limit_desc1": "자원 제한 없이 실행.",
    "opt.no_resource_limit_desc2": "폭주 시 PC가 일시적으로 마비될 수 있습니다.",
    "opt.privileged": "privileged 모드 (호스트 디바이스 노출)",
    "opt.privileged_desc1": "컨테이너에 거의 호스트 수준 권한 부여.",
    "opt.privileged_desc2": "이 옵션은 격리의 의미를 크게 약화시킵니다.",
    "opt.privileged_desc3": "특수한 디버깅 용도가 아니면 사용하지 마세요.",

    # ── 위험 옵션 확인 ──
    "checkbox.high_risk_header": "매우 위험한 옵션 활성화",
    "checkbox.medium_risk_header": "주의 필요한 옵션 활성화",
    "checkbox.option_label": "옵션: {label}",
    "checkbox.description": "설명:",
    "checkbox.high_warn": "이 옵션은 시스템에 심각한 영향을 줄 수 있습니다.",
    "checkbox.medium_warn": "이 옵션은 추가 위험이 있습니다.",
    "checkbox.type_keyword": "활성화하려면 정확히 '{kw}'를 입력하세요.",
    "checkbox.cancel_default": "그 외 입력은 취소로 처리됩니다.",
    "checkbox.invalid_input": "잘못된 입력 — 번호 또는 명령어를 입력하세요",
    "checkbox.out_of_range": "범위 밖: {idx}",
    "checkbox.locked": "'{label}'은(는) 잠긴 항목입니다",
    "checkbox.cancelled": "'{label}' 활성화 취소됨",
    "checkbox.help_toggle": "번호 입력: 토글 (예: '3' 또는 '3 5')",
    "checkbox.help_commands": "go: 실행 | b: 뒤로 | q: 종료",

    # ── 호스트 직접 모드 ──
    "agent.direct_title_warn": "호스트 직접 실행 모드 - 매우 위험",
    "agent.direct_intro": "이 모드는 에이전트가 여러분 PC에 직접 접근합니다.",
    "agent.direct_risks": "위험:",
    "agent.direct_risk1": "- 모든 파일 읽기/쓰기/삭제 가능",
    "agent.direct_risk2": "- 시스템 명령 실행 가능 (포맷, shutdown 포함)",
    "agent.direct_risk3": "- 네트워크 자유 사용",
    "agent.direct_risk4": "- 격리 없음 — 모델의 실수가 PC에 직접 영향",
    "agent.direct_alternative": "대안: 메뉴 [2] 샌드박스 모드는 거의 같은 작업을 안전하게 처리합니다.",
    "agent.direct_confirm_prompt": "계속하려면 정확히 '{kw}'를 입력하세요:",
    "agent.direct_confirm_strict": "(대소문자 정확히 일치, 그 외 입력은 모두 취소)",
    "agent.direct_cancelled": "취소되었습니다 (대안 권장: 메뉴 [2] 샌드박스 모드)",
    "agent.direct_interpreter_missing": "Open Interpreter 미설치: {path}",
    "agent.direct_starting": "직접 모드 시작 — auto_run 비활성, 매 명령마다 y/n 확인됩니다",

    # ── 자원 가드 ──
    "guard.auto_stop": "[안전 정지] {reason}",
    "guard.ram_critical": "가용 RAM 위급 ({mb}MB) — 자동 정지",
    "guard.ram_persisted": "가용 RAM 부족 {mb}MB가 {sec}초 지속 — 자동 정지",

    # ── Ollama 메뉴 ──
    "ollama.title": "Ollama 서비스",
    "ollama.running": "이미 11434에서 가동 중",
    "ollama.starting": "시작 중...",
    "ollama.start_ok": "시작 완료",
    "ollama.start_fail": "시작 실패",

    # ── 모델 정보 ──
    "model_info.title": "설치된 모델 정보",

    # ── Docker 이미지 빌드 ──
    "build.title": "Docker 샌드박스 이미지 빌드",
    "build.dockerfile_missing": "Dockerfile 없음: {path}",
    "build.run_install_again": "install을 다시 실행하세요",
    "build.daemon_not_running": "Docker 데몬이 응답하지 않습니다",
    "build.start_docker_first": "Docker Desktop을 시작 후 다시 시도하세요",
    "build.starting": "이미지 빌드 시작 (5~10분 소요)...",
    "build.complete": "이미지 빌드 완료: {name}",
    "build.failed": "이미지 빌드 실패",

    # ── SearXNG ──
    "searxng.title": "SearXNG 검색 엔진 제어",
    "searxng.image_missing": "이미지 미설치",
    "searxng.image_missing_hint": "install을 다시 실행하면 자동 설치됩니다",
    "searxng.status_running": "상태: 가동 중 ({url})",
    "searxng.status_stopped": "상태: 정지됨",
    "searxng.config_label": "설정: {path}",
    "searxng.port_label": "포트: {port}",
    "searxng.opt_stop": "정지",
    "searxng.opt_open_browser": "브라우저에서 열기",
    "searxng.opt_start": "시작",
    "searxng.opt_recreate": "컨테이너 삭제 + 재생성",
    "searxng.opt_show_settings": "settings.yml 위치 보기 (수정은 텍스트 에디터로)",
    "searxng.settings_file": "설정 파일: {path}",
    "searxng.settings_main_keys": "주요 항목:",
    "searxng.settings_safesearch": "  - safe_search: 0  (필터 없음. 1=중간, 2=엄격)",
    "searxng.settings_engines": "  - engines:        (백엔드 엔진 on/off)",
    "searxng.settings_recreate_hint": "수정 후 [3]으로 재생성 필요",
    "searxng.recreating": "재생성 중...",

    # ── 설정 관리 ──
    "settings.title": "설정 관리",
    "settings.file_label": "설정 파일: {path}",
    "settings.status_exists": "상태: 존재 ({size} bytes)",
    "settings.status_missing": "상태: 없음 (기본값 사용 중)",
    "settings.current_values": "현재 설정값",
    "settings.last_workspace": "  마지막 워크스페이스: {value}",
    "settings.last_choice": "  마지막 메뉴 선택: {value}",
    "settings.last_model": "  마지막 사용 모델: {value}",
    "settings.lang_current": "  언어: {lang}",
    "settings.saved_safe_options": "  저장된 안전 옵션:",
    "settings.none": "(없음)",
    "settings.dangerous_note": "* 위험 옵션은 보안상 저장되지 않습니다 (매번 명시적 활성화 필요)",
    "settings.opt_show_raw": "설정 파일 내용 보기 (raw JSON)",
    "settings.opt_reset_workspace": "워크스페이스 경로만 초기화",
    "settings.opt_change_lang": "언어 변경",
    "settings.opt_reset_all": "전체 초기화 (파일 삭제)",
    "settings.no_file_yet": "설정 파일이 아직 없습니다",
    "settings.workspace_reset_ok": "워크스페이스 경로 초기화됨",
    "settings.reset_warn": "이 작업은 저장된 모든 설정을 삭제합니다.",
    "settings.reset_confirm": "계속하려면 'RESET' 정확히 입력:",
    "settings.reset_done": "설정 초기화 완료",
    "settings.reset_cancelled": "취소됨",
},

}
