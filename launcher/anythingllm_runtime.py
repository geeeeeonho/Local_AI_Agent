# -*- coding: utf-8 -*-
# >>> ANYTHINGLLM_v1 (PATCH_ANYTHINGLLM.py 가 생성)  ANYTHINGLLM_REV=8
"""anythingllm_runtime — AnythingLLM 컨테이너 수명주기.

searxng_runtime / warp_runtime 과 같은 모양이며, 같은 규약을 따른다.
  - 주소/이미지/자원은 launcher/config.py 가 정본. 리터럴을 직접 적지 않는다.
  - 환경변수로 실행시 오버라이드 가능 (LOCAL_AI_ANYTHINGLLM_*)
  - 기동하면 lifelog.register_cleanup 으로 종료 정리를 등록한다
    (llm_anythingllm 은 lifelog 의 고아 패턴에 걸리지 않으므로 필수)

경로
  Ollama   : host.docker.internal:11434   (호스트 프로세스)
  SearXNG  : llm_searxng:8080             (컨테이너끼리는 llm_net + 이름으로만)
  브라우저 : http://localhost:3001

설정은 storage/.env 에 '한 번만' 심는다(seed). AnythingLLM 이 UI 설정을 이 파일에
되쓰기 때문에, 매번 덮어쓰면 사용자가 UI 에서 바꾼 값이 날아간다.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    from . import config as _cfg
except Exception:  # pragma: no cover
    try:
        from launcher import config as _cfg
    except Exception:
        _cfg = None


def _c(name, default):
    return getattr(_cfg, name, default) if _cfg else default


def _envc(env_name, cfg_name, default):
    """환경변수 > config > 기본값 순."""
    v = os.environ.get(env_name)
    if v not in (None, ""):
        return v
    return _c(cfg_name, default)


IMAGE = _envc("LOCAL_AI_ANYTHINGLLM_IMAGE", "ANYTHINGLLM_IMAGE",
              "mintplexlabs/anythingllm:latest")
CONTAINER = _envc("LOCAL_AI_ANYTHINGLLM_CONTAINER", "ANYTHINGLLM_CONTAINER",
                  "llm_anythingllm")
HOST_PORT = int(_envc("LOCAL_AI_ANYTHINGLLM_PORT", "ANYTHINGLLM_HOST_PORT", 3001))
CONTAINER_PORT = int(_c("ANYTHINGLLM_CONTAINER_PORT", 3001))
URL = "http://localhost:%d" % HOST_PORT
STORAGE_MOUNT = _c("ANYTHINGLLM_STORAGE_MOUNT", "/app/server/storage")
SERVER_ENV_MOUNT = _c("ANYTHINGLLM_SERVER_ENV_MOUNT", "/app/server/.env")
BOOT_TIMEOUT = int(_envc("LOCAL_AI_ANYTHINGLLM_BOOT_TIMEOUT",
                         "ANYTHINGLLM_BOOT_TIMEOUT", 180))
PULL_TIMEOUT = int(_c("ANYTHINGLLM_PULL_TIMEOUT", 5400))
CAP_ADD = tuple(_c("ANYTHINGLLM_CAP_ADD", ("SYS_ADMIN",)) or ())
VECTOR_DB = _c("ANYTHINGLLM_VECTOR_DB", "lancedb")
WHISPER = _c("ANYTHINGLLM_WHISPER_PROVIDER", "local")
TTS = _c("ANYTHINGLLM_TTS_PROVIDER", "native")
OLLAMA_TIMEOUT_MS = int(_c("ANYTHINGLLM_OLLAMA_TIMEOUT_MS", 7200000))
EMBED_ENGINE = _envc("LOCAL_AI_ANYTHINGLLM_EMBED", "ANYTHINGLLM_EMBEDDING_ENGINE",
                     "native")
EMBED_MODEL = _c("ANYTHINGLLM_EMBEDDING_MODEL", "Xenova/all-MiniLM-L6-v2")
EMBED_BASE_PATH = _c("ANYTHINGLLM_EMBEDDING_BASE_PATH", "")
EXTRA_ENV = dict(_c("ANYTHINGLLM_EXTRA_ENV", {}) or {})
NET_AWARE = bool(_c("ANYTHINGLLM_NET_AWARE", True))
NODE_ENV_PROXY = bool(_c("ANYTHINGLLM_NODE_ENV_PROXY", True))
NO_PROXY_EXTRA = str(_c("ANYTHINGLLM_NO_PROXY_EXTRA", ""))
NETMODE_LABEL = "local_ai_netmode"
CFGSIG_LABEL = "local_ai_cfgsig"
STOP_GRACE = int(_c("ANYTHINGLLM_STOP_GRACE", 3))
PROBE_HOSTS = str(_c("ANYTHINGLLM_PROBE_HOSTS", "127.0.0.1,localhost"))
PROGRESS_EVERY = int(_c("ANYTHINGLLM_PROGRESS_EVERY", 8))
NODE_BOOTSTRAP = bool(_c("ANYTHINGLLM_NODE_BOOTSTRAP", True))
NODE_BOOTSTRAP_NAME = "proxy-bootstrap.js"
NODE_OPTIONS_EXTRA = str(_c("ANYTHINGLLM_NODE_OPTIONS_EXTRA", ""))
NETWORK = os.environ.get("LLM_NETWORK", _c("LLM_NETWORK", "llm_net"))
_NOWIN = int(_c("WIN_CREATE_NO_WINDOW", 0x08000000)) if os.name == "nt" else 0


def _ll(kind, msg):
    """런처 로그(lifelog)에 남긴다. 사후 분석용 — 실패해도 무시."""
    try:
        try:
            from .core import lifelog as _lg
        except Exception:
            from launcher.core import lifelog as _lg
        _lg.log(kind, "[anythingllm] " + str(msg))
    except Exception:
        pass


def _emit(log, msg, kind="INFO"):
    """화면(log 콜백) + 런처 로그에 동시에."""
    if log:
        try:
            log(msg)
        except Exception:
            pass
    _ll(kind, msg)


def _run(args, timeout=60):
    kw = {"capture_output": True, "text": True, "timeout": timeout}
    if _NOWIN:
        kw["creationflags"] = _NOWIN
    try:
        return subprocess.run(args, **kw)
    except FileNotFoundError:
        class _R:
            returncode = 127
            stdout = ""
            stderr = "docker not found"
        return _R()
    except subprocess.TimeoutExpired:
        class _R:
            returncode = 124
            stdout = ""
            stderr = "timeout"
        return _R()


# ─────────────────────────────────────────────
#  자원 (auto 지원)
# ─────────────────────────────────────────────
def resolve_memory():
    """'auto' 면 여유 RAM 을 보고 정한다. 26B 모델과 경합하지 않도록 보수적으로."""
    v = str(_envc("LOCAL_AI_ANYTHINGLLM_MEM", "ANYTHINGLLM_MEM", "auto"))
    if v.lower() != "auto":
        return v or None
    free = None
    try:
        from launcher.models import model_roles as _mr
        free = _mr.detect_free_memory_gb()
    except Exception:
        free = None
    if not free:
        return _c("DEFAULT_CONTAINER_MEM", "4g")
    if free < 4:
        return "2g"
    if free < 8:
        return "3g"
    return "4g"


def resolve_cpus():
    v = str(_envc("LOCAL_AI_ANYTHINGLLM_CPUS", "ANYTHINGLLM_CPUS", "auto"))
    if v.lower() != "auto":
        return v or None
    try:
        n = os.cpu_count() or 2
    except Exception:
        n = 2
    return str(max(1, min(4, n // 2)))


# ─────────────────────────────────────────────
#  경로
# ─────────────────────────────────────────────
def storage_dir():
    """호스트측 영속 저장 폴더. user_data/anythingllm.

    resolve() 로 실경로를 쓴다 — user_data 가 정션이면 정션 경로를 그대로
    docker -v 에 넘길 때 Docker Desktop 파일 공유가 어긋난다.
    """
    d = None
    try:
        from launcher.core import user_data as _ud
        d = Path(_ud.chat_dir()).parent / "anythingllm"
    except Exception:
        d = None
    if d is None:
        d = Path(__file__).resolve().parents[1] / "user_data" / "anythingllm"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    try:
        d = d.resolve()
    except OSError:
        pass
    return d


def _vol(p):
    """docker -v 용 경로. Docker Desktop 은 슬래시를 안전하게 받는다."""
    return str(p).replace("\\", "/")


# ─────────────────────────────────────────────
#  .env seed
# ─────────────────────────────────────────────
def env_file():
    return storage_dir() / ".env"


def searxng_url_for_container():
    name = _c("SEARXNG_CONTAINER", "llm_searxng")
    port = int(_c("SEARXNG_CONTAINER_PORT", 8080))
    return "http://%s:%d" % (name, port)


def _env_lines(model_tag=None, token_limit=4096):
    ollama_port = int(_c("OLLAMA_PORT", 11434))
    model = model_tag or _c("MODEL_TAG", "")
    out = [
        "# AnythingLLM 설정 — PATCH_ANYTHINGLLM 이 최초 1회 생성",
        "# UI 에서 바꾼 값이 여기에 되쓰기되므로 이 파일은 다시 덮어쓰지 않는다.",
        "# 다시 심으려면: anythingllm_runtime.reseed_env()",
        "SERVER_PORT=%d" % CONTAINER_PORT,
        'STORAGE_DIR="%s"' % STORAGE_MOUNT,
        'JWT_SECRET="%s"' % secrets.token_hex(24),
        'DISABLE_TELEMETRY="true"',
        "",
        "# ── LLM: 호스트의 Ollama ──",
        'LLM_PROVIDER="ollama"',
        'OLLAMA_BASE_PATH="http://host.docker.internal:%d"' % ollama_port,
        'OLLAMA_MODEL_PREF="%s"' % model,
        "OLLAMA_MODEL_TOKEN_LIMIT=%d" % int(token_limit),
        "OLLAMA_RESPONSE_TIMEOUT=%d" % OLLAMA_TIMEOUT_MS,
        "",
        "# ── 임베딩 ──",
        'EMBEDDING_ENGINE="%s"' % EMBED_ENGINE,
        'EMBEDDING_MODEL_PREF="%s"' % EMBED_MODEL,
    ]
    if EMBED_BASE_PATH:
        out.append('EMBEDDING_BASE_PATH="%s"' % EMBED_BASE_PATH)
    out += [
        "",
        "# ── 벡터 DB (로컬 파일) ──",
        'VECTOR_DB="%s"' % VECTOR_DB,
        "",
        "# ── 음성 ──",
        'WHISPER_PROVIDER="%s"' % WHISPER,
        'TTS_PROVIDER="%s"' % TTS,
        "",
        "# ── @agent 웹 검색: 자체 호스팅 SearXNG ──",
        'AGENT_SEARXNG_API_URL="%s"' % searxng_url_for_container(),
    ]
    # ANYTHINGLLM_CHROMIUM_ARGS 는 여기 넣지 않는다. 네트워크 모드에 따라 값이
    # 달라지는데 .env 는 1회만 심으므로 stale 이 된다 -> 항상 -e 로 준다.
    if EXTRA_ENV:
        out.append("")
        out.append("# ── config.ANYTHINGLLM_EXTRA_ENV ──")
        for k in sorted(EXTRA_ENV):
            out.append('%s="%s"' % (k, EXTRA_ENV[k]))
    return out


def ensure_env_file(model_tag=None, token_limit=4096):
    """없거나 비어 있으면 심는다. 이미 내용이 있으면 손대지 않는다."""
    f = env_file()
    try:
        if f.is_file() and f.stat().st_size > 0:
            return False
    except OSError:
        pass
    return reseed_env(model_tag=model_tag, token_limit=token_limit)


def reseed_env(model_tag=None, token_limit=4096):
    """강제로 다시 심는다 (UI 설정이 날아감)."""
    body = "\n".join(_env_lines(model_tag, token_limit)) + "\n"
    try:
        # UTF-8, BOM 없음 — BOM 이 들어가면 dotenv 가 첫 키를 못 읽는다
        env_file().write_bytes(body.encode("utf-8"))
        return True
    except OSError:
        return False


# ─────────────────────────────────────────────
#  종료 정리 등록 (warp_runtime._register_exit_cleanup 과 같은 방식)
# ─────────────────────────────────────────────
_CLEANUP_REGISTERED = False


def register_exit_cleanup():
    """런처 종료 시 컨테이너를 정리하도록 lifelog 에 등록(멱등).

    lifelog 의 고아 컨테이너 패턴(_detect_container_patterns + 폴백)에는
    llm_anythingllm / mintplexlabs 가 없다. 등록하지 않으면 런처를 닫아도
    컨테이너가 계속 떠 있는다.
    """
    global _CLEANUP_REGISTERED
    if _CLEANUP_REGISTERED:
        return True
    try:
        try:
            from .core import lifelog as _ll
        except Exception:
            from launcher.core import lifelog as _ll

        def _do():
            try:
                _ll.log("CLEANUP", "AnythingLLM 컨테이너 정리: %s" % CONTAINER)
            except Exception:
                pass
            try:
                stop()
            except Exception:
                pass

        _ll.register_cleanup(_do)
        _CLEANUP_REGISTERED = True
        try:
            _ll.log("INFO", "AnythingLLM 종료 정리 cleanup 등록됨 (%s)" % CONTAINER)
        except Exception:
            pass
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────
#  컨테이너
# ─────────────────────────────────────────────
def image_exists():
    return _run(["docker", "image", "inspect", IMAGE], timeout=30).returncode == 0


def pull(log=None, cancel_check=None):
    """이미지 받기 (3~5GB). cancel_check() 가 True 면 중단한다."""
    args = ["docker", "pull", IMAGE]
    if log is None and cancel_check is None:
        return _run(args, timeout=PULL_TIMEOUT).returncode == 0
    kw = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
          "text": True, "bufsize": 1}
    if _NOWIN:
        kw["creationflags"] = _NOWIN
    try:
        pr = subprocess.Popen(args, **kw)
    except FileNotFoundError:
        if log:
            log("docker 실행 파일을 찾을 수 없습니다")
        return False
    last = ""
    try:
        for line in pr.stdout:
            if cancel_check is not None:
                try:
                    if cancel_check():
                        pr.terminate()
                        if log:
                            log("사용자가 취소했습니다 — 다운로드 중단")
                        return False
                except Exception:
                    pass
            line = (line or "").strip()
            if log and line and line != last:
                last = line
                log(line[:160])
    finally:
        try:
            pr.wait(timeout=30)
        except Exception:
            try:
                pr.kill()
            except Exception:
                pass
    return pr.returncode == 0


def is_running():
    r = _run(["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER], timeout=20)
    return r.returncode == 0 and "true" in (r.stdout or "").lower()


def exists():
    return _run(["docker", "inspect", CONTAINER], timeout=20).returncode == 0


def ensure_network():
    if _run(["docker", "network", "inspect", NETWORK], timeout=20).returncode != 0:
        _run(["docker", "network", "create", NETWORK], timeout=30)


def _remove_stale():
    if exists() and not is_running():
        _run(["docker", "rm", "-f", CONTAINER], timeout=40)


# ─────────────────────────────────────────────
#  네트워크 모드 (WARP / Tor / 직접)  — NET_MODE 정본을 따른다
# ─────────────────────────────────────────────
def net_mode():
    """현재 모드. config.NET_MODE 우선, 없으면 환경변수."""
    m = None
    try:
        m = getattr(_cfg, "NET_MODE", None)
    except Exception:
        m = None
    m = (m or os.environ.get("NET_MODE", "warp") or "warp").strip().lower()
    return m if m in ("warp", "tor", "direct", "none") else "warp"


def net_mode_label(mode=None):
    m = mode or net_mode()
    return {"warp": "WARP 경유 (빠름)",
            "tor": "Tor 경유 (최고 익명)"}.get(m, "직접 연결 (프록시 없음)")


def _http_proxy_for(mode):
    """이 모드에서 Node 가 쓸 수 있는 'http://' 프록시. 없으면 None.

    WARP 는 SOCKS5 전용이라 반드시 HTTP 브리지(llm_httpbridge:8118)를 거친다.
    Tor 는 Privoxy(llm_tor:8118)가 HTTP 프록시를 직접 준다.
    """
    if mode == "tor":
        try:
            u = _cfg.tor_http_proxy()
        except Exception:
            u = "http://%s:%d" % (_c("TOR_CONTAINER", "llm_tor"),
                                  int(_c("TOR_HTTP_PORT", 8118)))
    elif mode == "warp":
        try:
            u = _cfg.http_bridge_proxy()
        except Exception:
            u = "http://%s:%d" % (_c("HTTP_BRIDGE_CONTAINER", "llm_httpbridge"),
                                  int(_c("HTTP_BRIDGE_PORT", 8118)))
    else:
        return None
    # Node 는 socks 를 못 쓴다. http:// 가 아니면 프록시를 걸지 않는다.
    return u if str(u).startswith("http://") else None


def no_proxy_hosts():
    """프록시를 타면 안 되는 대상. Ollama(host.docker.internal) + SearXNG 필수."""
    base = str(_c("NO_PROXY_HOSTS",
                  "host.docker.internal,localhost,127.0.0.1,::1"))
    parts = [x.strip() for x in base.split(",") if x.strip()]
    for extra in (_c("SEARXNG_CONTAINER", "llm_searxng"),
                  _c("HTTP_BRIDGE_CONTAINER", "llm_httpbridge"),
                  _c("WARP_CONTAINER", "llm_warp"),
                  _c("TOR_CONTAINER", "llm_tor"),
                  CONTAINER):
        if extra and extra not in parts:
            parts.append(str(extra))
    for extra in NO_PROXY_EXTRA.split(","):
        extra = extra.strip()
        if extra and extra not in parts:
            parts.append(extra)
    return ",".join(parts)


def proxy_env_for_container(mode=None):
    """컨테이너에 넣을 프록시 환경변수. 직접 연결이면 빈 dict.

    주의 — ALL_PROXY/all_proxy 는 일부러 넣지 않는다.
      config.net_proxy_env() 는 ALL_PROXY=socks5h://... 를 함께 준다(파이썬 쪽 용도).
      그런데 Node 에는 SOCKS 클라이언트가 없고, axios 가 쓰는 proxy-from-env 는
      ALL_PROXY 를 읽어 'socks5h://' 를 HTTP 프록시로 취급한다 -> 전 요청 실패.
    """
    m = mode or net_mode()
    if not NET_AWARE:
        return {}
    hp = _http_proxy_for(m)
    if not hp:
        return {}
    env = {}
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env[k] = hp
    npx = no_proxy_hosts()
    env["NO_PROXY"] = npx
    env["no_proxy"] = npx
    if NODE_ENV_PROXY:
        # Node 내장 fetch 는 기본적으로 HTTP_PROXY 를 무시한다.
        # v22.21+/v24+ 는 이 플래그가 있어야 env 프록시를 따른다.
        # 구버전에서는 그냥 무시되는 값이라 해가 없다.
        env["NODE_USE_ENV_PROXY"] = "1"
    return env


_NODE_BOOTSTRAP_JS = """// proxy-bootstrap.js  (PATCH_ANYTHINGLLM 이 생성 — 직접 수정하지 마세요)
//
// Node 18/20 의 내장 fetch 는 HTTP_PROXY 환경변수를 무시한다.
// (NODE_USE_ENV_PROXY 는 v22.21+/v24+ 전용)
// 설치된 undici 의 ProxyAgent 를 전역 디스패처로 꽂아 강제로 프록시를 태운다.
//
// 중요: NO_PROXY 를 반드시 존중해야 한다. AnythingLLM 의 Ollama 호출도 fetch 를
// 쓰기 때문에, 전부 프록시로 몰면 host.docker.internal 이 프록시 너머에서
// 해석되지 않아 모델 호출이 통째로 죽는다.
(function () {
  try {
    var proxy = process.env.HTTPS_PROXY || process.env.HTTP_PROXY ||
                process.env.https_proxy || process.env.http_proxy || '';
    if (!proxy) { return; }
    var bypass = (process.env.NO_PROXY || process.env.no_proxy || '')
      .split(',').map(function (x) { return x.trim().toLowerCase(); })
      .filter(function (x) { return x.length > 0; });

    var undici = null;
    var tried = ['undici',
                 '/app/server/node_modules/undici',
                 '/app/collector/node_modules/undici',
                 '/app/node_modules/undici'];
    for (var i = 0; i < tried.length; i++) {
      try { undici = require(tried[i]); if (undici && undici.ProxyAgent) break; }
      catch (e) { undici = null; }
    }
    if (!undici || !undici.ProxyAgent || !undici.Agent) {
      console.error('[proxy-bootstrap] undici 를 찾지 못했습니다 - fetch 는 직접 나갑니다');
      return;
    }

    var viaProxy = new undici.ProxyAgent(proxy);
    var direct = new undici.Agent();

    function isBypass(origin) {
      var host = '';
      try { host = new URL(origin).hostname.toLowerCase(); } catch (e) { return false; }
      if (host === 'localhost' || host === '127.0.0.1' || host === '::1') { return true; }
      for (var i = 0; i < bypass.length; i++) {
        var b = bypass[i];
        if (b === '*') { return true; }
        if (host === b) { return true; }
        if (b.charAt(0) === '.' && host.slice(-b.length) === b) { return true; }
        if (host.slice(-(b.length + 1)) === ('.' + b)) { return true; }
      }
      return false;
    }

    function pick(opts) {
      var origin = opts && opts.origin ? String(opts.origin) : '';
      return isBypass(origin) ? direct : viaProxy;
    }

    // Dispatcher 를 상속하지 않는다. undici 의 Dispatcher 는 ES class 라
    // ES5 방식으로 상속하면 "cannot be invoked without 'new'" 로 죽는다.
    // Node 내장 fetch 도 undici.setGlobalDispatcher 도 dispatch 함수만 확인한다.
    var router = {
      dispatch: function (opts, handler) {
        return pick(opts).dispatch(opts, handler);
      },
      close: function () {
        return Promise.all([viaProxy.close(), direct.close()]);
      },
      destroy: function (err) {
        return Promise.all([viaProxy.destroy(err), direct.destroy(err)]);
      }
    };
    // Node 내장 fetch 가 읽는 well-known 심볼. setGlobalDispatcher 도 이걸 세운다.
    globalThis[Symbol.for('undici.globalDispatcher.1')] = router;
    try { if (undici.setGlobalDispatcher) { undici.setGlobalDispatcher(router); } }
    catch (e) { /* 심볼 직접 설정으로 충분 */ }

    console.error('[proxy-bootstrap] fetch -> ' + proxy +
                  '  (bypass: ' + bypass.join(',') + ')');
  } catch (e) {
    try { console.error('[proxy-bootstrap] 실패: ' + (e && e.message)); } catch (e2) {}
  }
})();
"""


def node_bootstrap_host_path():
    return storage_dir() / NODE_BOOTSTRAP_NAME


def write_node_proxy_bootstrap(mode=None):
    """프록시 모드면 부트스트랩을 심고 컨테이너 내부 경로를 돌려준다.

    storage 는 이미 STORAGE_MOUNT 로 마운트돼 있으므로 추가 마운트가 필요 없다.
    직접 연결 모드면 파일을 지우고 None 을 돌려준다.
    """
    f = node_bootstrap_host_path()
    if not NODE_BOOTSTRAP or not NET_AWARE or not _http_proxy_for(mode or net_mode()):
        try:
            if f.exists():
                f.unlink()
        except OSError:
            pass
        return None
    try:
        f.write_bytes(_NODE_BOOTSTRAP_JS.encode("utf-8"))
    except OSError:
        return None
    return STORAGE_MOUNT.rstrip("/") + "/" + NODE_BOOTSTRAP_NAME


def node_bootstrap_container_path(mode=None):
    """부트스트랩이 붙을 컨테이너 내부 경로 (부수효과 없음)."""
    if not NODE_BOOTSTRAP or not NET_AWARE:
        return None
    if not _http_proxy_for(mode or net_mode()):
        return None
    return STORAGE_MOUNT.rstrip("/") + "/" + NODE_BOOTSTRAP_NAME


def node_options(mode=None):
    """컨테이너에 줄 NODE_OPTIONS. 부수효과 없음(파일은 별도로 쓴다)."""
    parts = []
    if NODE_OPTIONS_EXTRA.strip():
        parts.append(NODE_OPTIONS_EXTRA.strip())
    boot = node_bootstrap_container_path(mode)
    if boot:
        parts.append("--require " + boot)
    return " ".join(parts)


def config_signature(mode=None):
    """이 설정으로 만들면 어떤 컨테이너가 되는지를 요약한 서명.

    라벨로 박아두고 다음 기동 때 비교한다. 값이 달라지면 컨테이너를 다시 만든다.
    패치를 올렸는데 낡은 컨테이너가 그대로 재사용되는 사고를 막는 장치다.
    메모리/CPU 는 'auto' 로 매번 달라질 수 있으므로 서명에 넣지 않는다.
    """
    import hashlib
    m = mode or net_mode()
    px = proxy_env_for_container(m)
    parts = [
        IMAGE, str(HOST_PORT), str(CONTAINER_PORT),
        STORAGE_MOUNT, SERVER_ENV_MOUNT, NETWORK,
        ",".join(CAP_ADD),
        "|".join("%s=%s" % (k, px[k]) for k in sorted(px)),
        chromium_args(m),
        node_options(m),
    ]
    return hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()[:12]


def chromium_args(mode=None):
    """내장 Chromium(문서 스크래핑)용 인자. ANYTHINGLLM_CHROMIUM_ARGS 값."""
    args = []
    if not CAP_ADD:
        args += ["--no-sandbox", "--disable-setuid-sandbox"]
    hp = _http_proxy_for(mode or net_mode()) if NET_AWARE else None
    if hp:
        args.append("--proxy-server=" + hp)
        args.append("--proxy-bypass-list=" + no_proxy_hosts().replace(",", ";"))
    return ",".join(args)


def ensure_proxy_stack(log=None, env_path=None):
    """선택한 모드의 프록시 컨테이너를 먼저 띄운다.

    warp: warp_runtime.start() 가 WARP + HTTP 브리지를 함께 보장한다.
    tor : tor_runtime.start(). (NET_MODE!=tor 이면 TOR_GUARD 가 기동을 막는다)
    """
    def _say(m):
        if log:
            try:
                log(m)
            except Exception:
                pass

    m = net_mode()
    if m not in ("warp", "tor") or not NET_AWARE:
        return True
    try:
        if m == "warp":
            try:
                from . import warp_runtime as _rt
            except Exception:
                from launcher import warp_runtime as _rt
        else:
            try:
                from . import tor_runtime as _rt
            except Exception:
                from launcher import tor_runtime as _rt
    except Exception as e:
        _say("프록시 런타임을 불러오지 못했습니다: %r" % e)
        return False
    try:
        try:
            ok = _rt.start(env_path, log_path=None)
        except TypeError:
            ok = _rt.start(env_path, log=lambda x: _say(str(x)))
    except Exception as e:
        _say("프록시 기동 예외: %r" % e)
        return False
    if not ok:
        _say("%s 미기동 — 이 모드에서는 외부 연결이 실패할 수 있습니다." % m.upper())
    return bool(ok)


def container_labels():
    """컨테이너 라벨 전체를 dict 로. Go 템플릿에 따옴표를 넣지 않아
    이스케이프 사고를 원천 차단한다."""
    r = _run(["docker", "inspect", "-f", "{{json .Config.Labels}}", CONTAINER],
             timeout=20)
    if r.returncode != 0:
        return {}
    try:
        return json.loads((r.stdout or "").strip() or "{}") or {}
    except Exception:
        return {}


def running_netmode():
    """실행 중인 컨테이너에 박아둔 모드 라벨. 없으면 None."""
    return container_labels().get(NETMODE_LABEL) or None


def running_cfgsig():
    """실행 중인 컨테이너에 박힌 설정 서명. 없으면 None."""
    return container_labels().get(CFGSIG_LABEL) or None


def build_run_cmd(memory=None, cpus=None):
    """docker run 명령 조립 (진단/테스트에서 그대로 검사할 수 있게 분리)."""
    d = _vol(storage_dir())
    cmd = [
        "docker", "run", "-d",
        "--name", CONTAINER,
        "--network", NETWORK,
        "-p", "%d:%d" % (HOST_PORT, CONTAINER_PORT),
    ]
    for cap in CAP_ADD:
        cmd += ["--cap-add", str(cap)]
    cmd += [
        "-v", d + ":" + STORAGE_MOUNT,
        "-v", d + "/.env:" + SERVER_ENV_MOUNT,
        "-e", "STORAGE_DIR=" + STORAGE_MOUNT,
    ]
    _mode = net_mode()
    write_node_proxy_bootstrap(_mode)          # 실제 파일 기록은 여기서만
    cmd += ["--label", NETMODE_LABEL + "=" + _mode]
    cmd += ["--label", CFGSIG_LABEL + "=" + config_signature(_mode)]
    for _k, _v in sorted(proxy_env_for_container(_mode).items()):
        cmd += ["-e", _k + "=" + _v]
    _ca = chromium_args(_mode)
    if _ca:
        cmd += ["-e", "ANYTHINGLLM_CHROMIUM_ARGS=" + _ca]
    _no = node_options(_mode)
    if _no:
        cmd += ["-e", "NODE_OPTIONS=" + _no]
    m = memory if memory is not None else resolve_memory()
    c = cpus if cpus is not None else resolve_cpus()
    if m:
        cmd.append("--memory=" + str(m))
    if c:
        cmd.append("--cpus=" + str(c))
    cmd.append(IMAGE)          # 이미지는 반드시 마지막
    return cmd


def health_status():
    """컨테이너 HEALTHCHECK 상태. 없으면 빈 문자열."""
    r = _run(["docker", "inspect", "-f",
              "{{if .State.Health}}{{.State.Health.Status}}{{end}}", CONTAINER],
             timeout=20)
    if r.returncode != 0:
        return ""
    return (r.stdout or "").strip()


def probe_urls():
    """기동 확인용 주소. 윈도우에서 localhost 가 ::1 로 먼저 풀리는 경우가 있어
    127.0.0.1 을 먼저 시도한다."""
    out = []
    for h in PROBE_HOSTS.split(","):
        h = h.strip()
        if h:
            out.append("http://%s:%d" % (h, HOST_PORT))
    return out or [URL]


def wait_ready(timeout=None, cancel_check=None, log=None):
    """서버가 HTTP 응답을 낼 때까지 대기. 프록시는 우회한다.

    최초 기동은 1~3분 걸린다(마이그레이션 + 벡터DB 초기화). 그동안 아무 출력이
    없으면 멈춘 것으로 보이므로, PROGRESS_EVERY 초마다 경과/health/컨테이너
    로그 꼬리를 함께 내보낸다.
    """
    total = int(timeout or BOOT_TIMEOUT)
    started = time.time()
    deadline = started + total
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    urls = probe_urls()
    next_tick = started + PROGRESS_EVERY
    last_tail = ""
    while time.time() < deadline:
        if cancel_check is not None:
            try:
                if cancel_check():
                    _emit(log, "사용자가 취소했습니다 — 기동 대기 중단")
                    return False
            except Exception:
                pass
        for u in urls:
            try:
                opener.open(u, timeout=3)
                _emit(log, "응답 확인: %s (%d초 소요)" % (u, int(time.time() - started)), "OK")
                return True
            except urllib.error.HTTPError:
                # 4xx/5xx 도 '서버가 살아 있음' 의 증거
                _emit(log, "응답 확인: %s (%d초 소요)" % (u, int(time.time() - started)), "OK")
                return True
            except Exception:
                pass
        now = time.time()
        if now >= next_tick:
            next_tick = now + PROGRESS_EVERY
            parts = ["초기화 대기 %d/%d초" % (min(int(now - started), total), total)]
            hs = health_status()
            if hs:
                parts.append("상태=" + hs)
            try:
                lines = [x.strip() for x in logs(tail=3).splitlines() if x.strip()]
                tail = lines[-1][:110] if lines else ""
            except Exception:
                tail = ""
            if tail and tail != last_tail:
                last_tail = tail
                parts.append(tail)
            _emit(log, " · ".join(parts))
        time.sleep(2)
    return False


def start(log=None, memory=None, cpus=None, model_tag=None, token_limit=4096,
          cancel_check=None, env_path=None):
    def _say(m, kind="INFO"):
        _emit(log, m, kind)

    register_exit_cleanup()

    _mode = net_mode()
    _say("인터넷 모드: " + net_mode_label(_mode))
    ensure_proxy_stack(log=log, env_path=env_path)

    if is_running():
        _prev = running_netmode()
        _prevsig = running_cfgsig()
        _sig = config_signature(_mode)
        _reason = None
        if _prev and _prev != _mode:
            _reason = "네트워크 모드 %s -> %s" % (_prev, _mode)
        elif not _prevsig:
            _reason = "설정 서명이 없는 구버전 컨테이너"
        elif _prevsig != _sig:
            _reason = "설정이 바뀜 (%s -> %s)" % (_prevsig, _sig)
        if _reason:
            _say("컨테이너를 다시 만듭니다 — " + _reason)
            stop()
        else:
            _say("AnythingLLM 이 이미 실행 중입니다 (설정 동일 %s)." % _sig)
            return wait_ready(cancel_check=cancel_check, log=log)

    ensure_network()
    _remove_stale()
    seeded = ensure_env_file(model_tag=model_tag, token_limit=token_limit)
    _say("설정 파일 %s: %s" % ("생성" if seeded else "기존 유지", env_file()))

    cmd = build_run_cmd(memory=memory, cpus=cpus)
    _say("docker run 실행 (도커 데몬이 방금 켜졌다면 수십 초 걸릴 수 있습니다)")
    _t0 = time.time()
    r = _run(cmd, timeout=180)
    if r.returncode != 0:
        _say("컨테이너 시작 실패: " + ((r.stderr or r.stdout or "")[-300:]), "FAIL")
        return False
    _say("컨테이너 생성 완료 (%d초) — 초기화 대기 중. 최초 실행은 1~3분 걸립니다."
         % int(time.time() - _t0))
    ok = wait_ready(cancel_check=cancel_check, log=log)
    if not ok:
        _hs = health_status()
        if _hs == "healthy":
            _say("컨테이너는 healthy 인데 호스트에서 %d 포트 응답이 없습니다." % HOST_PORT,
                 "WARN")
            _say("포트 게시/방화벽 문제로 보입니다. 확인: docker port " + CONTAINER, "WARN")
        else:
            _say("기동 대기 시간 초과 (컨테이너 상태=%s). 확인: docker logs %s"
                 % (_hs or "?", CONTAINER), "WARN")
    return ok


def stop(remove=True, grace=None):
    """컨테이너 정지/제거.

    -t 를 주지 않으면 docker 가 기본 10초를 기다린다. 런처를 닫을 때마다
    10초가 그대로 체감되므로 짧게 준다(lifelog 도 -t 2 를 쓴다).
    """
    if not exists():
        return True
    g = STOP_GRACE if grace is None else int(grace)
    _run(["docker", "stop", "-t", str(g), CONTAINER], timeout=g + 30)
    if remove:
        _run(["docker", "rm", "-f", CONTAINER], timeout=40)
    return True


def logs(tail=80):
    r = _run(["docker", "logs", "--tail", str(tail), CONTAINER], timeout=30)
    return (r.stdout or "") + (r.stderr or "")


def describe():
    """현재 해석된 설정을 한 줄씩. 진단용."""
    return [
        "image=" + IMAGE,
        "container=" + CONTAINER,
        "url=" + URL,
        "network=" + NETWORK,
        "storage=" + str(storage_dir()),
        "memory=" + str(resolve_memory()),
        "cpus=" + str(resolve_cpus()),
        "cap_add=" + (",".join(CAP_ADD) if CAP_ADD else "(없음)"),
        "embedding=" + EMBED_ENGINE,
        "searxng=" + searxng_url_for_container(),
        "netmode=" + net_mode() + " (" + net_mode_label() + ")",
        "http_proxy=" + (proxy_env_for_container().get("HTTP_PROXY") or "(없음 — 직접 연결)"),
        "no_proxy=" + no_proxy_hosts(),
        "chromium_args=" + (chromium_args() or "(없음)"),
        "node_options=" + (node_options() or "(없음)"),
        "cfgsig=" + config_signature(),
    ]


__all__ = [
    "IMAGE", "CONTAINER", "HOST_PORT", "URL", "NETWORK",
    "storage_dir", "env_file", "ensure_env_file", "reseed_env",
    "searxng_url_for_container", "image_exists", "pull",
    "is_running", "exists", "ensure_network", "build_run_cmd",
    "wait_ready", "start", "stop", "logs", "describe",
    "register_exit_cleanup", "resolve_memory", "resolve_cpus",
    "net_mode", "net_mode_label", "proxy_env_for_container", "no_proxy_hosts",
    "chromium_args", "ensure_proxy_stack", "running_netmode",
    "node_options", "write_node_proxy_bootstrap", "node_bootstrap_host_path",
    "node_bootstrap_container_path", "config_signature", "running_cfgsig",
    "container_labels",
]
# <<< ANYTHINGLLM_v1
