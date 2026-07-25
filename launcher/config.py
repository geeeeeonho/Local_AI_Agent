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


# ═══════════════════════════════════════════════════════
#  TOKEN_LIMITS_v1 — 에이전트 생성 한도 (정본)
#
#  max_tokens 가 작으면 보고서용 긴 코드 블록이 중간에 잘려 실행조차 되지 않는다
#  (실측된 실패 모드). context_window 는 시스템 메시지 + 대화 이력을 담을 공간이다.
#  RAM 이 빠듯하면 CONTEXT_WINDOW 를 6144 또는 4096 으로 낮춰도 된다
#  (max_tokens 상향 효과는 그대로 유지된다).
# ═══════════════════════════════════════════════════════
AGENT_MAX_TOKENS = 2048        # 출력 길이. 모델 가중치 메모리와 무관
AGENT_CONTEXT_WINDOW = 8192    # KV 캐시에 영향(4096 -> 8192 는 대략 수백MB~1GB)


# ═══════════════════════════════════════════════════════
#  SETTINGS_v1 — 조정 가능한 설정 (정본)
#
#  여기 값만 고치면 런처와 컨테이너 안 PreTool 까지 함께 바뀐다.
#  (PreTool 은 config 를 import 할 수 없으므로 pretool_env() 로 환경변수 전달)
# ═══════════════════════════════════════════════════════

# ── 검색/열람 타임아웃 (초) ───────────────────────────
SEARCH_TIMEOUT = 25          # 검색 1회 (Tor 는 느리므로 여유 있게)
SEARCH_ONION_TIMEOUT = 25    # onion 은 회로 구축이 더 걸릴 수 있음
PAGE_TIMEOUT = 25            # 페이지 본문 가져오기
ARCHIVE_TIMEOUT = 20         # Wayback 아카이브 조회
# 실측: 25초 안에 응답 없는 사이트는 90초를 기다려도 대개 실패한다.
# 빨리 포기하고 아카이브로 넘어가는 편이 전체 소요를 줄인다.

# ── 재시도 ────────────────────────────────────────────
SEARCH_RETRIES = 3           # 검색 재시도
PUBLIC_SEARX_TRIES = 3       # 공용 인스턴스 시도 개수

# ── 본문 길이 한도 (자) ───────────────────────────────
PAGE_BODY_LIMIT = 6000       # open_url 이 돌려주는 최대 길이
RESEARCH_BODY_CHARS = 1800   # research() 가 기사당 붙이는 본문 길이
MIN_BODY_CHARS = 400         # 이보다 짧으면 '기사 본문' 으로 보지 않음

# ── 컨테이너 내부 경로 ────────────────────────────────
AGENT_WORKSPACE = "/home/agent/workspace"
AGENT_STATE_DIR = "/home/agent/.agent_state"

# ── 검색 경로 선택 ────────────────────────────────────
#   race(기본) | onion | clearnet | searxng
SEARCH_PATH_MODE = "race"

# 공용 SearXNG 인스턴스 (Tor 로 경유 -> 구글 차단 회피)
PUBLIC_SEARX_INSTANCES = (
    "https://searx.be",
    "https://search.inetol.net",
    "https://priv.au",
    "https://opnxng.com",
    "https://searxng.site",
    "https://search.bus-hit.me",
)

# Tor 를 우회할 도메인 (막히는 사이트만 예외 처리).
# 비워 두면 전부 Tor 를 지난다. 호스트에 VPN 을 켜 두면 이 경로도 실제 IP 는 가려진다.
SEARCH_DIRECT_DOMAINS = ()


def pretool_settings_env() -> dict:
    """PreTool(컨테이너 안)에 전달할 설정 환경변수."""
    return {
        "SEARCH_TIMEOUT": str(SEARCH_TIMEOUT),
        "SEARCH_ONION_TIMEOUT": str(SEARCH_ONION_TIMEOUT),
        "PAGE_TIMEOUT": str(PAGE_TIMEOUT),
        "ARCHIVE_TIMEOUT": str(ARCHIVE_TIMEOUT),
        "SEARCH_RETRIES": str(SEARCH_RETRIES),
        "PUBLIC_SEARX_TRIES": str(PUBLIC_SEARX_TRIES),
        "PAGE_BODY_LIMIT": str(PAGE_BODY_LIMIT),
        "RESEARCH_BODY_CHARS": str(RESEARCH_BODY_CHARS),
        "MIN_BODY_CHARS": str(MIN_BODY_CHARS),
        "SEARCH_PATH": SEARCH_PATH_MODE,
        "SEARXNG_PUBLIC": ",".join(PUBLIC_SEARX_INSTANCES),
        "SEARCH_DIRECT_DOMAINS": ",".join(SEARCH_DIRECT_DOMAINS),
        "AGENT_WORKSPACE": AGENT_WORKSPACE,
    }


def all_pretool_env() -> dict:
    """엔드포인트 + 설정을 합친 전체 환경변수 (컨테이너 주입용)."""
    env = {}
    try:
        env.update(pretool_env())
    except Exception:
        pass
    env.update(pretool_settings_env())
    return env
