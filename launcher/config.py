"""config — launcher 전역 상수.

모든 매직 넘버 / 상수 / 경로 패턴을 한 곳에 모아 변경 추적성을 높였다.
이전: handlers.py 상단, searxng_runtime.py, gui.py 등에 분산.
"""
from __future__ import annotations

# ─── 모델 ─────────────────────────────────────────────
MODEL_TAG = "prutser/gemma-4-26B-A4B-it-ara-abliterated:Q4_K_S"  # MODEL_GEMMA_v9 (무검열 범용/에이전트)
MODEL_TAG_FALLBACK = "gemma4:12b"  # MODEL_GEMMA_v9 (메모리 부족 시 롤백)

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

OPEN_WEBUI_PORT = 8080
OPEN_WEBUI_URL = f"http://localhost:{OPEN_WEBUI_PORT}"

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
#  리터럴을 직접 적지 않는다. (컨테이너 안에서 도는 PreTool 은 config 를 import
#  할 수 없으므로 환경변수로 주입받고, 기본값만 여기 값을 '미러'한다.
#  미러가 어긋나면 CHECK_ENDPOINTS 가 잡아낸다.)
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


def pretool_env() -> dict:
    """PreTool(컨테이너 안)에 주입할 엔드포인트 환경변수."""
    return {
        "SEARXNG_URL": SEARXNG_INTERNAL_URL,
        "DDG_ONION_HOST": DDG_ONION_HOST,
        "DDG_LITE_URL": DDG_LITE_URL,
    }
