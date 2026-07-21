# -*- coding: utf-8 -*-
"""manage_gui — MANAGE 대시보드 (MANAGE_GUI_v2, 완전 임베드).

MANAGE.bat -> python -m installer.manage_gui
한 창에서: 진단(상태) + 클래스별 사다리 모델 관리(설치/삭제) + 진행 로그.
모델 pull/rm 은 **새 콘솔 없이** 창 안 로그로 스트리밍. 오직 명시적 [적용] 에서
체크된 것만 처리 -> '선택 안 한 것 자동 설치' 경로 없음. 삭제는 화면에 표시된
모델(관리 대상)만 대상 -> 다른 모델 보호.

tkinter/공용모듈은 지연 임포트 — 모듈 임포트/헬퍼는 headless 에서도 동작.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

_BG = "#1e1e1e"
_CARD = "#252526"
_DIM = "#9d9d9d"
_ACC = "#0e639c"
_ACC_HI = "#1177bb"
_OK = "#4ec9b0"
_WARN = "#d7ba7d"
_ERR = "#f48771"
_STAR = "#dcdcaa"
_LINE = "#3c3c3c"


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _ollama_exe() -> str:
    exe = _root() / "llm_environment" / "ollama_runtime" / "ollama.exe"
    return str(exe) if exe.exists() else "ollama"


def _new_console_flags() -> dict:
    kw: dict = {}
    if os.name == "nt":
        kw["creationflags"] = 0x00000010  # CREATE_NEW_CONSOLE
    return kw


def _spawn_module(mod: str) -> None:
    try:
        subprocess.Popen([sys.executable, "-m", mod], cwd=str(_root()),
                         **_new_console_flags())
    except Exception as e:
        print("[WARN] 실행 실패: %s (%r)" % (mod, e))


# ── 상태(진단) ─────────────────────────────────────────────────────────
def _daemon_alive():
    # DOCKER_DAEMON_v1: CLI 설치 여부가 아니라 '데몬 응답(docker info)' 을 본다
    try:
        from launcher.services.docker import DockerService
        return DockerService.daemon_alive()
    except Exception:
        try:
            return subprocess.run(["docker", "info"], capture_output=True,
                                  timeout=8).returncode == 0
        except Exception:
            return False


def _check_docker():
    if _daemon_alive():
        return True, "실행 중 (데몬 응답)"
    try:
        r = subprocess.run(["docker", "--version"], capture_output=True,
                           text=True, timeout=6)
        if r.returncode == 0:
            return False, "설치됨·데몬 미기동 — Docker Desktop 을 실행하세요"
    except Exception:
        pass
    return False, "없음 (샌드박스·SearXNG·Tor 비활성)"


def _check_ollama(host="http://127.0.0.1:11434"):
    try:
        urllib.request.urlopen(host + "/api/tags", timeout=2)
        return True, "실행 중 (" + host + ")"
    except Exception:
        return False, "응답 없음 — 모델 관리 시 자동 기동 시도"


def _check_env():
    env = _root() / "llm_environment"
    if (env / "ollama_runtime" / "ollama.exe").exists():
        return True, "설치됨"
    if env.exists():
        return False, "폴더는 있으나 ollama.exe 없음 — 설치 필요"
    return False, "미설치 — [환경 설치] 먼저"


def _free_gb():
    try:
        from launcher.models import model_roles as mr
    except Exception:
        try:
            from launcher import model_roles as mr
        except Exception:
            return None
    try:
        return mr.detect_free_memory_gb()
    except Exception:
        return None


def _check_tor():
    try:
        from launcher import tor_runtime as _tr
    except Exception:
        return False, "Tor 런타임 없음 (검색 익명화 비활성)"
    try:
        if _tr.is_running():
            return True, "실행 중 (9050) — 검색이 Tor 로 익명화됨"
        if _tr.image_exists():
            return False, "이미지 있음·미실행 (챗/검색 시 자동 기동)"
        return False, "이미지 없음 — docker pull dperson/torproxy"
    except Exception:
        return False, "상태 확인 실패"


def collect_status():
    py = (True, "Python " + sys.version.split()[0])
    fg = _free_gb()
    mem = (fg is not None, ("여유 %.1fGB" % fg) if fg else "감지 실패")
    return [("Python",) + py, ("Docker",) + _check_docker(),
            ("Ollama",) + _check_ollama(), ("메모리",) + mem,
            ("Tor",) + _check_tor(), ("설치",) + _check_env()]


# ── 공용 클래스 뷰 ─────────────────────────────────────────────────────
def _class_view(free_gb=None, installed=None):
    try:
        from launcher.models import model_classes as mcls
    except Exception:
        try:
            from launcher import model_classes as mcls
        except Exception:
            return []
    return mcls.build_view(free_gb=free_gb, installed=installed)


def _installed_set():
    try:
        from launcher.models import model_roles as mr
    except Exception:
        try:
            from launcher import model_roles as mr
        except Exception:
            return None
    try:
        return mr.installed_models()
    except Exception:
        return None


def compute_plan(checked, installed, managed):
    """반환 (pull, rm). rm 은 '관리 대상(화면 표시)'이면서 체크 해제된 설치본만 -> 그 외 모델 보호."""
    checked = set(checked)
    installed = set(installed or [])
    managed = set(managed)
    pull = sorted(checked - installed)
    rm = sorted((managed & installed) - checked)
    return pull, rm


# ── 텍스트 폴백 ────────────────────────────────────────────────────────
def _text_menu() -> int:
    try:
        from launcher.models import model_classes as mcls
    except Exception:
        mcls = None
    while True:
        print("\n" + "=" * 60)
        print("  LLM Local Setup - 관리 (텍스트 모드)")
        print("=" * 60)
        for name, ok, msg in collect_status():
            print("  [%s] %-7s: %s" % ("OK" if ok else "--", name, msg))
        if mcls:
            print("-" * 60)
            print(mcls.format_text())
        print("-" * 60)
        print("  [1] 환경 설치/업데이트   [Q] 종료")
        try:
            c = input("선택: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return 0
        if c == "1":
            _spawn_module("installer")
        elif c in ("q", ""):
            return 0


# ── GUI ───────────────────────────────────────────────────────────────
def _run_gui() -> int:
    import tkinter as tk

    root = tk.Tk()
    root.title("LLM Local Setup - 관리")
    root.configure(bg=_BG)
    try:
        root.geometry("720x760")
        root.minsize(600, 560)
    except Exception:
        pass

    state = {"vars": {}, "managed": set(), "busy": False, "installed": None}

    head = tk.Frame(root, bg=_BG)
    head.pack(fill="x", padx=16, pady=(14, 4))
    tk.Label(head, text="LLM Local Setup", bg=_BG, fg="#ffffff",
             font=("Segoe UI", 16, "bold"), anchor="w").pack(fill="x")
    tk.Label(head, text="설치 · 모델 관리 · 진단 — 체크는 설치, 해제는 삭제, [적용]에서만 반영",
             bg=_BG, fg=_DIM, font=("Segoe UI", 9), anchor="w").pack(fill="x")

    status_lbl = tk.Label(root, text="", bg=_BG, fg=_DIM, font=("Segoe UI", 9),
                          anchor="w", justify="left")
    status_lbl.pack(fill="x", padx=16, pady=(2, 6))

    body = tk.Frame(root, bg=_BG)
    body.pack(fill="both", expand=True, padx=16, pady=(0, 6))
    canvas = tk.Canvas(body, bg=_BG, highlightthickness=0)
    sb = tk.Scrollbar(body, orient="vertical", command=canvas.yview)
    inner = tk.Frame(canvas, bg=_BG)
    inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=sb.set)
    canvas.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")

    logf = tk.Frame(root, bg=_BG)
    logf.pack(fill="x", padx=16, pady=(0, 4))
    tk.Label(logf, text="진행 로그", bg=_BG, fg=_DIM, font=("Segoe UI", 8),
             anchor="w").pack(fill="x")
    log = tk.Text(logf, height=7, bg="#141414", fg="#cccccc", insertbackground="#cccccc",
                  relief="flat", font=("Consolas", 9), wrap="word")
    log.pack(fill="x")
    log.tag_configure("ok", foreground=_OK)
    log.tag_configure("err", foreground=_ERR)
    log.tag_configure("warn", foreground=_WARN)
    log.configure(state="disabled")

    def _logln(s, tag=None):
        log.configure(state="normal")
        log.insert("end", s + "\n", tag or ())
        log.see("end")
        log.configure(state="disabled")

    def _rebuild():
        for w in inner.winfo_children():
            w.destroy()
        state["vars"].clear()
        state["managed"].clear()

        installed = _installed_set()
        state["installed"] = installed if installed is not None else set()
        view = _class_view(installed=installed)
        parts = ["%s: %s" % (n, m) for n, _o, m in collect_status()]
        status_lbl.configure(text="   |   ".join(parts))

        if not view:
            tk.Label(inner, text="모델 클래스 정보를 불러오지 못했습니다 (launcher/models 확인).",
                     bg=_BG, fg=_WARN, font=("Segoe UI", 10)).pack(anchor="w", pady=20)
            return

        for c in view:
            sec = tk.Frame(inner, bg=_CARD)
            sec.pack(fill="x", pady=(6, 2))
            tk.Label(sec, text=c["title"], bg=_CARD, fg=_ACC_HI,
                     font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x", padx=12, pady=(8, 0))
            tk.Label(sec, text=c["desc"], bg=_CARD, fg=_DIM,
                     font=("Segoe UI", 8), anchor="w").pack(fill="x", padx=12)
            for r in c["rungs"]:
                state["managed"].add(r["tag"])
                row = tk.Frame(sec, bg=_CARD)
                row.pack(fill="x", padx=12, pady=1)
                if r["tag"] in state["vars"]:
                    var = state["vars"][r["tag"]]
                else:
                    var = tk.BooleanVar(value=bool(r["installed"]))
                    state["vars"][r["tag"]] = var
                cb = tk.Checkbutton(row, variable=var, bg=_CARD, activebackground=_CARD,
                                    selectcolor=_ACC, highlightthickness=0, bd=0,
                                    command=lambda: _update_summary())
                cb.pack(side="left")
                size = ("%.1fGB" % r["size_gb"]) if r["size_gb"] else "  ? "
                badge = "설치됨" if r["installed"] else ("미설치" if r["installed"] is False else "설치?")
                bcol = _OK if r["installed"] else _WARN
                tk.Label(row, text=r["label"], bg=_CARD,
                         fg=(_DIM if r.get("is_primary") else _STAR),
                         font=("Segoe UI", 9, "bold" if r.get("is_primary") else "normal"),
                         width=4, anchor="w").pack(side="left")
                tk.Label(row, text=r["tag"], bg=_CARD, fg="#dddddd",
                         font=("Consolas", 9), anchor="w").pack(side="left")
                tk.Label(row, text="  " + size, bg=_CARD, fg=_DIM,
                         font=("Segoe UI", 8), width=8).pack(side="left")
                tk.Label(row, text="여유>=%.0f" % r["need_gb"], bg=_CARD, fg=_DIM,
                         font=("Segoe UI", 8), width=8).pack(side="left")
                tk.Label(row, text=badge, bg=_CARD, fg=bcol,
                         font=("Segoe UI", 8, "bold"), width=6).pack(side="left")
                if not r.get("is_primary"):
                    tk.Label(row, text="대안", bg=_CARD, fg=_STAR,
                             font=("Segoe UI", 8)).pack(side="left")
                elif r["recommended"]:
                    tk.Label(row, text="★추천", bg=_CARD, fg=_STAR,
                             font=("Segoe UI", 8, "bold")).pack(side="left")
                elif r["actual"]:
                    tk.Label(row, text="실제사용", bg=_CARD, fg=_ACC_HI,
                             font=("Segoe UI", 8)).pack(side="left")
            miss = [r["label"] for r in c["rungs"]
                    if r["installed"] is False and r.get("is_primary")]
            note = ("미설치 %s 건너뜀 → 상위에서 하위로 바로 폴백" % ",".join(miss)) if miss \
                else "메모리 부족 시 1→2→3 순 자동 폴백"
            tk.Label(sec, text="   " + note, bg=_CARD, fg=_DIM,
                     font=("Segoe UI", 8, "italic"), anchor="w").pack(fill="x", padx=12, pady=(0, 8))
        _update_summary()

    def _update_summary():
        # CACHE_v1: 클릭마다 /api/tags 조회하지 않고 _rebuild 시 캐시한 값 사용
        installed = state.get("installed") or set()
        checked = [t for t, v in state["vars"].items() if v.get()]
        pull, rm = compute_plan(checked, installed, state["managed"])
        summary_lbl.configure(
            text="선택: 설치 예정 %d개, 삭제 예정 %d개   (체크=설치 / 해제=삭제)"
                 % (len(pull), len(rm)),
            fg=(_OK if (pull or rm) else _DIM))

    def _worker(pull, rm, done_cb):
        exe = _ollama_exe()
        env = dict(os.environ)
        for tag in rm:
            root.after(0, _logln, "[삭제] " + tag)
            try:
                subprocess.run([exe, "rm", tag], env=env, check=False)
                root.after(0, _logln, "  삭제 완료: " + tag, "ok")
            except Exception as e:
                root.after(0, _logln, "  삭제 실패: %s (%r)" % (tag, e), "err")
        for tag in pull:
            root.after(0, _logln, "[설치] " + tag + " ...")
            try:
                p = subprocess.Popen([exe, "pull", tag], env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, bufsize=1)
                last = ""
                buf = ""
                while True:
                    ch = p.stdout.read(1)
                    if not ch:
                        break
                    if ch in ("\r", "\n"):
                        line = buf.strip()
                        buf = ""
                        if line and line != last:
                            last = line
                            root.after(0, _logln, "  " + line)
                    else:
                        buf += ch
                rc = p.wait()
                if rc == 0:
                    root.after(0, _logln, "  설치 완료: " + tag, "ok")
                else:
                    root.after(0, _logln, "  설치 실패(rc=%d): %s" % (rc, tag), "err")
                    root.after(0, _logln, "  '412 requires a newer version' 이면 Ollama 업데이트: "
                               "https://ollama.com/download", "warn")
            except Exception as e:
                root.after(0, _logln, "  설치 오류: %s (%r)" % (tag, e), "err")
        root.after(0, done_cb)

    def _apply():
        if state["busy"]:
            return
        installed = state.get("installed") or set()  # CACHE_v1
        checked = [t for t, v in state["vars"].items() if v.get()]
        pull, rm = compute_plan(checked, installed, state["managed"])
        if not pull and not rm:
            _logln("변경 없음 (체크 상태 = 설치 상태)")
            return
        state["busy"] = True
        apply_btn.configure(state="disabled", text="적용 중...")
        _logln("── 적용: 설치 %d개, 삭제 %d개 ──" % (len(pull), len(rm)))

        def _done():
            state["busy"] = False
            apply_btn.configure(state="normal", text="적용 (설치/삭제)")
            _logln("완료.", "ok")
            _rebuild()

        threading.Thread(target=_worker, args=(pull, rm, _done), daemon=True).start()

    summary_lbl = tk.Label(root, text="", bg=_BG, fg=_DIM, font=("Segoe UI", 9, "bold"),
                           anchor="w")
    summary_lbl.pack(fill="x", padx=16, pady=(0, 2))

    def _pull_tor():
        # TOR_PULL_v1: Tor 이미지를 창 안에서 원클릭 pull (CLI/재설치 불필요)
        if state["busy"]:
            return
        try:
            from launcher import tor_runtime as _tr
            _img = getattr(_tr, "TOR_IMAGE", "dperson/torproxy")
        except Exception:
            _img = "dperson/torproxy"
        state["busy"] = True
        _logln("[Tor] 이미지 받는 중: " + _img + " (수 분 걸릴 수 있음)")

        def _w():
            # DOCKER_DAEMON_v1: Docker 데몬 확인 + 필요 시 Docker Desktop 자동 시작
            class _L:
                def info(self, m):
                    root.after(0, _logln, "  " + str(m))

                def ok(self, m):
                    root.after(0, _logln, "  " + str(m), "ok")

                def warn(self, m):
                    root.after(0, _logln, "  " + str(m), "warn")

                def error(self, m):
                    root.after(0, _logln, "  " + str(m), "err")

            _alive = False
            try:
                from launcher.services.docker import DockerService
                root.after(0, _logln, "  Docker 데몬 확인/시작 중...")
                _alive = DockerService.ensure_daemon(logger=_L(), timeout=120)
            except Exception:
                _alive = _daemon_alive()
            if not _alive:
                root.after(0, _logln,
                           "  Docker 데몬 미기동 — Docker Desktop 실행 후 다시 시도하세요", "err")

                def _d0():
                    state["busy"] = False
                    _rebuild()
                root.after(0, _d0)
                return
            root.after(0, _logln, "[Tor] 이미지 받는 중: " + _img)
            try:
                pr = subprocess.Popen(["docker", "pull", _img],
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      text=True, bufsize=1)
                last = ""
                buf = ""
                while True:
                    ch = pr.stdout.read(1)
                    if not ch:
                        break
                    if ch in ("\r", "\n"):
                        line = buf.strip()
                        buf = ""
                        if line and line != last:
                            last = line
                            root.after(0, _logln, "  " + line)
                    else:
                        buf += ch
                rc = pr.wait()
                if rc == 0:
                    root.after(0, _logln, "  Tor 이미지 준비 완료 — 챗/검색 시 자동 기동", "ok")
                else:
                    root.after(0, _logln, "  Tor pull 실패(rc=%d) — Docker 실행 확인" % rc, "err")
            except Exception as e:
                root.after(0, _logln, "  오류: %r" % e, "err")

            def _done():
                state["busy"] = False
                _rebuild()
            root.after(0, _done)

        threading.Thread(target=_w, daemon=True).start()

    def _install_env():
        # UNIFY_v1: 환경 설치/업데이트 + 선택 모델 적용을 '창 안에서' 통합 (콘솔/별도 매니저 없음)
        if state["busy"]:
            return
        state["busy"] = True
        apply_btn.configure(state="disabled")
        _logln("-- 환경 설치/업데이트 (창 안에서 진행) --")
        checked = [t for t, v in state["vars"].items() if v.get()]

        def _w():
            # (1) Docker 데몬 확인/자동 시작
            try:
                from launcher.services.docker import DockerService

                class _L:
                    def info(self, m):
                        root.after(0, _logln, "  " + str(m))

                    def ok(self, m):
                        root.after(0, _logln, "  " + str(m), "ok")

                    def warn(self, m):
                        root.after(0, _logln, "  " + str(m), "warn")

                    def error(self, m):
                        root.after(0, _logln, "  " + str(m), "err")
                DockerService.ensure_daemon(logger=_L(), timeout=120)
            except Exception:
                pass
            # (2) 환경 구성 (모델 제외) — 창 안 스트리밍. lang=한국어(2), 이후 프롬프트는 기본
            root.after(0, _logln, "[설치] 환경 구성 중 (모델 제외)...")
            try:
                pr = subprocess.Popen(
                    [sys.executable, "-m", "installer", "--skip-model"],
                    cwd=str(_root()), stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1)
                try:
                    pr.stdin.write("2\n\n\n")
                    pr.stdin.flush()
                    pr.stdin.close()
                except Exception:
                    pass
                buf = ""
                while True:
                    ch = pr.stdout.read(1)
                    if not ch:
                        break
                    if ch in ("\r", "\n"):
                        ln = buf.strip()
                        buf = ""
                        if ln:
                            root.after(0, _logln, "  " + ln)
                    else:
                        buf += ch
                pr.wait()
            except Exception as e:
                root.after(0, _logln, "  환경 설치 오류: %r" % e, "err")
            # (3) 선택된 모델 적용 (설치/삭제) — 기존 _worker 재사용
            try:
                installed = _installed_set() or set()
            except Exception:
                installed = set()
            pull, rm = compute_plan(checked, installed, state["managed"])
            root.after(0, _logln, "[모델] 설치 %d · 삭제 %d 적용" % (len(pull), len(rm)))

            def _done():
                state["busy"] = False
                apply_btn.configure(state="normal")
                _logln("환경 설치/업데이트 완료.", "ok")
                _rebuild()
            _worker(pull, rm, _done)

        threading.Thread(target=_w, daemon=True).start()

    foot = tk.Frame(root, bg=_BG)
    foot.pack(fill="x", padx=16, pady=(2, 14))
    apply_btn = tk.Button(foot, text="적용 (설치/삭제)", command=_apply,
                          bg=_ACC, fg="#ffffff", activebackground=_ACC_HI,
                          relief="flat", font=("Segoe UI", 10, "bold"), padx=14, pady=6)
    apply_btn.pack(side="left")
    tk.Button(foot, text="환경 설치/업데이트", command=_install_env,
              bg=_CARD, fg="#dddddd", activebackground=_LINE, relief="flat",
              font=("Segoe UI", 9), padx=10, pady=6).pack(side="left", padx=(8, 0))
    tk.Button(foot, text="Tor 이미지 받기", command=_pull_tor,
              bg=_CARD, fg="#dddddd", activebackground=_LINE, relief="flat",
              font=("Segoe UI", 9), padx=10, pady=6).pack(side="left", padx=(8, 0))
    tk.Button(foot, text="새로고침", command=_rebuild,
              bg=_CARD, fg="#dddddd", activebackground=_LINE, relief="flat",
              font=("Segoe UI", 9), padx=10, pady=6).pack(side="left", padx=(8, 0))
    tk.Button(foot, text="닫기", command=root.destroy,
              bg=_CARD, fg="#dddddd", activebackground=_LINE, relief="flat",
              font=("Segoe UI", 9), padx=14, pady=6).pack(side="right")

    _rebuild()
    root.mainloop()
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        a = argv[0].lower()
        if a in ("install", "setup"):
            _spawn_module("installer"); return 0
        if a in ("diagnose", "diag", "--diagnose"):
            for name, ok, msg in collect_status():
                print("  [%s] %-7s: %s" % ("OK" if ok else "--", name, msg))
            try:
                from launcher.models import model_classes as mcls
                print(mcls.format_text())
            except Exception:
                pass
            return 0
    try:
        return _run_gui()
    except Exception as e:
        print("[INFO] GUI 를 열 수 없어 텍스트 모드로 전환 (%r)" % e)
        return _text_menu()


if __name__ == "__main__":
    sys.exit(main())
