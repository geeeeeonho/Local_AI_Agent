"""config — launcher 전역 상수.

모든 매직 넘버 / 상수 / 경로 패턴을 한 곳에 모아 변경 추적성을 높였다.
이전: handlers.py 상단, searxng_runtime.py, gui.py 등에 분산.
"""
from __future__ import annotations

# ─── 모델 ─────────────────────────────────────────────
MODEL_TAG = "prutser/gemma-4-26B-A4B-it-ara-abliterated:Q3_K_M"
MODEL_TAG_FALLBACK = "hf.co/jenerallee78/gemma-4-26B-A4B-it-ara-abliterated:Q3_K_M"

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
