# -*- coding: utf-8 -*-
"""manage — 모델 관리 단독 진입점 (설치/삭제 통합 창).

MANAGE.bat -> python -m installer.manage
무거운 환경 설치 없이 Ollama 만 확인하고 통합 모델 관리 창을 띄운다.
실제 설치/삭제는 installer.model.download() 가 수행(통합 창 + pull/rm).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _ollama_up(host: str = "http://127.0.0.1:11434") -> bool:
    try:
        urllib.request.urlopen(host + "/api/tags", timeout=2)
        return True
    except Exception:
        return False


def main() -> int:
    root = _root()
    env_dir = root / "llm_environment"
    if not env_dir.exists():
        print("[FAIL] 설치 폴더가 없습니다: " + str(env_dir))
        print("[INFO] 먼저 INSTALL.bat 을 실행하세요.")
        return 1

    paths = {
        "env": env_dir,
        "ollama": env_dir / "ollama_runtime",
        "models": env_dir / "llm_models",
    }

    try:
        from installer.lang_setup import initialize_language
        initialize_language(root)
    except Exception:
        pass

    exe = paths["ollama"] / "ollama.exe"
    if not exe.exists():
        print("[FAIL] ollama.exe 없음: " + str(exe))
        print("[INFO] 먼저 INSTALL.bat 을 실행하세요.")
        return 1

    # Ollama 기동 확인 (없으면 백그라운드 start)
    if not _ollama_up():
        print("[INFO] Ollama 시작 중...")
        try:
            from installer.steps import ollama as _oll
            envv = _oll.env_for(paths)
        except Exception:
            envv = dict(os.environ)
            envv["OLLAMA_MODELS"] = str(paths["models"])
        kw = {}
        if os.name == "nt":
            kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        logf = None
        try:
            logdir = paths["env"] / "logs"
            logdir.mkdir(parents=True, exist_ok=True)
            logf = open(logdir / "ollama_manage.log", "ab")
        except Exception:
            logf = None
        try:
            subprocess.Popen([str(exe), "serve"], env=envv,
                             stdout=logf, stderr=logf, **kw)
        except Exception as e:
            print("[WARN] Ollama 시작 실패: " + repr(e))
        finally:
            if logf is not None:
                try:
                    logf.close()
                except Exception:
                    pass
        for _ in range(20):
            if _ollama_up():
                break
            time.sleep(1)

    if not _ollama_up():
        print("[FAIL] Ollama 에 연결할 수 없습니다. Docker/Ollama 상태를 확인하세요.")
        return 1

    from installer.steps import model as _model
    _model.download(paths)
    print("[OK] 모델 관리 완료.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
