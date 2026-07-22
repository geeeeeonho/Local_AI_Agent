"""searxng — 로컬 SearXNG Docker 컨테이너 자동 설치 + 무필터 설정.

작동 원리:
  - Docker 이미지 pull: searxng/searxng (공식)
  - settings.yml 자동 생성: SafeSearch=0, JSON API 활성화, Tor 프록시 연결
  - 컨테이너 자체는 install 단계에서 만들지 않음 (이름만 예약)
  - 실제 컨테이너 시작/정지는 launcher/searxng_runtime.py 가 담당
"""
from __future__ import annotations

import secrets
import subprocess
from pathlib import Path
from typing import Dict

from installer import utils

CONTAINER_NAME = "llm_searxng"
IMAGE          = "searxng/searxng:latest"
HOST_PORT      = 8888  # Open WebUI 가 8080 쓰므로 충돌 회피


# Open WebUI 와 호환되도록 JSON 포맷을 활성화하고 SafeSearch=0 으로 설정
# 추가됨: outgoing 프록시를 통해 모든 검색 트래픽이 Tor 네트워크(9050 포트)를 통과하도록 설정
def _settings_yml(secret: str) -> str:
    return f"""# SearXNG 설정 — 자동 생성됨 (LLM 환경)
# 무필터 검색을 위한 설정 및 익명화를 위한 Tor 프록시 설정

use_default_settings: true

# ===== proxy / Tor (INSTALLER_NET_v1) =====
# ASCII only on purpose: non-ASCII here has been corrupted by PowerShell
# edits before, and SearXNG then refuses to start.
#   * key MUST be "all://" - newer httpx rejects the bare "all" and every
#     engine then dies with "unexpected crash" (search returns 0 results)
#   * target MUST be the container name - on Docker Desktop containers
#     cannot reach each other through host.docker.internal
outgoing:
  proxies:
    "all://": socks5h://llm_tor:9050
  request_timeout: 15.0
  max_request_timeout: 30.0
# ==========================================

general:
  debug: false
  instance_name: "Local LLM SearXNG"

server:
  secret_key: "{secret}"
  limiter: false                   # 자체 호스팅이므로 rate limit 끄기
  image_proxy: false
  port: 8080
  bind_address: "0.0.0.0"

search:
  safe_search: 0                   # 0=없음, 1=중간, 2=엄격
  autocomplete: ""
  default_lang: ""
  formats:
    - html
    - json                         # Open WebUI 가 JSON 사용

ui:
  static_use_hash: true

# 엔진별 가중치는 default 사용. 특정 엔진 끄려면 여기서 disabled: true
engines:
  - name: google
    disabled: false
  - name: duckduckgo
    disabled: false
  - name: bing
    disabled: false
  - name: brave
    disabled: false
"""


# limiter.toml — bot 검사 비활성 (Open WebUI 가 정상 클라이언트로 인식되도록)
LIMITER_TOML = """[botdetection.ip_limit]
link_token = false

[botdetection.ip_lists]
pass_searx_org = false
"""


def install(paths: Dict[str, Path]):
    """SearXNG 설정 파일 생성 + 이미지 pull. 컨테이너는 만들지 않음."""
    from installer.i18n import t

    utils.section(t("install.searxng_section"))

    # ─── 설정 폴더 ───
    cfg_dir = paths["env"] / "searxng" / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    utils.ok(t("install.searxng_config_dir", path=str(cfg_dir)))

    # ─── settings.yml ───
    settings_path = cfg_dir / "settings.yml"
    if settings_path.exists():
        utils.ok(t("install.searxng_settings_reused", path=str(settings_path)))
    else:
        secret = secrets.token_hex(32)
        settings_path.write_text(_settings_yml(secret), encoding="utf-8")
        utils.ok(t("install.searxng_settings_created", path=str(settings_path)))

    # ─── limiter.toml (INSTALLER_NET_v1: 생성하지 않음) ───
    # 최신 searxng 이미지와 스키마가 맞지 않아 부팅 중 TypeError 로 컨테이너가
    # 즉사한다("schema of /etc/searxng/limiter.toml is invalid!").
    # limiter 는 settings.yml 의 limiter:false 로 이미 비활성이므로 파일이 없는
    # 편이 안전하다(없으면 이미지 내장 기본값을 사용).
    limiter_path = cfg_dir / "limiter.toml"
    if limiter_path.exists():
        try:
            limiter_path.unlink()
            utils.ok("limiter.toml 제거 (이미지 기본값 사용)")
        except Exception:
            utils.warn("limiter.toml 제거 실패: " + str(limiter_path))

    # ─── 이미지 pull ───
    utils.info(t("install.searxng_pulling", image=IMAGE))
    utils.warn(t("install.searxng_pull_size"))
    try:
        subprocess.run(["docker", "pull", IMAGE], check=True)
        utils.ok(t("install.searxng_pull_ok"))
    except subprocess.CalledProcessError:
        utils.err(t("install.searxng_pull_fail"))
        return

    # SEARXNG_HARDEN_v1: Tor SOCKS 프록시 이미지도 함께 받음 (검색 익명화에 필요)
    try:
        utils.info("Tor 프록시 이미지 pull: dperson/torproxy")
        subprocess.run(["docker", "pull", "dperson/torproxy"], check=True)
        utils.ok("Tor 이미지 준비 완료")
    except subprocess.CalledProcessError:
        utils.warn("Tor 이미지 pull 실패 - 검색 익명화가 제한될 수 있습니다 "
                   "(수동: docker pull dperson/torproxy)")

    utils.ok(t("install.searxng_ready", name=CONTAINER_NAME, port=HOST_PORT))