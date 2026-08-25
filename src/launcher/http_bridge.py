"""http_bridge — HTTP 프록시 -> SOCKS5 브리지 컨테이너 (HTTP_BRIDGE_v1).

왜 필요한가
  Cloudflare WARP 는 SOCKS5 만 제공한다. 그런데 local_search MCP 서버의
  검색·본문 수집은 파이썬 표준 urllib 을 쓰고, urllib 은 SOCKS 를 지원하지 않는다.
  HTTP_PROXY=socks5h://... 로 두면 urllib 이 SOCKS 포트에 평문 HTTP 를 보내
  'Connection reset by peer' 로 실패한다.
  (기존 Tor 는 Privoxy(8118) 라는 HTTP 프록시를 함께 제공해서 동작했다.)

해결
  WARP 앞에 HTTP 프록시를 한 단 세운다. 새 서드파티 이미지를 받지 않고,
  이미 있는 샌드박스 이미지(python3)로 순수 표준 라이브러리 브리지를 실행한다.
    urllib --HTTP--> llm_httpbridge:8118 --SOCKS5--> llm_warp:1080 --> 인터넷
  호스트 이름 해석은 SOCKS 서버가 수행한다(socks5h 와 동등, DNS 유출 없음).

Tor 모드에서는 필요 없다(Privoxy 가 이미 HTTP 프록시를 제공).
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import time

try:
    from . import config as _config
except Exception:  # pragma: no cover
    try:
        import config as _config  # type: ignore
    except Exception:
        _config = None


def _c(name, default):
    return getattr(_config, name, default) if _config else default


CONTAINER = _c("HTTP_BRIDGE_CONTAINER", "llm_httpbridge")
PORT = int(_c("HTTP_BRIDGE_PORT", 8118))
HOST_PORT = int(_c("HTTP_BRIDGE_HOST_PORT", 8119))   # Tor 8118 과 충돌 회피
NET = _c("LLM_NETWORK", "llm_net")
WARP_CONTAINER = _c("WARP_CONTAINER", "llm_warp")
WARP_PORT = int(_c("WARP_PORT", 1080))
IMAGE = _c("SANDBOX_IMAGE", "llm-agent-sandbox")
FALLBACK_IMAGE = _c("SEARXNG_IMAGE", "searxng/searxng:latest")

_CREATE_NO_WINDOW = 0x08000000

# ── 컨테이너 안에서 실행되는 브리지 본체 (표준 라이브러리만) ────────────────
BRIDGE_SRC = r'''
import os, socket, sys, threading, select

UPSTREAM = os.environ.get("UPSTREAM", "llm_warp:1080")
_h, _, _p = UPSTREAM.rpartition(":")
UP_HOST, UP_PORT = (_h or "llm_warp"), int(_p or "1080")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "8118"))
TIMEOUT = float(os.environ.get("BRIDGE_TIMEOUT", "30"))


def _recvn(s, n):
    buf = b""
    while len(buf) < n:
        b = s.recv(n - len(buf))
        if not b:
            raise OSError("upstream closed")
        buf += b
    return buf


def socks5_connect(host, port):
    s = socket.create_connection((UP_HOST, UP_PORT), timeout=TIMEOUT)
    s.settimeout(TIMEOUT)
    s.sendall(b"\x05\x01\x00")
    r = _recvn(s, 2)
    if r[0:1] != b"\x05" or r[1:2] != b"\x00":
        s.close()
        raise OSError("socks5 handshake rejected %r" % r)
    hb = host.encode("idna") if all(ord(c) < 128 for c in host) else host.encode("utf-8")
    s.sendall(b"\x05\x01\x00\x03" + bytes([len(hb)]) + hb + int(port).to_bytes(2, "big"))
    rep = _recvn(s, 4)
    if rep[1] != 0:
        s.close()
        raise OSError("socks5 connect failed code=%d" % rep[1])
    atyp = rep[3]
    if atyp == 1:
        _recvn(s, 6)
    elif atyp == 3:
        ln = _recvn(s, 1)[0]
        _recvn(s, ln + 2)
    else:
        _recvn(s, 18)
    return s


def pipe(a, b):
    try:
        while True:
            r, _, x = select.select([a, b], [], [a, b], 60)
            if x or not r:
                return
            for s in r:
                try:
                    data = s.recv(65536)
                except Exception:
                    return
                if not data:
                    return
                (b if s is a else a).sendall(data)
    except Exception:
        pass


def read_headers(sock):
    buf = b""
    while b"\r\n\r\n" not in buf:
        d = sock.recv(4096)
        if not d:
            break
        buf += d
        if len(buf) > 65536:
            break
    return buf


def handle(cli):
    up = None
    try:
        cli.settimeout(TIMEOUT)
        head = read_headers(cli)
        if not head:
            return
        header_part, _, rest = head.partition(b"\r\n\r\n")
        lines = header_part.split(b"\r\n")
        parts = lines[0].decode("latin-1").split()
        if len(parts) < 3:
            return
        method, target, ver = parts[0], parts[1], parts[2]

        if method.upper() == "CONNECT":
            h, _, p = target.rpartition(":")
            up = socks5_connect(h or target, int(p or 443))
            cli.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        else:
            if "://" not in target:
                cli.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                return
            scheme, _, rem = target.partition("://")
            hostport, _, path = rem.partition("/")
            path = "/" + path
            if "@" in hostport:
                hostport = hostport.rpartition("@")[2]
            if hostport.startswith("["):
                h = hostport[1:hostport.index("]")]
                p = hostport[hostport.index("]") + 1:].lstrip(":")
            else:
                h, _, p = hostport.partition(":")
            port = int(p) if p else (443 if scheme == "https" else 80)
            up = socks5_connect(h, port)
            out = [("%s %s %s" % (method, path, ver)).encode("latin-1")]
            for ln in lines[1:]:
                low = ln.lower()
                if low.startswith(b"proxy-connection:") or low.startswith(b"proxy-authorization:"):
                    continue
                out.append(ln)
            up.sendall(b"\r\n".join(out) + b"\r\n\r\n" + rest)
            rest = b""
        if rest:
            up.sendall(rest)
        cli.settimeout(None)
        up.settimeout(None)
        pipe(cli, up)
    except Exception as e:
        # [BRIDGE_LOG_v1] 사유를 stderr 로도 남긴다.
        # 본문에만 쓰면 urllib 이 CONNECT 실패 시 본문을 버려 원인이 사라진다.
        try:
            sys.stderr.write("bridge: FAIL %s <- %s: %s\n"
                             % (locals().get("target", "?"), type(e).__name__, e))
            sys.stderr.flush()
        except Exception:
            pass
        try:
            cli.sendall(("HTTP/1.1 502 Bad Gateway\r\n\r\nbridge: %s\r\n" % e).encode("utf-8"))
        except Exception:
            pass
    finally:
        for s in (cli, up):
            try:
                if s:
                    s.close()
            except Exception:
                pass


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", LISTEN_PORT))
    srv.listen(128)
    sys.stderr.write("bridge: http :%d -> socks5 %s:%d\n" % (LISTEN_PORT, UP_HOST, UP_PORT))
    sys.stderr.flush()
    while True:
        try:
            cli, _ = srv.accept()
        except Exception:
            continue
        threading.Thread(target=handle, args=(cli,), daemon=True).start()


main()
'''


def _docker(args, timeout=60):
    """docker 실행. Windows 에서는 콘솔 창을 띄우지 않는다.

    encoding='utf-8' 고정: Windows 기본 코덱(cp949)으로 UTF-8 출력을 디코드하다
    UnicodeDecodeError 로 죽는 것을 방지한다.
    """
    kw = {"capture_output": True, "text": True, "encoding": "utf-8",
          "errors": "replace", "timeout": timeout}
    if os.name == "nt":
        kw["creationflags"] = _CREATE_NO_WINDOW
    try:
        return subprocess.run([shutil.which("docker") or "docker"] + list(args), **kw)
    except Exception:
        return None


def _ok(r):
    return bool(r and r.returncode == 0)


def proxy_url(inside_net: bool = True) -> str:
    """이 브리지의 HTTP 프록시 URL."""
    if inside_net:
        return "http://%s:%d" % (CONTAINER, PORT)
    return "http://127.0.0.1:%d" % HOST_PORT


def is_running() -> bool:
    r = _docker(["ps", "--filter", "name=^/%s$" % CONTAINER, "--format", "{{.Names}}"], 25)
    return _ok(r) and CONTAINER in (r.stdout or "")


def _exists() -> bool:
    r = _docker(["ps", "-a", "--filter", "name=^/%s$" % CONTAINER, "--format", "{{.Names}}"], 25)
    return _ok(r) and CONTAINER in (r.stdout or "")


def _image_ok(img) -> bool:
    return _ok(_docker(["image", "inspect", img], 25))


def _ensure_net():
    if not _ok(_docker(["network", "inspect", NET], 15)):
        _docker(["network", "create", NET], 20)


def start(log=None) -> bool:
    """브리지 컨테이너 기동. 이미 떠 있으면 True."""
    def _l(m):
        if log:
            try:
                log(m)
            except Exception:
                pass

    if is_running():
        return True
    _ensure_net()
    if _exists():
        _docker(["rm", "-f", CONTAINER], 30)

    img = IMAGE if _image_ok(IMAGE) else (FALLBACK_IMAGE if _image_ok(FALLBACK_IMAGE) else None)
    if img is None:
        _l("HTTP 브리지: 사용할 이미지가 없습니다 (%s / %s)" % (IMAGE, FALLBACK_IMAGE))
        return False

    b64 = base64.b64encode(BRIDGE_SRC.encode("utf-8")).decode("ascii")
    code = "import base64;exec(base64.b64decode('%s').decode('utf-8'))" % b64
    args = [
        "run", "-d", "--name", CONTAINER,
        "--network", NET,
        # NET_CLEANUP_v1: 종료 시 함께 정리되므로 자동 재시작 안 함
        "-e", "UPSTREAM=%s:%d" % (WARP_CONTAINER, WARP_PORT),
        "-e", "LISTEN_PORT=%d" % PORT,
        "-p", "127.0.0.1:%d:%d" % (HOST_PORT, PORT),
        "--entrypoint", "python3",
        img, "-c", code,
    ]
    r = _docker(args, 90)
    if not _ok(r):
        _l("HTTP 브리지 기동 실패: %s" % ((r.stderr if r else "docker 없음") or "").strip()[:160])
        return False

    # 부팅 확인(리스닝까지 잠깐 대기)
    for _ in range(10):
        if is_running():
            time.sleep(0.5)
            _l("HTTP 브리지 준비됨 (%s:%d -> %s:%d)" % (CONTAINER, PORT, WARP_CONTAINER, WARP_PORT))
            return True
        time.sleep(0.5)
    _l("HTTP 브리지 컨테이너가 곧바로 종료됨 — docker logs %s 확인" % CONTAINER)
    return False


def stop() -> None:
    if _exists():
        _docker(["rm", "-f", CONTAINER], 30)


def logs(tail=30) -> str:
    r = _docker(["logs", "--tail", str(tail), CONTAINER], 25)
    return ((r.stdout or "") + (r.stderr or "")) if r else ""
