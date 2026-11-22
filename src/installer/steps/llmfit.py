"""Install the pinned official llmfit Windows release to the shared environment.

Read-only recommendations are optional. A failed update must never break
Ollama, model downloads, Chat or Agent. Download is SHA-256 verified and
extracted without executing external installer scripts.
"""
from __future__ import annotations

import hashlib
import io
import os
import platform
from pathlib import Path
import re
import subprocess
import urllib.request
import zipfile

VERSION = "1.1.20"
BASE = "https://github.com/AlexsJones/llmfit/releases/download/v" + VERSION
MAX_ZIP = 40 * 1024 * 1024
MAX_EXE = 40 * 1024 * 1024


def install(paths, *, log=None):
    notify = log if log is not None else (lambda message: None)
    if os.name != "nt":
        notify("LLMfit: Windows 이외 플랫폼은 설치 생략")
        return False
    machine = platform.machine().lower()
    arch = ("aarch64" if machine in ("arm64", "aarch64") else
            "x86_64" if machine in ("amd64", "x86_64") else None)
    if not arch:
        notify("LLMfit: 지원하지 않는 CPU 아키텍처")
        return False
    exe = Path(paths["env"]) / "llmfit" / "llmfit.exe"
    if exe.is_file() and _version_ok(exe):
        notify("LLMfit " + VERSION + ": 설치 확인")
        return True

    archive = f"llmfit-v{VERSION}-{arch}-pc-windows-msvc.zip"
    url = BASE + "/" + archive
    try:
        checksum_text = _download(url + ".sha256", limit=1024).decode("utf-8")
        match = re.match(r"^([a-fA-F0-9]{64})\\s+", checksum_text.strip())
        if not match:
            raise ValueError("공식 SHA-256 파일 형식이 유효하지 않습니다")
        payload = _download(url, limit=MAX_ZIP)
        actual = hashlib.sha256(payload).hexdigest()
        if actual.lower() != match.group(1).lower():
            raise ValueError("LLMfit ZIP SHA-256 불일치")
        with zipfile.ZipFile(io.BytesIO(payload)) as archive_obj:
            binaries = [
                info for info in archive_obj.infolist()
                if info.filename.replace("\\", "/").split("/")[-1].lower() == "llmfit.exe"
                and not info.is_dir()
            ]
            if len(binaries) != 1 or binaries[0].file_size > MAX_EXE:
                raise ValueError("LLMfit 실행 파일 구성 또는 크기 오류")
            executable_bytes = archive_obj.read(binaries[0])
        if len(executable_bytes) > MAX_EXE:
            raise ValueError("LLMfit 실행 파일 최대 크기 초과")
        exe.parent.mkdir(parents=True, exist_ok=True)
        temporary = exe.with_suffix(".exe.new")
        try:
            temporary.write_bytes(executable_bytes)
            if not _version_ok(temporary):
                raise ValueError("LLMfit 실행 파일 버전 검증 실패")
            os.replace(temporary, exe)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        notify("LLMfit 선택 설치 실패 (기존 추천 기능 유지): " + str(exc))
        return False
    notify("LLMfit " + VERSION + " 설치 완료: " + str(exe))
    return True


def _download(url, *, limit):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Local_AI_Agent", "Accept": "application/octet-stream",
    })
    # Trusted, pinned GitHub release assets only.
    with urllib.request.urlopen(req, timeout=45) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("다운로드 용량 제한 초과")
    return data


def _version_ok(exe):
    try:
        kwargs = {"capture_output": True, "text": True, "timeout": 8,
                  "encoding": "utf-8", "errors": "replace", "check": False}
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000
        result = subprocess.run([str(exe), "--version"], **kwargs)
        return result.returncode == 0 and bool(
            re.search(r"(?<![0-9])" + re.escape(VERSION) + r"(?![0-9])",
                      (result.stdout or "") + " " + (result.stderr or ""))
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
