"""config — launcher 전역 상수.

모든 매직 넘버 / 상수 / 경로 패턴을 한 곳에 모아 변경 추적성을 높였다.
이전: handlers.py 상단, searxng_runtime.py, gui.py 등에 분산.
"""
from __future__ import annotations

# ─── 모델 ─────────────────────────────────────────────
# model_roles 를 못 불러왔을 때만 쓰는 최후 기본값. 평상시 모델 선택은
# model_roles.TIERS 사다리가 전담한다(메모리 롤백 포함) — 여기에 폴백 태그를
# 따로 두면 사다리와 갈라지기만 하고 아무도 읽지 않는다.
MODEL_TAG = "prutser/gemma-4-26B-A4B-it-ara-abliterated:Q4_K_S"

# ─── Docker ───────────────────────────────────────────
SANDBOX_IMAGE = "llm-agent-sandbox"
SANDBOX_CONTAINER_PREFIX = "llm_agent_"

SEARXNG_IMAGE = "searxng/searxng:latest"
SEARXNG_CONTAINER = "llm_searxng"

# ─── 네트워크 ─────────────────────────────────────────
OLLAMA_HOST = "127.0.0.1"
OLLAMA_PORT = 11434
OLLAMA_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"
OLLAMA_API_TAGS = f"{OLLAMA_URL}/api/tags"

# Open WebUI 는 AnythingLLM 으로 대체되었다(ANYTHINGLLM_v1 참고).
# 남아 있던 포트/URL 상수는 아무도 읽지 않았고, 8080 은 이제 SearXNG 컨테이너
# 내부 포트 의미로만 쓰인다.

SEARXNG_HOST_PORT = 8888
SEARXNG_URL = f"http://localhost:{SEARXNG_HOST_PORT}"

# ─── 타임아웃 (초) ────────────────────────────────────
OLLAMA_PROBE_TIMEOUT = 2
OLLAMA_BOOT_TIMEOUT = 30
DOCKER_PROBE_TIMEOUT = 10
SEARXNG_BOOT_TIMEOUT = 60

# ─── 컨테이너 마운트 경로 ─────────────────────────────
SANDBOX_WORKSPACE_MOUNT = "/home/agent/workspace"

# ─── Windows 전용 ─────────────────────────────────────
WIN_CREATE_NO_WINDOW = 0x08000000   # 콘솔창 안 뜸 (백그라운드 작업용)
WIN_CREATE_NEW_CONSOLE = 0x00000010  # 새 콘솔창 띄움 (인터랙티브 액션용)

# ─── 기본 자원 한도 (감지 실패 시 폴백) ───────────────
DEFAULT_CONTAINER_MEM = "4g"
DEFAULT_CONTAINER_CPUS = "2"

# ─── UI 모드 ──────────────────────────────────────────
UI_MODE_TUI = "tui"
UI_MODE_GUI = "gui"
DEFAULT_UI_MODE = UI_MODE_GUI

# ═══════════════════════════════════════════════════════
#  NET_CONFIG_v1 — 네트워크 엔드포인트 '정본(single source of truth)'
#
#  주소/포트/컨테이너명을 여기서만 정의한다. 다른 모듈은 반드시 이 값을 읽고,
#  리터럴을 직접 적지 않는다.
#
#  ★ Docker Desktop 제약: 컨테이너끼리는 host.docker.internal 로 서로의 게시
#    포트에 도달할 수 없다. 반드시 공유 네트워크 + '컨테이너 이름' 으로 통신할 것.
#    (host.docker.internal 은 호스트 프로세스인 Ollama 에만 사용)
# ═══════════════════════════════════════════════════════

# 공유 Docker 네트워크 (컨테이너 간 이름 해석용)
LLM_NETWORK = "llm_net"

# ── Tor 프록시 ────────────────────────────────────────
TOR_IMAGE = "dperson/torproxy"
TOR_CONTAINER = "llm_tor"
TOR_SOCKS_PORT = 9050          # SOCKS5 (socks5h = 원격 DNS, 유출 방지)
TOR_HTTP_PORT = 8118           # Privoxy (HTTP/HTTPS 프록시, .onion 도 통과)
TOR_BOOT_TIMEOUT = 90          # 회로 구축까지 걸리는 시간을 감안

# ── SearXNG ───────────────────────────────────────────
# SEARXNG_IMAGE / SEARXNG_CONTAINER / SEARXNG_HOST_PORT 는 위쪽에 이미 정의됨
SEARXNG_CONTAINER_PORT = 8080  # 이미지가 내부에서 리슨하는 포트

# ── 외부 검색 엔드포인트 ──────────────────────────────
# DuckDuckGo 공식 v3 onion. Tor 망 내부에서 종단되므로 출구 노드가 없고,
# 따라서 차단할 IP 자체가 존재하지 않는다(= 검색 익명성 최상).
DDG_ONION_HOST = "duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion"
DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"

# ── 파생 URL (컨테이너 '이름' 기준) ───────────────────
def tor_http_proxy(host: str = None) -> str:
    """Privoxy HTTP 프록시 URL. 예) http://llm_tor:8118"""
    return "http://%s:%d" % (host or TOR_CONTAINER, TOR_HTTP_PORT)


def tor_socks_proxy(host: str = None) -> str:
    """SOCKS5 프록시 URL(원격 DNS). 예) socks5h://llm_tor:9050"""
    return "socks5h://%s:%d" % (host or TOR_CONTAINER, TOR_SOCKS_PORT)


def searxng_internal_url(host: str = None) -> str:
    """컨테이너 간 SearXNG 주소. 예) http://llm_searxng:8080

    주의: 위쪽 SEARXNG_URL 은 '호스트에서' 접근하는 주소(localhost:8888)로
    의미가 다르다. 컨테이너 안에서는 반드시 이 함수를 쓸 것.
    """
    return "http://%s:%d" % (host or SEARXNG_CONTAINER, SEARXNG_CONTAINER_PORT)


SEARXNG_INTERNAL_URL = "http://%s:%d" % (SEARXNG_CONTAINER, SEARXNG_CONTAINER_PORT)

# =======================================================
#  NETMODE_WARP_v2 - 기본 네트워크 = WARP, Tor 는 별개 옵션 (정본)
#
#  NET_MODE 로 나가는 프록시 계층을 고른다.
#    warp(기본) : Cloudflare WARP SOCKS5 (llm_warp:1080) - 빠르고 차단 적음
#    tor        : 기존 Tor (llm_tor:9050) - onion/익명성 경로 보존
#  주소/포트/이미지는 여기서만 정의하고 다른 모듈은 이 값을 읽는다.
#  (WARP 는 SOCKS5 만 제공 -> HTTP_PROXY 도 socks5h 로 통일)
# =======================================================
import os as _os  # 표준 라이브러리 (지연 참조용)

NET_MODE = _os.environ.get("NET_MODE", "warp").strip().lower()

WARP_IMAGE = _os.environ.get("WARP_IMAGE", "dublok/cloudflare-warp:latest")
WARP_CONTAINER = _os.environ.get("WARP_CONTAINER", "llm_warp")
WARP_PORT = int(_os.environ.get("WARP_PORT", "1080"))
WARP_LICENSE = _os.environ.get("WARP_LICENSE", "")
WARP_BOOT_TIMEOUT = int(_os.environ.get("WARP_BOOT_TIMEOUT", "45"))


# HTTP_BRIDGE_v1: WARP(SOCKS 전용) 앞의 HTTP 프록시 브리지
HTTP_BRIDGE_CONTAINER = _os.environ.get("HTTP_BRIDGE_CONTAINER", "llm_httpbridge")
HTTP_BRIDGE_PORT = int(_os.environ.get("HTTP_BRIDGE_PORT", "8118"))
HTTP_BRIDGE_HOST_PORT = int(_os.environ.get("HTTP_BRIDGE_HOST_PORT", "8119"))


def http_bridge_proxy(host: str = None) -> str:
    """HTTP_BRIDGE_v1: urllib 이 쓸 수 있는 HTTP 프록시 URL."""
    return "http://%s:%d" % (host or HTTP_BRIDGE_CONTAINER, HTTP_BRIDGE_PORT)


def warp_socks_proxy(host: str = None) -> str:
    """WARP SOCKS5 프록시 URL(원격 DNS). 예) socks5h://llm_warp:1080"""
    return "socks5h://%s:%d" % (host or WARP_CONTAINER, WARP_PORT)


def active_socks_proxy(host: str = None) -> str:
    """NET_MODE 기준 SOCKS5 프록시(컨테이너 이름).
    warp -> socks5h://llm_warp:1080,  tor -> socks5h://llm_tor:9050"""
    if NET_MODE == "tor":
        return tor_socks_proxy(host)
    return warp_socks_proxy(host)


def active_container() -> str:
    """현재 네트워크 모드의 프록시 컨테이너 이름."""
    return TOR_CONTAINER if NET_MODE == "tor" else WARP_CONTAINER


def active_image() -> str:
    """현재 네트워크 모드의 프록시 이미지."""
    return TOR_IMAGE if NET_MODE == "tor" else WARP_IMAGE


def net_proxy_env(host: str = None) -> dict:
    """NET_MODE 인지 프록시 env. warp 는 SOCKS 전용이라 HTTP_PROXY 도 socks5h.
    tor 모드는 기존 agent_proxy_env() 와 동일 동작을 유지한다."""
    if NET_MODE == "tor":
        return agent_proxy_env(host)
    # HTTP_BRIDGE_v1: urllib 은 SOCKS 를 못 쓴다. HTTP_* 는 브리지(http://),
    # ALL_PROXY 는 SOCKS 를 이해하는 클라이언트(curl/requests)용으로 유지.
    p = warp_socks_proxy(host)
    hp = http_bridge_proxy()
    env = {}
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env[k] = hp
    for k in ("ALL_PROXY", "all_proxy"):
        env[k] = p
    for k in ("NO_PROXY", "no_proxy"):
        env[k] = NO_PROXY_HOSTS
    return env

# 프록시를 태우면 안 되는 대상 (로컬 Ollama 등)
NO_PROXY_HOSTS = "host.docker.internal,localhost,127.0.0.1,::1"


def agent_proxy_env(tor_host: str = None) -> dict:
    """에이전트 컨테이너/호스트 프로세스에 넣을 프록시 환경변수 묶음."""
    http_p = tor_http_proxy(tor_host)
    socks_p = tor_socks_proxy(tor_host)
    env = {}
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env[k] = http_p
    for k in ("ALL_PROXY", "all_proxy"):
        env[k] = socks_p
    for k in ("NO_PROXY", "no_proxy"):
        env[k] = NO_PROXY_HOSTS
    return env


# ═══════════════════════════════════════════════════════
#  TOKEN_LIMITS_v1 — 채팅 런타임 토큰 한도 (정본)
#
#  context_window 는 시스템 메시지 + 대화 이력을 담을 공간이다.
#  RAM 이 빠듯하면 낮춰도 되고, 긴 문서 RAG 를 자주 쓰면 올려도 된다.
#
#  이 섹션에는 원래 설명만 있고 상수가 없었다. 값은 launcher.runtime_guard 가
#  준다고 적혀 있었지만 그 모듈은 저장소에 존재하지 않아, 호출부의 try/except 가
#  매번 조용히 실패하고 하드코딩된 4096 이 쓰이고 있었다. 정본을 여기로 되돌린다.
#  (상수를 되돌린 뒤에도 호출부는 존재하지 않는 model_roles.chat_context_window()
#   를 계속 불렀다. 지금은 actions/chat.py 와 transition 어댑터가 이 상수를 직접
#   읽는다 — 새 이름을 만들 때는 호출부까지 같이 고칠 것.)
#
#  AnythingLLM 은 이 값을 OLLAMA_MODEL_TOKEN_LIMIT 로 받는다.
#  (Agent 런타임은 컨텍스트 길이를 AgentConfig 가 아니라 Open Interpreter/Ollama
#   기본값에 맡기므로 이 상수를 읽지 않는다.)
# ═══════════════════════════════════════════════════════
CHAT_CONTEXT_WINDOW = 4096


# ═══════════════════════════════════════════════════════
#  SETTINGS_v1 — 조정 가능한 설정 (정본)
# ═══════════════════════════════════════════════════════

# ── 컨테이너 내부 경로 ────────────────────────────────
AGENT_WORKSPACE = "/home/agent/workspace"
AGENT_STATE_DIR = "/home/agent/.agent_state"


# >>> ANYTHINGLLM_v1 (PATCH_ANYTHINGLLM.py)  ANYTHINGLLM_REV=8
# AnythingLLM (Open WebUI 대체) — 주소/포트/자원 정본
# 값 출처: mintplexlabs/anything-llm docker/.env.example
# 실행시 오버라이드: LOCAL_AI_ANYTHINGLLM_{IMAGE,CONTAINER,PORT,MEM,CPUS,EMBED,BOOT_TIMEOUT}
ANYTHINGLLM_IMAGE = "mintplexlabs/anythingllm:latest"
ANYTHINGLLM_CONTAINER = "llm_anythingllm"
ANYTHINGLLM_HOST_PORT = 3001
ANYTHINGLLM_CONTAINER_PORT = 3001
ANYTHINGLLM_STORAGE_MOUNT = "/app/server/storage"
ANYTHINGLLM_SERVER_ENV_MOUNT = "/app/server/.env"
ANYTHINGLLM_BOOT_TIMEOUT = 180
ANYTHINGLLM_PULL_TIMEOUT = 5400
# 기동 대기 중 진행 상황을 몇 초마다 출력할지 (0 이면 매 루프)
ANYTHINGLLM_PROGRESS_EVERY = 8
# docker stop 유예(초). -t 를 안 주면 도커 기본 10초를 매 종료마다 기다린다.
ANYTHINGLLM_STOP_GRACE = 3
# 기동 확인 주소. 윈도우에서 localhost 가 ::1 로 먼저 풀리는 경우가 있어 IPv4 우선.
ANYTHINGLLM_PROBE_HOSTS = "127.0.0.1,localhost"
# "auto" = 여유 RAM / CPU 수를 보고 결정. 고정하려면 "4g" / "2" 처럼 적는다.
ANYTHINGLLM_MEM = "auto"
ANYTHINGLLM_CPUS = "auto"
# 내장 Chromium(문서 스크래핑)용. 빈 튜플로 두면 대신
# ANYTHINGLLM_CHROMIUM_ARGS 를 .env 에 넣어 권한 없이 돌린다.
ANYTHINGLLM_CAP_ADD = ("SYS_ADMIN",)
ANYTHINGLLM_VECTOR_DB = "lancedb"
ANYTHINGLLM_WHISPER_PROVIDER = "local"
ANYTHINGLLM_TTS_PROVIDER = "native"
ANYTHINGLLM_OLLAMA_TIMEOUT_MS = 7200000
# native = 컨테이너 내장 임베더 (최초 1회 HuggingFace 에서 모델을 받음).
# 오프라인이면 "ollama" 로 바꾸고 BASE_PATH/MODEL 을 채운 뒤
# 호스트에서 `ollama pull nomic-embed-text` 를 먼저 하세요.
ANYTHINGLLM_EMBEDDING_ENGINE = "native"
ANYTHINGLLM_EMBEDDING_MODEL = "Xenova/all-MiniLM-L6-v2"
ANYTHINGLLM_EMBEDDING_BASE_PATH = ""
# .env 에 그대로 추가할 임의 키 (예: {"DISABLE_SWAGGER_DOCS": "true"})
ANYTHINGLLM_EXTRA_ENV = {}
# ── 네트워크(WARP/Tor) 연동 ──
# True 면 NET_MODE 를 따라 컨테이너에 HTTP_PROXY 를 주입한다.
#   warp -> http://llm_httpbridge:8118 (WARP 는 SOCKS 전용 -> 기존 HTTP 브리지 재사용)
#   tor  -> http://llm_tor:8118        (Privoxy)
# ALL_PROXY(socks5h) 는 일부러 넣지 않는다 — Node 는 SOCKS 를 못 쓰고,
# axios 의 proxy-from-env 가 ALL_PROXY 를 읽어 그대로 깨진다.
ANYTHINGLLM_NET_AWARE = True
# Node 내장 fetch 는 기본적으로 HTTP_PROXY 를 무시한다. v22.21+/v24+ 는 이 값이
# 있어야 따른다(구버전에서는 무시되는 값이라 해가 없다).
ANYTHINGLLM_NODE_ENV_PROXY = True
# NO_PROXY 에 더 넣을 호스트 (쉼표 구분). Ollama/SearXNG/프록시 컨테이너는 자동 포함.
ANYTHINGLLM_NO_PROXY_EXTRA = ""
# 이미지의 Node 가 v22.21 미만이면 내장 fetch 가 HTTP_PROXY 를 무시한다.
# True 면 storage 에 proxy-bootstrap.js 를 심고 NODE_OPTIONS=--require 로 물려서
# undici ProxyAgent 를 전역 디스패처로 꽂는다 (NO_PROXY 존중).
# undici 가 이미지에 없으면 조용히 무시된다.
ANYTHINGLLM_NODE_BOOTSTRAP = True
ANYTHINGLLM_NODE_OPTIONS_EXTRA = ""
# <<< ANYTHINGLLM_v1
