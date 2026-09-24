# -*- coding: utf-8 -*-
# >>> ANYTHINGLLM_v1 (PATCH_ANYTHINGLLM.py 가 생성)  ANYTHINGLLM_REV=9
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

설정은 storage/.env 에 보존한다. AnythingLLM 이 UI 설정을 이 파일에 되쓰기 때문에
전체 파일은 덮어쓰지 않는다. Local AI가 소유하는 Ollama 연결 필드만 Chat 시작 전에
선택 모델/토큰 한도에 맞춰 동기화하며, 나머지 UI 설정은 그대로 보존한다.
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
        f = env_file()
        f.write_bytes(body.encode("utf-8"))
        return True
    except OSError:
        return False


def _env_values():
    """Read simple KEY=VALUE pairs from the persisted AnythingLLM env."""
    values = {}
    try:
        lines = env_file().read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = value.strip().strip('"').strip("'")
    return values


def configured_model():
    """The Ollama model AnythingLLM is currently configured to request."""
    return _env_values().get("OLLAMA_MODEL_PREF", "").strip()


def sync_managed_llm_env(model_tag=None, token_limit=4096):
    """Synchronize only Local AI's Ollama contract and preserve user UI settings.

    AnythingLLM writes other choices back into this file. Re-seeding the whole
    file would erase those settings, while never touching it leaves a stale
    OLLAMA_MODEL_PREF when the user chooses another Chat model.
    """
    model = str(model_tag or _c("MODEL_TAG", "")).strip()
    managed = {
        "LLM_PROVIDER": "ollama",
        "OLLAMA_BASE_PATH": "http://host.docker.internal:%d" % int(_c("OLLAMA_PORT", 11434)),
        "OLLAMA_MODEL_PREF": model,
        "OLLAMA_MODEL_TOKEN_LIMIT": str(int(token_limit)),
        "OLLAMA_RESPONSE_TIMEOUT": str(OLLAMA_TIMEOUT_MS),
    }
    f = env_file()
    try:
        if not f.is_file() or f.stat().st_size <= 0:
            return bool(reseed_env(model_tag=model, token_limit=token_limit))
        lines = f.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False

    seen = set()
    changed = False
    output = []
    for raw in lines:
        stripped = raw.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else ""
        if key in managed:
            replacement = '%s="%s"' % (key, managed[key])
            output.append(replacement)
            seen.add(key)
            if raw != replacement:
                changed = True
        else:
            output.append(raw)
    for key, value in managed.items():
        if key not in seen:
            output.append('%s="%s"' % (key, value))
            changed = True
    if not changed:
        return False
    try:
        f.write_text("\n".join(output) + "\n", encoding="utf-8")
        return True
    except OSError:
        return False


def _host_http_ready():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for url in probe_urls():
        try:
            opener.open(url, timeout=3)
            return True
        except urllib.error.HTTPError:
            return True
        except Exception:
            pass
    return False


def probe_ollama_connection(model_tag=None):
    """Verify AnythingLLM container -> host Ollama and selected model visibility."""
    if not is_running():
        return False, "AnythingLLM container is not running."
    target = str(model_tag or configured_model()).strip()
    port = int(_c("OLLAMA_PORT", 11434))
    script = (
        "const http=require('http');"
        "const target=" + json.dumps(target) + ";"
        "const req=http.get({host:'host.docker.internal',port:" + str(port) + ",path:'/api/tags',timeout:5000},res=>{"
        "let body='';res.on('data',c=>body+=c);res.on('end',()=>{"
        "if(res.statusCode<200||res.statusCode>=300){console.error('ollama-http-'+res.statusCode);process.exitCode=2;return;}"
        "let data;try{data=JSON.parse(body)}catch(e){console.error('ollama-json');process.exitCode=2;return;}"
        "const names=(data.models||[]).flatMap(m=>[m.name||'',m.model||'']).filter(Boolean);"
        "const norm=v=>String(v||'').trim().toLowerCase();"
        "if(target&&!names.some(n=>norm(n)===norm(target))){console.error('model-missing:'+target);process.exitCode=3;return;}"
        "console.log('ollama-ok:'+(target||'(any)'));"
        "});});"
        "req.on('timeout',()=>{console.error('ollama-timeout');req.destroy();process.exitCode=4;});"
        "req.on('error',e=>{console.error('ollama-error:'+e.message);process.exitCode=4;});"
    )
    result = _run(["docker", "exec", CONTAINER, "node", "-e", script], timeout=15)
    detail = ((result.stdout or "") + " " + (result.stderr or "")).strip()
    if result.returncode == 0:
        return True, detail or ("Ollama connected: " + (target or "(any model)"))
    return False, detail or "AnythingLLM cannot reach Ollama."


def is_ready(model_tag=None):
    """Strong Chat readiness: UI responds and container can use host Ollama/model."""
    if not is_running() or not _host_http_ready():
        return False
    ok, _ = probe_ollama_connection(model_tag=model_tag)
    return bool(ok)


_CLEANUP_REGISTERED = False


def register_exit_cleanup():
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


def _network_policy():
    try:
        from . import network_policy
    except Exception:
        from launcher import network_policy
    return network_policy


def net_mode():
    """Return the canonical product network mode."""
    return _network_policy().current_mode().value


def network_for_mode(mode=None):
    """Return the Docker network matching the canonical AnythingLLM mode."""
    selected = _network_policy().normalize_mode(mode or net_mode())
    if selected is _network_policy().NetworkMode.BLOCK:
        return _network_policy().block_network_name()
    return NETWORK


def ensure_network(mode=None):
    selected = _network_policy().normalize_mode(mode or net_mode())
    if selected is _network_policy().NetworkMode.BLOCK:
        return bool(_network_policy().ensure_block_network())
    if _run(["docker", "network", "inspect", NETWORK], timeout=20).returncode != 0:
        created = _run(["docker", "network", "create", NETWORK], timeout=30)
        return created.returncode == 0
    return True


def _remove_stale():
    if exists() and not is_running():
        _run(["docker", "rm", "-f", CONTAINER], timeout=40)


def net_mode_label(mode=None):
    return _network_policy().display_label(mode or net_mode())


def _http_proxy_for(mode):
    m = _network_policy().normalize_mode(mode).value
    env = _network_policy().container_proxy_env(m)
    value = env.get("HTTP_PROXY") or ""
    return value if value.startswith("http://") else None


def no_proxy_hosts():
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
    """AnythingLLM Node proxy env, always carrying the canonical mode marker.

    ALL_PROXY is intentionally omitted because Node/axios may misinterpret
    socks5h URLs as HTTP proxy URLs. HTTP(S)_PROXY remains sufficient here.
    """
    m = _network_policy().normalize_mode(mode or net_mode()).value
    if not NET_AWARE:
        return {"LOCAL_AI_NETWORK_MODE": m}
    env = dict(_network_policy().container_proxy_env(m))
    env.pop("ALL_PROXY", None)
    env.pop("all_proxy", None)
    if m in ("warp", "tor"):
        npx = no_proxy_hosts()
        env["NO_PROXY"] = npx
        env["no_proxy"] = npx
        if NODE_ENV_PROXY:
            env["NODE_USE_ENV_PROXY"] = "1"
    return env


_NODE_BOOTSTRAP_JS = """// proxy-bootstrap.js  (PATCH_ANYTHINGLLM 이 생성 — 직접 수정하지 마세요)
// Protected-mode bootstrap: if routing cannot be installed, terminate Node.
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
      console.error('[proxy-bootstrap] undici ProxyAgent unavailable; protected startup aborted');
      process.exit(78);
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
    globalThis[Symbol.for('undici.globalDispatcher.1')] = router;
    try { if (undici.setGlobalDispatcher) { undici.setGlobalDispatcher(router); } }
    catch (e) { /* direct symbol assignment is sufficient */ }

    console.error('[proxy-bootstrap] fetch -> ' + proxy +
                  '  (bypass: ' + bypass.join(',') + ')');
  } catch (e) {
    try { console.error('[proxy-bootstrap] protected setup failed: ' + (e && e.message)); } catch (e2) {}
    process.exit(78);
  }
})();
"""


def node_bootstrap_host_path():
    return storage_dir() / NODE_BOOTSTRAP_NAME


def write_node_proxy_bootstrap(mode=None):
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
    if not NODE_BOOTSTRAP or not NET_AWARE:
        return None
    if not _http_proxy_for(mode or net_mode()):
        return None
    return STORAGE_MOUNT.rstrip("/") + "/" + NODE_BOOTSTRAP_NAME


def node_options(mode=None):
    parts = []
    if NODE_OPTIONS_EXTRA.strip():
        parts.append(NODE_OPTIONS_EXTRA.strip())
    boot = node_bootstrap_container_path(mode)
    if boot:
        parts.append("--require " + boot)
    return " ".join(parts)


def config_signature(mode=None):
    import hashlib
    m = mode or net_mode()
    px = proxy_env_for_container(m)
    managed = _env_values()
    managed_sig = "|".join(
        "%s=%s" % (key, managed.get(key, ""))
        for key in (
            "LLM_PROVIDER", "OLLAMA_BASE_PATH", "OLLAMA_MODEL_PREF",
            "OLLAMA_MODEL_TOKEN_LIMIT", "OLLAMA_RESPONSE_TIMEOUT",
        )
    )
    parts = [
        IMAGE, str(HOST_PORT), str(CONTAINER_PORT),
        STORAGE_MOUNT, SERVER_ENV_MOUNT, network_for_mode(m),
        ",".join(CAP_ADD),
        "|".join("%s=%s" % (k, px[k]) for k in sorted(px)),
        chromium_args(m),
        node_options(m),
        managed_sig,
    ]
    return hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()[:12]


def chromium_args(mode=None):
    args = []
    if not CAP_ADD:
        args += ["--no-sandbox", "--disable-setuid-sandbox"]
    hp = _http_proxy_for(mode or net_mode()) if NET_AWARE else None
    if hp:
        args.append("--proxy-server=" + hp)
        args.append("--proxy-bypass-list=" + no_proxy_hosts().replace(",", ";"))
    return ",".join(args)


def ensure_proxy_stack(log=None, env_path=None):
    """Prepare WARP/Tor through the canonical network policy."""
    m = net_mode()
    if m not in ("warp", "tor"):
        return True
    if not NET_AWARE:
        if log:
            try:
                log("보호 네트워크 모드에서는 AnythingLLM 네트워크 연동을 끌 수 없습니다.")
            except Exception:
                pass
        return False
    return bool(_network_policy().prepare_runtime(m, env_path=env_path, log=log))


def container_labels():
    r = _run(["docker", "inspect", "-f", "{{json .Config.Labels}}", CONTAINER],
             timeout=20)
    if r.returncode != 0:
        return {}
    try:
        return json.loads((r.stdout or "").strip() or "{}") or {}
    except Exception:
        return {}


def running_netmode():
    return container_labels().get(NETMODE_LABEL) or None


def running_cfgsig():
    return container_labels().get(CFGSIG_LABEL) or None


def build_run_cmd(memory=None, cpus=None):
    d = _vol(storage_dir())
    _mode = net_mode()
    cmd = [
        "docker", "run", "-d",
        "--name", CONTAINER,
        "--network", network_for_mode(_mode),
        "--add-host", "host.docker.internal:host-gateway",
        "-p", "127.0.0.1:%d:%d" % (HOST_PORT, CONTAINER_PORT),
    ]
    for cap in CAP_ADD:
        cmd += ["--cap-add", str(cap)]
    cmd += [
        "-v", d + ":" + STORAGE_MOUNT,
        "-v", d + "/.env:" + SERVER_ENV_MOUNT,
        "-e", "STORAGE_DIR=" + STORAGE_MOUNT,
    ]
    write_node_proxy_bootstrap(_mode)
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
    cmd.append(IMAGE)
    return cmd


def health_status():
    r = _run(["docker", "inspect", "-f",
              "{{if .State.Health}}{{.State.Health.Status}}{{end}}", CONTAINER],
             timeout=20)
    if r.returncode != 0:
        return ""
    return (r.stdout or "").strip()


def probe_urls():
    out = []
    for h in PROBE_HOSTS.split(","):
        h = h.strip()
        if h:
            out.append("http://%s:%d" % (h, HOST_PORT))
    return out or [URL]


def wait_ready(timeout=None, cancel_check=None, log=None):
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
    if _mode in ("warp", "tor") and not ensure_proxy_stack(log=log, env_path=env_path):
        _say("보호 네트워크 준비에 실패하여 AnythingLLM 시작을 중단합니다.", "FAIL")
        return False
    if _mode == "block" and not _network_policy().ensure_block_network(log=log):
        _say("Block 네트워크 준비에 실패하여 AnythingLLM 시작을 중단합니다.", "FAIL")
        return False

    model = str(model_tag or _c("MODEL_TAG", "")).strip()
    changed = sync_managed_llm_env(model_tag=model, token_limit=token_limit)
    configured = configured_model()
    if model and configured != model:
        _say("Chat LLM 설정 저장 실패: requested=%s configured=%s" %
             (model, configured or "(empty)"), "FAIL")
        return False
    _say("Chat LLM 설정 %s: model=%s · Ollama=host.docker.internal:%s" % (
        "동기화" if changed else "확인",
        configured or model or "(default)",
        int(_c("OLLAMA_PORT", 11434)),
    ))

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
            if not wait_ready(cancel_check=cancel_check, log=log):
                return False
            connected, detail = probe_ollama_connection(model)
            _say(("Ollama 연결 검증 완료: " if connected else "Ollama 연결 검증 실패: ") + detail,
                 "OK" if connected else "FAIL")
            return connected

    if not ensure_network(_mode):
        _say("Docker 네트워크를 준비할 수 없어 AnythingLLM 시작을 중단합니다.", "FAIL")
        return False
    _remove_stale()
    _say("설정 파일 준비: %s" % env_file())

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
        return False
    connected, detail = probe_ollama_connection(model)
    _say(("Ollama 연결 검증 완료: " if connected else "Ollama 연결 검증 실패: ") + detail,
         "OK" if connected else "FAIL")
    return connected


def stop(remove=True, grace=None):
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
    return [
        "image=" + IMAGE,
        "container=" + CONTAINER,
        "url=" + URL,
        "network=" + network_for_mode(),
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
    "configured_model", "sync_managed_llm_env", "probe_ollama_connection", "is_ready",
    "searxng_url_for_container", "image_exists", "pull",
    "is_running", "exists", "ensure_network", "network_for_mode", "build_run_cmd",
    "wait_ready", "start", "stop", "logs", "describe",
    "register_exit_cleanup", "resolve_memory", "resolve_cpus",
    "net_mode", "net_mode_label", "proxy_env_for_container", "no_proxy_hosts",
    "chromium_args", "ensure_proxy_stack", "running_netmode",
    "node_options", "write_node_proxy_bootstrap", "node_bootstrap_host_path",
    "node_bootstrap_container_path", "config_signature", "running_cfgsig",
    "container_labels",
]
# <<< ANYTHINGLLM_v1