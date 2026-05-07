"""searxng_runtime — SearXNG 컨테이너 시작/정지/상태 확인.

run.py 가 채팅 시작 시 자동 호출하거나, 사용자가 메뉴에서 직접 제어.

이번 버전 변경 사항 (v3):
  - STARTUP_TIMEOUT_SEC = 60 (was 20). 콜드 부팅이 25~35초 걸리는 사례 대비.
  - is_running() 을 컨테이너/HTTP 두 단계로 분리해서 어디서 막혔는지 진단 가능.
  - 타임아웃 시 docker logs --tail 50 자동 캡처.
  - HTTP 응답을 2xx 만 통과 (5xx 도 응답이지만 SearXNG 가 아직 준비 안 된 상태).
  - log_path 인자로 모든 단계 파일 로깅 가능.
  - **NEW v3**: 시작 직전 limiter.toml 호환성 자가 치유.
       구버전 installer 가 만든 invalid limiter.toml 이 SearXNG 2026.x 와 충돌해
       worker 가 즉시 죽는 문제를 자동 감지·격리·복구.
  - **NEW (프록시 통합)**: Tor 프록시 컨테이너 자동 가동/정지/삭제 관리 기능 추가.
"""
from __future__ import annotations

import datetime
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from . import ui

CONTAINER = "llm_searxng"
IMAGE     = "searxng/searxng:latest"
HOST_PORT = 8888
URL       = f"http://localhost:{HOST_PORT}"

# 첫 부팅(콜드 스타트) 시 SearXNG 가 25~35초 걸리는 경우가 있어 여유 있게 60 으로 설정.
STARTUP_TIMEOUT_SEC = 60

# limiter.toml 에 들어가면 SearXNG 2026.x 의 스키마 검증을 깨뜨리는 키 목록.
# 이 키들 중 하나라도 발견되면 limiter.toml 전체를 격리한다 (server.limiter: false
# 라면 어차피 이 파일이 필요 없으므로 안전).
DEPRECATED_LIMITER_KEYS = (
    # 옛 이름. 새 SearXNG 는 pass_searxng_org (n 추가).
    "pass_searx_org",
)


# ───────── 파일 로그 (선택적) ─────────

def _flog(log_path: Optional[Path], level: str, msg: str) -> None:
    """디버그 로그를 파일에 append. log_path 가 None 이거나 실패하면 조용히 무시."""
    if log_path is None:
        return
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] [{level:5}] [searxng] {msg}\n")
    except OSError:
        pass


# ==============================================================
#  추가됨: Tor 프록시 자동 관리 로직
# ==============================================================
def _ensure_tor_proxy(quiet: bool = False, log_path: Optional[Path] = None):
    """Tor 프록시 컨테이너가 없으면 만들고, 꺼져있으면 켭니다."""
    _flog(log_path, "INFO", "Tor 프록시 상태 확인 중...")
    try:
        r = subprocess.run(["docker", "inspect", "tor-proxy"], capture_output=True)
        if r.returncode != 0:
            if not quiet: ui.info("Tor 프록시 컨테이너 자동 생성 중...")
            _flog(log_path, "INFO", "Tor 프록시 컨테이너 생성 및 시작")
            subprocess.run([
                "docker", "run", "-d",
                "--name", "tor-proxy",
                "--restart", "unless-stopped",
                "-p", "9050:9050",
                "peterdavehello/tor-socks-proxy"
            ], check=False, capture_output=True)
        else:
            # 컨테이너가 이미 존재하면 무조건 시작 명령
            _flog(log_path, "INFO", "기존 Tor 프록시 시작")
            subprocess.run(["docker", "start", "tor-proxy"], check=False, capture_output=True)
    except Exception as e:
        _flog(log_path, "FAIL", f"Tor 프록시 제어 실패: {e}")
# ==============================================================


# ───────── 자가 치유 ─────────

def _heal_limiter_toml(cfg_dir: Path,
                       log_path: Optional[Path] = None) -> bool:
    """limiter.toml 에 호환성 깨는 키가 있으면 격리한다.

    Returns:
        True  — 파일이 정상이거나 없거나, 격리 후 깨끗해짐 (시작 진행 가능)
        False — 격리 시도가 실패함 (드물지만 디스크 권한 등)
    """
    limiter = cfg_dir / "limiter.toml"
    if not limiter.exists():
        # 파일이 없는 게 가장 좋음 — SearXNG 가 기본 스키마로 동작
        _flog(log_path, "INFO", "limiter.toml 없음 — SearXNG 기본값 사용 (정상)")
        return True

    try:
        text = limiter.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        _flog(log_path, "WARN", f"limiter.toml 읽기 실패: {e} — 그대로 둠")
        return True  # 읽지 못하는 건 우리 책임 아님 — 그냥 진행

    bad_keys = [k for k in DEPRECATED_LIMITER_KEYS if k in text]
    if not bad_keys:
        _flog(log_path, "INFO", "limiter.toml 호환성 OK")
        return True

    _flog(log_path, "WARN",
          f"limiter.toml 에 deprecated 키 발견: {bad_keys} — 격리 진행")

    # 타임스탬프 백업 후 원본 제거
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    quarantine = cfg_dir / f"limiter.toml.broken-{ts}"
    try:
        shutil.move(str(limiter), str(quarantine))
        _flog(log_path, "INFO", f"limiter.toml 격리됨: {quarantine.name}")
        ui.warn(f"이전 SearXNG 설정의 한 파일이 새 버전과 호환되지 않아 격리했습니다:")
        ui.warn(f"  {quarantine}")
        ui.info("SearXNG 는 안전한 기본값으로 시작합니다 (검색 기능 정상)")
        return True
    except OSError as e:
        _flog(log_path, "FAIL", f"limiter.toml 격리 실패: {e}")
        ui.err(f"limiter.toml 격리 실패: {e}")
        ui.warn(f"수동으로 다음 파일을 삭제하거나 이름 변경하세요: {limiter}")
        return False


# ───────── 상태 확인 ─────────

def is_container_running() -> bool:
    """컨테이너 자체의 실행 상태만 확인 (HTTP 미체크)."""
    try:
        r = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0 and "true" in r.stdout.lower()
    except Exception:
        return False


def is_http_responding() -> bool:
    """SearXNG HTTP 엔드포인트가 2xx 응답 가능한지.

    5xx 는 컨테이너는 떠있지만 내부 초기화 미완료 상태이므로 False 처리한다.
    """
    try:
        with urllib.request.urlopen(URL, timeout=3) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        # 4xx/5xx 명시적 응답 — 아직 준비 안 됨
        return 200 <= e.code < 300
    except Exception:
        return False


def is_running() -> bool:
    """SearXNG 컨테이너가 실행 중인지 + HTTP 응답 가능한지 (외부 호환성 유지)."""
    return is_container_running() and is_http_responding()


def container_exists() -> bool:
    """이미 만들어진 컨테이너가 있는지 (실행 여부 무관)."""
    try:
        r = subprocess.run(
            ["docker", "inspect", CONTAINER],
            capture_output=True, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def image_exists() -> bool:
    try:
        r = subprocess.run(
            ["docker", "image", "inspect", IMAGE],
            capture_output=True, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def fetch_container_logs(tail: int = 50) -> str:
    """컨테이너 로그 마지막 N줄을 가져온다 (디버그용).

    컨테이너가 시작 후 즉시 죽거나 HTTP 응답이 없을 때 원인 추적용.
    """
    try:
        r = subprocess.run(
            ["docker", "logs", "--tail", str(tail), CONTAINER],
            capture_output=True, text=True, timeout=5,
        )
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return f"<로그 가져오기 실패: {e}>"


# ───────── 시작 / 정지 ─────────

def start(env: Path, quiet: bool = False, log_path: Optional[Path] = None) -> bool:
    """SearXNG 컨테이너 시작. 이미 실행 중이면 그대로 둠.

    Args:
        env: llm_environment 경로
        quiet: True면 이미 가동 중일 때 메시지 생략
        log_path: 디버그 로그 파일 경로 (None 이면 파일 로그 비활성)

    Returns:
        True if running after this call
    """
    _flog(log_path, "INFO", f"start() called, container_exists={container_exists()}")

    # ─── Tor 프록시 자동 시작 연동 ───
    _ensure_tor_proxy(quiet, log_path)

    if is_running():
        _flog(log_path, "INFO", "already running, returning True")
        if not quiet:
            ui.ok(f"SearXNG 이미 가동 중: {URL}")
        return True

    if not image_exists():
        _flog(log_path, "FAIL", f"image missing: {IMAGE}")
        ui.err(f"SearXNG 이미지가 없습니다: {IMAGE}")
        ui.warn("install.py 를 다시 실행하세요")
        return False

    cfg = env / "searxng" / "config"
    if not (cfg / "settings.yml").exists():
        _flog(log_path, "FAIL", f"settings.yml missing: {cfg / 'settings.yml'}")
        ui.err(f"settings.yml 없음: {cfg / 'settings.yml'}")
        ui.warn("install.py 를 다시 실행하세요")
        return False

    # ─── 자가 치유: limiter.toml 호환성 검증 ───
    # 컨테이너 시작 전에 반드시 수행. 잘못된 limiter.toml 이 마운트되면
    # SearXNG worker 가 즉시 사망하므로 컨테이너 자체는 떠 있는 것처럼 보임.
    _flog(log_path, "INFO", "limiter.toml 호환성 검증 중…")
    if not _heal_limiter_toml(cfg, log_path):
        return False

    # 만약 컨테이너가 이전에 깨진 limiter.toml 로 한 번 시작된 적 있다면
    # 격리한 뒤에 컨테이너를 재생성해야 변경이 반영된다 (마운트는 시작 시 고정).
    # → restart 시 새 파일 상태로 재마운트되므로 docker start 만으로도 됨,
    #   다만 컨테이너가 좀비처럼 떠있는 상태일 수 있어 강제로 한 일 정지.
    if container_exists() and is_container_running():
        _flog(log_path, "INFO", "이미 떠있는 컨테이너 정지 (마운트 새로 적용)")
        try:
            subprocess.run(
                ["docker", "stop", "-t", "5", CONTAINER],
                capture_output=True, timeout=10,
            )
        except Exception:
            pass

    # 기존 컨테이너 (멈춰있는 상태) 가 있으면 start
    if container_exists():
        ui.info("기존 SearXNG 컨테이너 재시작…")
        _flog(log_path, "INFO", "container exists, attempting docker start")
        try:
            r = subprocess.run(
                ["docker", "start", CONTAINER],
                check=True, capture_output=True, timeout=15,
            )
            _flog(log_path, "INFO",
                  f"docker start ok: {r.stdout.decode(errors='ignore').strip()}")
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr.decode(errors="ignore") if e.stderr else str(e)
            _flog(log_path, "WARN", f"docker start failed: {err_msg.strip()}")
            ui.warn("재시작 실패 — 컨테이너 삭제 후 새로 만들기")
            subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True)
            if not _create_new(cfg, log_path):
                return False
        except subprocess.TimeoutExpired:
            _flog(log_path, "FAIL", "docker start timeout (15s)")
            ui.err("docker start 명령 타임아웃 — Docker 데몬 응답 확인 필요")
            return False
    else:
        _flog(log_path, "INFO", "no existing container, creating new")
        if not _create_new(cfg, log_path):
            return False

    # ─── 가동 대기 ─────────────────────────
    # 컨테이너 실행과 HTTP 응답을 분리해서 추적해야 어디서 막혔는지 알 수 있다.
    _flog(log_path, "INFO", f"waiting for startup (max {STARTUP_TIMEOUT_SEC}s)")
    container_up_at: Optional[int] = None
    container_died_at: Optional[int] = None  # 한 번 떴다가 죽은 시점

    for i in range(STARTUP_TIMEOUT_SEC):
        cont_up = is_container_running()

        if cont_up:
            if container_up_at is None:
                container_up_at = i + 1
                _flog(log_path, "INFO", f"container Running=true at {container_up_at}s")
        else:
            # 컨테이너가 한 번 떴다가 죽은 경우 — 빠른 실패
            if container_up_at is not None and container_died_at is None:
                container_died_at = i + 1
                _flog(log_path, "FAIL",
                      f"container died at {container_died_at}s after first up")
                # 추가 대기는 의미 없음
                break

        if cont_up and is_http_responding():
            _flog(log_path, "INFO", f"HTTP responsive at {i + 1}s — startup complete")
            if not quiet:
                ui.ok(f"SearXNG 가동: {URL}  ({i + 1}초)")
            return True

        time.sleep(1)

    # ─── 타임아웃 또는 조기 사망 — 진단 정보 수집 ──
    final_cont = is_container_running()
    final_http = is_http_responding()
    _flog(log_path, "FAIL",
          f"FAILED — container_running={final_cont}, http_responding={final_http}, "
          f"container_first_up_at={container_up_at}, container_died_at={container_died_at}")

    if container_died_at is not None:
        ui.err(f"SearXNG 컨테이너가 시작 후 {container_died_at}초만에 종료됨")
        ui.warn("→ 컨테이너 로그에서 종료 원인을 확인하세요")
    elif final_cont and not final_http:
        ui.err(f"SearXNG 시작 타임아웃 ({STARTUP_TIMEOUT_SEC}초): "
               f"컨테이너는 가동 중이나 HTTP 응답 없음")
        ui.warn("→ settings.yml 또는 limiter.toml 문제일 가능성")
    elif not final_cont:
        ui.err(f"SearXNG 시작 타임아웃 ({STARTUP_TIMEOUT_SEC}초): "
               f"컨테이너가 실행 상태가 아님 (시작 직후 종료됨)")
    else:
        ui.err(f"SearXNG 시작 타임아웃 ({STARTUP_TIMEOUT_SEC}초)")

    # 컨테이너 로그 캡처 — 콘솔에 마지막 몇 줄, 파일에 전체
    container_logs = fetch_container_logs(tail=50)
    _flog(log_path, "DEBUG", "=== container logs (tail 50) ===")
    for line in container_logs.splitlines():
        _flog(log_path, "DEBUG", f"  | {line}")
    _flog(log_path, "DEBUG", "=== end container logs ===")

    last_lines = [ln for ln in container_logs.splitlines() if ln.strip()][-5:]
    if last_lines:
        ui.warn("컨테이너 마지막 로그:")
        for line in last_lines:
            print(f"    {line}")

    if log_path:
        ui.info(f"자세한 로그: {log_path}")

    return False


def _create_new(cfg: Path, log_path: Optional[Path] = None) -> bool:
    """새 컨테이너를 docker run -d 로 생성."""
    ui.info("SearXNG 컨테이너 생성…")
    _flog(log_path, "INFO", f"docker run -d, mount={cfg}")
    try:
        r = subprocess.run(
            [
                "docker", "run", "-d",
                "--name", CONTAINER,
                "--restart", "unless-stopped",
                "-p", f"{HOST_PORT}:8080",
                "-v", f"{cfg}:/etc/searxng:rw",
                IMAGE,
            ],
            check=True, capture_output=True, timeout=30,
        )
        _flog(log_path, "INFO",
              f"container created: {r.stdout.decode(errors='ignore').strip()}")
        return True
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr.decode(errors="ignore")
        _flog(log_path, "FAIL", f"docker run failed: {err_msg.strip()}")
        ui.err(f"컨테이너 생성 실패: {err_msg[:200]}")
        return False
    except subprocess.TimeoutExpired:
        _flog(log_path, "FAIL", "docker run timeout (30s)")
        ui.err("컨테이너 생성 타임아웃 — Docker 데몬 응답 확인 필요")
        return False


def stop():
    """SearXNG 및 Tor 프록시 컨테이너 정지."""
    # ─── Tor 프록시 동시 정지 ───
    try:
        subprocess.run(["docker", "stop", "tor-proxy"], capture_output=True, timeout=10)
    except Exception:
        pass

    if not container_exists():
        ui.info("SearXNG 컨테이너 없음")
        return
    ui.info("SearXNG 및 Tor 프록시 정지…")
    try:
        subprocess.run(
            ["docker", "stop", CONTAINER],
            check=True, capture_output=True, timeout=15,
        )
        ui.ok("정지 완료")
    except subprocess.CalledProcessError:
        ui.err("정지 실패")


def remove():
    """컨테이너 삭제 (이미지는 보존). Tor 프록시도 함께 삭제."""
    stop()
    try:
        # ─── Tor 프록시 동시 삭제 ───
        subprocess.run(["docker", "rm", "-f", "tor-proxy"], capture_output=True, timeout=10)

        subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True, timeout=10)
        ui.ok("컨테이너 삭제 완료")
    except Exception:
        pass