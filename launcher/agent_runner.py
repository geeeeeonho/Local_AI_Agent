"""agent_runner — GUI 통합 에이전트 백엔드 (subprocess.PIPE 기반).

지시사항 [1단계] + [2단계] 구현:
  - subprocess.PIPE 로 에이전트 stdout/stderr/stdin 캡처
  - 백그라운드 reader 스레드 → thread-safe Queue → GUI 가 폴링
  - GUI 입력 → Queue → writer 스레드 → 에이전트 stdin
  - --no_vision 강제 (system_message + env var 3중)
  - ErrorGuard: 화면 캡처 시도 패턴 감지 → 경고

설계 원칙
─────────
- pure stdlib (subprocess, threading, queue)
- GUI 스레드 블록 금지 — 모든 I/O 는 백그라운드
- 에이전트 종료 시 reader/writer 스레드 자연 종료
- 외부에서 stop() 호출 시 graceful → forceful 단계적 종료
"""
from __future__ import annotations


# >>> LLM_SESSION_LOG_PATH_FIX_v1 (auto-inserted by FIX_LOG_PATHS.py v7.8; do not edit between markers)
# LLM_REALTIME_READER_FIX_v1 (FIX_AGENT_REALTIME.py v7.9)

# >>> LLM_AGENT_REPL_FIX_v1 (FIX_AGENT_REPL.py v8.0)
_AGENT_REPL_SRC_B64 = "IyEvdXNyL2Jpbi9lbnYgcHl0aG9uMwojIC0qLSBjb2Rpbmc6IHV0Zi04IC0qLQojIGFnZW50X3JlcGwucHkgKHY4LjUpIC0gT3BlbiBJbnRlcnByZXRlciDrpbwgc3RkaW4g66Oo7ZSEICsg7YyM7J207I2sIEFQSSDroZwg6rWs64+ZIChUVFkg67aI7ZWE7JqUKS4KIyB2OC4xOiDrqqjrjbjrqoUg7J207KSRIG9sbGFtYS8g7KCR65GQ7Ja0IOygnOqxsC4KIyB2OC4yOiDsnZHri7Ug7LKt7YGsIOy2lOy2nCDqsJXtmZQgKyBpbnRlcnByZXRlci5tZXNzYWdlcyDtj7TrsLEgKyDruYgg7J2R64u1IOyLnCDssq3tgaztmJXtg5wg7KeE64uoLgojIHY4LjM6IOuqqOuNuOydhCBvbGxhbWFfY2hhdC8g66GcIOygleq3nO2ZlCAoL2FwaS9jaGF0LCDthZztlIzrpr8g7KCB7JqpIOKAlCDruYjsnZHri7Ug7ZqM7ZS8KS4KIyB2OC41OiBtYXhfdG9rZW5zIO2VmO2VnCAyMDQ4IOKAlCDsvZTrk5wg7IOd7ISxIOykkeqwhCDsnpjrprwoU3ludGF4RXJyb3IpIOuwqeyngC4KaW1wb3J0IHN5cwppbXBvcnQgb3MKaW1wb3J0IGFyZ3BhcnNlCmltcG9ydCB0cmFjZWJhY2sKCgpkZWYgX3NldChvYmosIGRvdHRlZCwgdmFsKToKICAgIGN1ciA9IG9iagogICAgcGFydHMgPSBkb3R0ZWQuc3BsaXQoIi4iKQogICAgZm9yIHAgaW4gcGFydHNbOi0xXToKICAgICAgICBpZiBub3QgaGFzYXR0cihjdXIsIHApOgogICAgICAgICAgICByZXR1cm4gRmFsc2UKICAgICAgICBjdXIgPSBnZXRhdHRyKGN1ciwgcCkKICAgIGlmIGhhc2F0dHIoY3VyLCBwYXJ0c1stMV0pOgogICAgICAgIHRyeToKICAgICAgICAgICAgc2V0YXR0cihjdXIsIHBhcnRzWy0xXSwgdmFsKQogICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHJldHVybiBGYWxzZQogICAgcmV0dXJuIEZhbHNlCgoKZGVmIF9idWlsZChhcmdzKToKICAgIGludGVycCA9IE5vbmUKICAgIHRyeToKICAgICAgICBmcm9tIGludGVycHJldGVyIGltcG9ydCBpbnRlcnByZXRlciBhcyBpbnRlcnAKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgdHJ5OgogICAgICAgICAgICBmcm9tIGludGVycHJldGVyIGltcG9ydCBPcGVuSW50ZXJwcmV0ZXIKICAgICAgICAgICAgaW50ZXJwID0gT3BlbkludGVycHJldGVyKCkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBmcm9tIGludGVycHJldGVyLmNvcmUuY29yZSBpbXBvcnQgT3BlbkludGVycHJldGVyCiAgICAgICAgICAgIGludGVycCA9IE9wZW5JbnRlcnByZXRlcigpCiAgICAjIHY4LjM6IGluc3RydWN0IOuqqOuNuOydgCAvYXBpL2NoYXQob2xsYW1hX2NoYXQpIOqwgCDslYjsoJXsoIEg4oCUIC9hcGkvZ2VuZXJhdGUg67mI7J2R64u1IO2ajO2UvAogICAgX0tOT1dOID0gKCJvbGxhbWFfY2hhdCIsICJvcGVuYWkiLCAiYW50aHJvcGljIiwgImF6dXJlIiwKICAgICAgICAgICAgICAiZ2VtaW5pIiwgImdyb3EiLCAibWlzdHJhbCIsICJjb2hlcmUiLCAidG9nZXRoZXJfYWkiKQogICAgX20gPSBhcmdzLm1vZGVsCiAgICBfcHJvdiA9IF9tLnNwbGl0KCIvIiwgMSlbMF0KICAgIGlmIF9wcm92ID09ICJvbGxhbWEiOgogICAgICAgIG1vZGVsID0gIm9sbGFtYV9jaGF0LyIgKyBfbS5zcGxpdCgiLyIsIDEpWzFdCiAgICBlbGlmIF9wcm92IGluIF9LTk9XTjoKICAgICAgICBtb2RlbCA9IF9tCiAgICBlbHNlOgogICAgICAgIG1vZGVsID0gIm9sbGFtYV9jaGF0LyIgKyBfbQogICAgIyB2OC41OiBtYXhfdG9rZW5zIO2VmO2VnCAyMDQ4IOuztOyepSDigJQgNTEyIOuKlCDsvZTrk5wg7IOd7ISxIOykkeqwhOyXkCDsnpjroKQgU3ludGF4RXJyb3Ig7Jyg67CcCiAgICBfZWZmX21heCA9IGFyZ3MubWF4X3Rva2VucyBpZiAoYXJncy5tYXhfdG9rZW5zIGFuZCBhcmdzLm1heF90b2tlbnMgPj0gMjA0OCkgZWxzZSAyMDQ4CiAgICBmb3IgcGF0aCwgdmFsIGluICgKICAgICAgICAoImxsbS5tb2RlbCIsIG1vZGVsKSwgKCJtb2RlbCIsIG1vZGVsKSwKICAgICAgICAoImxsbS5hcGlfYmFzZSIsIGFyZ3MuYXBpX2Jhc2UpLCAoImFwaV9iYXNlIiwgYXJncy5hcGlfYmFzZSksCiAgICAgICAgKCJsbG0uY29udGV4dF93aW5kb3ciLCBhcmdzLmNvbnRleHRfd2luZG93KSwgKCJjb250ZXh0X3dpbmRvdyIsIGFyZ3MuY29udGV4dF93aW5kb3cpLAogICAgICAgICgibGxtLm1heF90b2tlbnMiLCBfZWZmX21heCksICgibWF4X3Rva2VucyIsIF9lZmZfbWF4KSwKICAgICAgICAoImxsbS5zdXBwb3J0c19mdW5jdGlvbnMiLCBGYWxzZSksCiAgICAgICAgKCJzeXN0ZW1fbWVzc2FnZSIsIGFyZ3Muc3lzdGVtX21lc3NhZ2UpLAogICAgICAgICgiYXV0b19ydW4iLCBib29sKGFyZ3MuYXV0b19ydW4pKSwKICAgICAgICAoIm9mZmxpbmUiLCBUcnVlKSwgKCJ2ZXJib3NlIiwgRmFsc2UpLAogICAgICAgICgic2FmZV9tb2RlIiwgIm9mZiIpLAogICAgKToKICAgICAgICBfc2V0KGludGVycCwgcGF0aCwgdmFsKQogICAgcmV0dXJuIGludGVycAoKCmRlZiBfZXh0cmFjdChjaHVuayk6CiAgICAjIOuLpOyWke2VnCBPSSDrsoTsoIQg7LKt7YGsIO2PrOunt+yXkOyEnCDtkZzsi5wg7YWN7Iqk7Yq4IOy2lOy2nAogICAgaWYgaXNpbnN0YW5jZShjaHVuaywgc3RyKToKICAgICAgICByZXR1cm4gY2h1bmsKICAgIGlmIGlzaW5zdGFuY2UoY2h1bmssIGRpY3QpOgogICAgICAgIGMgPSBjaHVuay5nZXQoImNvbnRlbnQiKQogICAgICAgIGlmIGlzaW5zdGFuY2UoYywgc3RyKToKICAgICAgICAgICAgcmV0dXJuIGMKICAgICAgICBpZiBpc2luc3RhbmNlKGMsIGRpY3QpOgogICAgICAgICAgICBmb3IgayBpbiAoImNvbnRlbnQiLCAidGV4dCIsICJtZXNzYWdlIik6CiAgICAgICAgICAgICAgICB2ID0gYy5nZXQoaykKICAgICAgICAgICAgICAgIGlmIGlzaW5zdGFuY2Uodiwgc3RyKToKICAgICAgICAgICAgICAgICAgICByZXR1cm4gdgogICAgICAgIGZvciBrIGluICgidGV4dCIsICJtZXNzYWdlIiwgImRlbHRhIiwgInJlc3BvbnNlIik6CiAgICAgICAgICAgIHYgPSBjaHVuay5nZXQoaykKICAgICAgICAgICAgaWYgaXNpbnN0YW5jZSh2LCBzdHIpOgogICAgICAgICAgICAgICAgcmV0dXJuIHYKICAgIHJldHVybiAiIgoKCmRlZiBfc2hhcGUoY2h1bmspOgogICAgaWYgaXNpbnN0YW5jZShjaHVuaywgZGljdCk6CiAgICAgICAga2V5cyA9ICIsIi5qb2luKHNvcnRlZChzdHIoaykgZm9yIGsgaW4gY2h1bmsua2V5cygpKSkKICAgICAgICByZXR1cm4gImRpY3QodHlwZT0iICsgc3RyKGNodW5rLmdldCgidHlwZSIpKSArICIsZm10PSIgKyBzdHIoY2h1bmsuZ2V0KCJmb3JtYXQiKSkgKyAiLGtleXM9IiArIGtleXMgKyAiKSIKICAgIHJldHVybiB0eXBlKGNodW5rKS5fX25hbWVfXwoKCmRlZiBfZnJvbV9tZXNzYWdlcyhpbnRlcnAsIGJlZm9yZSk6CiAgICBtc2dzID0gZ2V0YXR0cihpbnRlcnAsICJtZXNzYWdlcyIsIE5vbmUpCiAgICBpZiBub3QgaXNpbnN0YW5jZShtc2dzLCBsaXN0KToKICAgICAgICByZXR1cm4gIiIKICAgIG91dCA9IFtdCiAgICBmb3IgbSBpbiBtc2dzW2JlZm9yZTpdOgogICAgICAgIGlmIG5vdCBpc2luc3RhbmNlKG0sIGRpY3QpOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGlmIG0uZ2V0KCJyb2xlIikgaW4gKCJhc3Npc3RhbnQiLCAiY29tcHV0ZXIiKToKICAgICAgICAgICAgYyA9IG0uZ2V0KCJjb250ZW50IikKICAgICAgICAgICAgaWYgaXNpbnN0YW5jZShjLCBzdHIpIGFuZCBjLnN0cmlwKCk6CiAgICAgICAgICAgICAgICB0YWcgPSAiIgogICAgICAgICAgICAgICAgaWYgbS5nZXQoInR5cGUiKSA9PSAiY29kZSI6CiAgICAgICAgICAgICAgICAgICAgdGFnID0gIltjb2RlXSAiCiAgICAgICAgICAgICAgICBlbGlmIG0uZ2V0KCJ0eXBlIikgPT0gImNvbnNvbGUiOgogICAgICAgICAgICAgICAgICAgIHRhZyA9ICJbb3V0cHV0XSAiCiAgICAgICAgICAgICAgICBvdXQuYXBwZW5kKHRhZyArIGMpCiAgICByZXR1cm4gIlxuIi5qb2luKG91dCkKCgpkZWYgbWFpbigpOgogICAgYXAgPSBhcmdwYXJzZS5Bcmd1bWVudFBhcnNlcigpCiAgICBhcC5hZGRfYXJndW1lbnQoIi0tbW9kZWwiLCByZXF1aXJlZD1UcnVlKQogICAgYXAuYWRkX2FyZ3VtZW50KCItLWFwaV9iYXNlIiwgcmVxdWlyZWQ9VHJ1ZSkKICAgIGFwLmFkZF9hcmd1bWVudCgiLS1jb250ZXh0X3dpbmRvdyIsIHR5cGU9aW50LCBkZWZhdWx0PTQwOTYpCiAgICBhcC5hZGRfYXJndW1lbnQoIi0tbWF4X3Rva2VucyIsIHR5cGU9aW50LCBkZWZhdWx0PTUxMikKICAgIGFwLmFkZF9hcmd1bWVudCgiLS1zeXN0ZW1fbWVzc2FnZSIsIGRlZmF1bHQ9IiIpCiAgICBhcC5hZGRfYXJndW1lbnQoIi0tYXV0b19ydW4iLCBhY3Rpb249InN0b3JlX3RydWUiKQogICAgYXJncywgX3Vua25vd24gPSBhcC5wYXJzZV9rbm93bl9hcmdzKCkKCiAgICB0cnk6CiAgICAgICAgaW50ZXJwID0gX2J1aWxkKGFyZ3MpCiAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgc3lzLnN0ZG91dC53cml0ZSgiW0ZBVEFMXSBpbnRlcnByZXRlciDstIjquLDtmZQg7Iuk7YyoOiAiICsgcmVwcihlKSArICJcbiIpCiAgICAgICAgdHJhY2ViYWNrLnByaW50X2V4YyhmaWxlPXN5cy5zdGRvdXQpCiAgICAgICAgc3lzLnN0ZG91dC5mbHVzaCgpCiAgICAgICAgcmV0dXJuIDEKCiAgICBzeXMuc3Rkb3V0LndyaXRlKCJb7JeQ7J207KCE7Yq4IOykgOu5hOuQqF0g66mU7Iuc7KeA66W8IOyeheugpe2VmOyEuOyalC5cbiIpCiAgICBzeXMuc3Rkb3V0LndyaXRlKCI+ICIpCiAgICBzeXMuc3Rkb3V0LmZsdXNoKCkKCiAgICBmb3IgbGluZSBpbiBzeXMuc3RkaW46CiAgICAgICAgbXNnID0gbGluZS5zdHJpcCgpCiAgICAgICAgaWYgbm90IG1zZzoKICAgICAgICAgICAgc3lzLnN0ZG91dC53cml0ZSgiPiAiKTsgc3lzLnN0ZG91dC5mbHVzaCgpOyBjb250aW51ZQogICAgICAgIGlmIG1zZy5sb3dlcigpIGluICgiZXhpdCIsICJxdWl0IiwgIi9leGl0IiwgIi9xdWl0Iik6CiAgICAgICAgICAgIGJyZWFrCiAgICAgICAgdHJ5OgogICAgICAgICAgICBiZWZvcmUgPSBsZW4oZ2V0YXR0cihpbnRlcnAsICJtZXNzYWdlcyIsIFtdKSBvciBbXSkKICAgICAgICAgICAgZ290ID0gRmFsc2UKICAgICAgICAgICAgc2VlbiA9IFtdCiAgICAgICAgICAgIHJlc3VsdCA9IGludGVycC5jaGF0KG1zZywgZGlzcGxheT1GYWxzZSwgc3RyZWFtPVRydWUpCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGl0ID0gaXRlcihyZXN1bHQpCiAgICAgICAgICAgIGV4Y2VwdCBUeXBlRXJyb3I6CiAgICAgICAgICAgICAgICBpdCA9IGl0ZXIoW3Jlc3VsdF0pCiAgICAgICAgICAgIGZvciBjaHVuayBpbiBpdDoKICAgICAgICAgICAgICAgIHQgPSBfZXh0cmFjdChjaHVuaykKICAgICAgICAgICAgICAgIGlmIHQ6CiAgICAgICAgICAgICAgICAgICAgc3lzLnN0ZG91dC53cml0ZSh0KTsgc3lzLnN0ZG91dC5mbHVzaCgpOyBnb3QgPSBUcnVlCiAgICAgICAgICAgICAgICBlbGlmIGxlbihzZWVuKSA8IDEwOgogICAgICAgICAgICAgICAgICAgIHNlZW4uYXBwZW5kKF9zaGFwZShjaHVuaykpCiAgICAgICAgICAgIGlmIG5vdCBnb3Q6CiAgICAgICAgICAgICAgICByZWNvdmVyZWQgPSBfZnJvbV9tZXNzYWdlcyhpbnRlcnAsIGJlZm9yZSkKICAgICAgICAgICAgICAgIGlmIHJlY292ZXJlZDoKICAgICAgICAgICAgICAgICAgICBzeXMuc3Rkb3V0LndyaXRlKHJlY292ZXJlZCk7IGdvdCA9IFRydWUKICAgICAgICAgICAgaWYgbm90IGdvdDoKICAgICAgICAgICAgICAgIGRpYWcgPSAiIHwgIi5qb2luKHNlZW4pIGlmIHNlZW4gZWxzZSAi7LKt7YGsIOyXhuydjCjrqqjrjbjsnbQg67mIIOydkeuLtSkiCiAgICAgICAgICAgICAgICBzeXMuc3Rkb3V0LndyaXRlKCJb67mIIOydkeuLtV0g7KeE64uoOiAiICsgZGlhZykKICAgICAgICAgICAgc3lzLnN0ZG91dC53cml0ZSgiXG4iKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc3lzLnN0ZG91dC53cml0ZSgiXG5bRVJST1JdIOydkeuLtSDsg53shLEg7Iuk7YyoOiAiICsgcmVwcihlKSArICJcbiIpCiAgICAgICAgICAgIHRyYWNlYmFjay5wcmludF9leGMoZmlsZT1zeXMuc3Rkb3V0KQogICAgICAgIHN5cy5zdGRvdXQud3JpdGUoIj4gIik7IHN5cy5zdGRvdXQuZmx1c2goKQogICAgcmV0dXJuIDAKCgppZiBfX25hbWVfXyA9PSAiX19tYWluX18iOgogICAgc3lzLmV4aXQobWFpbigpKQo="
_AGENT_REPL_BOOTSTRAP = "import os,base64;exec(base64.b64decode(os.environ['AGENT_REPL_SRC']).decode('utf-8'))"
# <<< LLM_AGENT_REPL_FIX_v1

def _llm_session_log_dir():
    """에이전트 로그를 llm_environment/logs 아래로 강제 (cwd 오염 방지)."""
    import os
    from pathlib import Path
    ov = os.environ.get("LLM_ENV_DIR")
    if ov:
        b = Path(ov)
        d = b / "logs" if b.name != "logs" else b
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return d
    try:
        here = Path(__file__).resolve()
        cands = [here.parent] + list(here.parents)
    except Exception:
        cands = [Path.cwd()]
    for c in cands:
        try:
            if (c / "llm_environment").is_dir() or (c / "RUN.bat").exists() or (c / "INSTALL.bat").exists():
                d = c / "llm_environment" / "logs"
                d.mkdir(parents=True, exist_ok=True)
                return d
        except Exception:
            continue
    d = Path.cwd() / "llm_environment" / "logs"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d
# <<< LLM_SESSION_LOG_PATH_FIX_v1
import os
import queue
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional


# ─────────────────────────────────────────────
#  메시지 종류 (큐에 흐르는 이벤트)
# ─────────────────────────────────────────────
LEVEL_STDOUT = "stdout"
LEVEL_STDERR = "stderr"
LEVEL_INFO = "info"
LEVEL_WARN = "warn"
LEVEL_ERROR = "error"
LEVEL_TERMINATED = "terminated"


@dataclass
class AgentMessage:
    """에이전트 → GUI 로 흘러가는 단일 이벤트."""
    level: str  # LEVEL_*
    text: str
    timestamp: float = field(default_factory=time.time)


# ─────────────────────────────────────────────
#  ErrorGuard — 위험 패턴 사전 차단
# ─────────────────────────────────────────────
_VISION_PATTERNS = [
    re.compile(r"\bscreenshot\b", re.IGNORECASE),
    re.compile(r"\bscreen[\s_-]*capture\b", re.IGNORECASE),
    re.compile(r"\bpyautogui\b", re.IGNORECASE),
    re.compile(r"\bpynput\b", re.IGNORECASE),
    re.compile(r"PIL\.ImageGrab", re.IGNORECASE),
    re.compile(r"\bImageGrab\b", re.IGNORECASE),
    re.compile(r"\b(?:from\s+mss\s+import|import\s+mss|mss\.mss)\b", re.IGNORECASE),
    re.compile(r"computer\.(display|mouse|keyboard|screen)", re.IGNORECASE),
    re.compile(r"\bget_monitors\b", re.IGNORECASE),
    re.compile(r"\bos_mode\b", re.IGNORECASE),
]


def looks_like_vision_attempt(line: str) -> bool:
    """에이전트가 화면 캡처/GUI 자동화를 시도하는 패턴인지 감지.

    Returns True if the line matches any known vision/GUI automation pattern.
    """
    for pat in _VISION_PATTERNS:
        if pat.search(line):
            return True
    return False


# ─────────────────────────────────────────────
#  UnifiedAgent — 메인 객체
# ─────────────────────────────────────────────
class UnifiedAgent:
    """subprocess.PIPE 기반 에이전트 실행기.

    사용:
        agent = UnifiedAgent()
        agent.start(cmd=["docker", "run", ...], env={...})
        # 폴링 (GUI 메인 루프에서 100ms 마다)
        for msg in agent.drain_messages():
            chat_panel.append(msg.level, msg.text)
        # 사용자 입력
        agent.send_input("hello")
        # 종료
        agent.stop(timeout=3.0)

    Thread-safety: 모든 public 메서드는 어느 스레드에서나 호출 가능.
    """

    def __init__(self, max_queue: int = 10000):
        self._proc: Optional[subprocess.Popen] = None
        self._cmd: List[str] = []
        self._messages: queue.Queue = queue.Queue(maxsize=max_queue)
        self._input_queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._readers: List[threading.Thread] = []
        self._writer: Optional[threading.Thread] = None
        self._error_guard_enabled = True
        # v6_lifelog: 컨테이너명과 세션 로그 파일 핸들
        self._container_name_v6 = None
        self._session_log_v6 = None
        # v4_lifecycle: 컨테이너명 (cmd 에서 --name 파싱하여 채움)
        self._container_name: Optional[str] = None
        # v4_lifecycle: 디버그 로그 파일 핸들 (선택적)
        self._debug_log_fh = None
        # v4_lifecycle: 첫 stdout 수신 시각 (TTFT 측정용)
        self._first_output_at: Optional[float] = None

    # ── lifecycle ──
    def is_running(self) -> bool:
        """에이전트 프로세스가 살아있는지."""
        with self._lock:
            if self._proc is None:
                return False
            return self._proc.poll() is None

    def start(
        self,
        cmd: List[str],
        env: Optional[dict] = None,
        cwd: Optional[Path] = None,
    ) -> bool:
        """에이전트 시작.

        Args:
            cmd: 실행할 명령 (예: ["docker", "run", "-i", ...])
                 IMPORTANT: docker run 의 경우 -t 빼고 -i 만 줘야 PIPE 가 동작.
            env: 환경변수 (None 이면 부모 env 상속)
            cwd: 작업 디렉터리

        Returns:
            True if started, False if already running.
        """
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return False
            self._cmd = list(cmd)
            self._stopped.clear()

            # v4_lifecycle: cmd 에서 --name <X> 자동 추출
            self._container_name = None
            try:
                _idx = self._cmd.index('--name')
                if _idx + 1 < len(self._cmd):
                    self._container_name = self._cmd[_idx + 1]
            except ValueError:
                pass

            # v4_lifecycle: 디버그 로그 파일 오픈 (best-effort)
            try:
                from . import config as _cfg
                _log_dir = Path(_cfg.ENV_PATH) / 'logs' if hasattr(_cfg, 'ENV_PATH') else Path('.')
                _log_dir.mkdir(parents=True, exist_ok=True)
                _ts = time.strftime('%Y%m%d_%H%M%S')
                _name_part = self._container_name or 'agent'
                self._debug_log_fh = open(
                    str(_llm_session_log_dir() / (_log_dir / ('agent_runner_' + _name_part + '_' + _ts + '.log'))),
                    'w', encoding='utf-8'
                )
                self._debug_log_fh.write(
                    "[start] " + time.strftime("%H:%M:%S")
                    + " container=" + str(self._container_name) + "\n"
                )
                self._debug_log_fh.write(
                    "[cmd] " + " ".join(self._cmd[:8]) + " ...\n"
                )
                self._debug_log_fh.flush()
            except Exception:
                self._debug_log_fh = None

            # Windows 에서 CREATE_NO_WINDOW — 콘솔창 안 뜨도록
            popen_kwargs = {
                "stdin": subprocess.PIPE,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "bufsize": 1,  # line-buffered
                "universal_newlines": True,
                "encoding": "utf-8",
                "errors": "replace",
            }
            if env is not None:
                popen_kwargs["env"] = env
            if cwd is not None:
                popen_kwargs["cwd"] = str(cwd)
            if os.name == "nt":
                popen_kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

            try:
                self._proc = subprocess.Popen(cmd, **popen_kwargs)
            except FileNotFoundError as e:
                self._emit(LEVEL_ERROR, f"명령을 찾을 수 없습니다: {e}")
                self._proc = None
                return False
            except Exception as e:
                self._emit(LEVEL_ERROR, f"에이전트 시작 실패: {type(e).__name__}: {e}")
                self._proc = None
                return False

            # ── 백그라운드 스레드 기동 ──
            self._readers = [
                threading.Thread(
                    target=self._reader_loop,
                    args=(self._proc.stdout, LEVEL_STDOUT),
                    daemon=True, name="agent-stdout",
                ),
                threading.Thread(
                    target=self._reader_loop,
                    args=(self._proc.stderr, LEVEL_STDERR),
                    daemon=True, name="agent-stderr",
                ),
            ]
            for t in self._readers:
                t.start()

            self._writer = threading.Thread(
                target=self._writer_loop,
                daemon=True, name="agent-stdin",
            )
            self._writer.start()

            # 종료 감지 스레드
            threading.Thread(
                target=self._wait_loop,
                daemon=True, name="agent-wait",
            ).start()

            # v6_lifelog: 세션 로그 + 컨테이너명 추출 + cleanup 등록
            self._container_name_v6 = None
            try:
                _idx = self._cmd.index("--name")
                if _idx + 1 < len(self._cmd):
                    self._container_name_v6 = self._cmd[_idx + 1]
            except (ValueError, AttributeError):
                pass
            self._session_log_v6 = None
            try:
                from . import lifelog as _ll
                _name = self._container_name_v6 or ("agent_pid" + str(self._proc.pid))
                self._session_log_v6 = _ll.open_session_log(_name)
                _ll.log("INFO", "에이전트 시작 (PID=" + str(self._proc.pid)
                       + ", container=" + str(self._container_name_v6) + ")")
                _ll.log_session(self._session_log_v6, "INFO",
                                "cmd=" + " ".join(self._cmd[:10]) + " ...")
                # 자기 자신을 cleanup 에 등록 — 종료 hook 에서 자동 정리
                _self_ref = self
                _ll.register_cleanup(lambda: _self_ref.stop(timeout=2.0))
            except Exception as _le:
                pass
            self._emit(LEVEL_INFO, f"에이전트 시작 (PID={self._proc.pid})")
            if self._container_name:
                self._emit(LEVEL_INFO, f"컨테이너: {self._container_name}")
            # v4_lifecycle: 활성 에이전트 registry 등록
            try:
                from . import agent_lifecycle as _lc
                _lc.register(self)
            except Exception as _e:
                self._emit(LEVEL_WARN, f"lifecycle 등록 실패: {_e}")
            return True

    def stop(self, timeout: float = 3.0) -> None:
        """에이전트 종료 — graceful 후 forceful.

        Args:
            timeout: graceful 종료 대기 시간 (초)
        """
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                self._stopped.set()
                return

            # 1) stdin 닫기 — exit 신호
            try:
                if proc.stdin and not proc.stdin.closed:
                    proc.stdin.close()
            except Exception:
                pass

            # 2) terminate
            try:
                proc.terminate()
            except Exception:
                pass

        # 3) 대기
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass

        # v4_lifecycle: docker 컨테이너 강제 종료 (CLI 래퍼만 죽이는 것 방지)
        if self._container_name:
            try:
                _no_window = {}
                if os.name == "nt":
                    _no_window["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
                subprocess.run(
                    ["docker", "stop", "-t", "2", self._container_name],
                    capture_output=True, timeout=5, **_no_window
                )
                subprocess.run(
                    ["docker", "rm", "-f", self._container_name],
                    capture_output=True, timeout=5, **_no_window
                )
                self._emit(LEVEL_INFO, f"컨테이너 정리: {self._container_name}")
            except Exception as _e:
                self._emit(LEVEL_WARN, f"컨테이너 정리 실패: {_e}")

        # v4_lifecycle: 디버그 로그 종료
        if self._debug_log_fh is not None:
            try:
                self._debug_log_fh.write(
                    "[stop] " + time.strftime("%H:%M:%S")
                    + " container=" + str(self._container_name) + "\n"
                )
                self._debug_log_fh.close()
            except Exception:
                pass
            self._debug_log_fh = None

        # v4_lifecycle: lifecycle registry 에서 제거
        try:
            from . import agent_lifecycle as _lc
            _lc.unregister(self)
        except Exception:
            pass

        # v6_lifelog: 컨테이너 강제 격멸 (docker stop -> docker kill fallback)
        _container = getattr(self, "_container_name_v6", None)
        if _container:
            try:
                from . import lifelog as _ll
                _ll.force_kill_container(_container, timeout=2)
            except Exception as _le:
                self._emit(LEVEL_WARN, "force_kill 예외: " + str(_le))

        # v6_lifelog: 세션 로그 close (마지막 flush 보장)
        _fh = getattr(self, "_session_log_v6", None)
        if _fh is not None:
            try:
                from . import lifelog as _ll
                _ll.log_session(_fh, "INFO", "===== 에이전트 종료 =====")
                _fh.close()
            except Exception:
                pass
            self._session_log_v6 = None

        self._stopped.set()
        self._emit(LEVEL_WARN, "에이전트 종료됨")

    def send_input(self, line: str) -> bool:
        """사용자 입력을 에이전트 stdin 에 보냄.

        Returns False if agent isn't running.
        """
        if not self.is_running():
            return False
        if not line.endswith("\n"):
            line = line + "\n"
        try:
            self._input_queue.put_nowait(line)
            return True
        except queue.Full:
            self._emit(LEVEL_WARN, "입력 큐 가득참 — 메시지 버려짐")
            return False

    def drain_messages(self, max_n: int = 200) -> List[AgentMessage]:
        """큐에서 메시지를 비파괴적으로 비움. GUI 가 폴링으로 호출.

        Returns up to `max_n` messages, oldest first. Empty list if no messages.
        """
        out: List[AgentMessage] = []
        for _ in range(max_n):
            try:
                msg = self._messages.get_nowait()
            except queue.Empty:
                break
            out.append(msg)
        return out

    # ── 내부 ──
    def _emit(self, level: str, text: str) -> None:
        """메시지를 큐에 넣음 — 가득 차면 가장 오래된 것 버림."""
        msg = AgentMessage(level=level, text=text)
        try:
            self._messages.put_nowait(msg)
        except queue.Full:
            # 가장 오래된 항목 하나 버리고 재시도
            try:
                self._messages.get_nowait()
            except queue.Empty:
                pass
            try:
                self._messages.put_nowait(msg)
            except queue.Full:
                pass  # 어쩔 수 없음

    def _read_realtime(self, stream):
        """v7.9: 문자 단위 실시간 읽기. readline 블록 회피.

        - 완성된 줄은 \\n 기준 즉시 방출
        - Open Interpreter 프롬프트('> ', '>>> ')는 줄바꿈 없이도 즉시 방출
        호출측(_reader_loop)의 줄 처리 로직을 그대로 재사용한다.
        """
        _PROMPTS = ("> ", ">>> ")
        _buf = []
        while True:
            try:
                ch = stream.read(1)
            except (ValueError, OSError):
                break
            if ch == "":
                break
            if ch == "\n":
                yield "".join(_buf) + "\n"
                _buf = []
                continue
            _buf.append(ch)
            if "".join(_buf) in _PROMPTS:
                yield "".join(_buf)
                _buf = []
        if _buf:
            yield "".join(_buf)

    def _reader_loop(self, stream, level: str) -> None:
        """stdout/stderr 한 줄씩 읽어 큐에 push.

        ErrorGuard: vision 시도 패턴 감지 시 WARN 추가.
        """
        try:
            for raw_line in self._read_realtime(stream):
                line = raw_line.rstrip("\n\r")
                if not line:
                    # 빈 줄도 표시 (코드 블록 보존)
                    self._emit(level, "")
                    continue

                # v4_lifecycle: 디버그 로그 + 첫 토큰 시각 측정
                if self._debug_log_fh is not None:
                    try:
                        self._debug_log_fh.write(
                            "[" + level + "] " + line + "\n"
                        )
                        self._debug_log_fh.flush()
                    except Exception:
                        pass
                if self._first_output_at is None and level == LEVEL_STDOUT:
                    self._first_output_at = time.time()
                # v6_lifelog: 모든 stdout/stderr 줄을 세션 로그에 기록
                try:
                    _fh = getattr(self, "_session_log_v6", None)
                    if _fh is not None:
                        from . import lifelog as _ll
                        _ll.log_session(_fh, level.upper(), line)
                except Exception:
                    pass
                # ErrorGuard
                if self._error_guard_enabled and looks_like_vision_attempt(line):
                    self._emit(
                        LEVEL_WARN,
                        f"⚠ 화면 캡처/GUI 자동화 패턴 감지됨 — 무시됨: {line[:80]}",
                    )

                self._emit(level, line)
        except (ValueError, OSError):
            # 스트림이 닫힌 정상 종료
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _writer_loop(self) -> None:
        """입력 큐에서 한 줄씩 꺼내 에이전트 stdin 에 씀."""
        while not self._stopped.is_set():
            try:
                line = self._input_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            with self._lock:
                proc = self._proc
                if proc is None or proc.stdin is None or proc.stdin.closed:
                    break
                try:
                    proc.stdin.write(line)
                    proc.stdin.flush()
                    _dbg = getattr(self, "_debug_log_fh", None)
                    if _dbg is not None:
                        try:
                            _dbg.write("[stdin] " + line.rstrip("\n\r") + "\n")
                            _dbg.flush()
                        except Exception:
                            pass
                except (BrokenPipeError, OSError, ValueError):
                    break

    def _wait_loop(self) -> None:
        """에이전트 종료를 감지해 TERMINATED 메시지 emit."""
        proc = self._proc
        if proc is None:
            return
        try:
            rc = proc.wait()
        except Exception:
            rc = -1
        self._stopped.set()
        self._emit(LEVEL_TERMINATED, f"프로세스 종료 (rc={rc})")


# ─────────────────────────────────────────────
#  명령 조립 헬퍼 — agent_chat 액션에서 사용
# ─────────────────────────────────────────────
def build_sandbox_pipe_cmd(
    image: str,
    container_name: str,
    workspace: Path,
    workspace_mount: str,
    model_tag: str,
    ollama_port: int,
    profile_system_message: str,
    context_window: int = 4096,
    memory_limit: Optional[str] = None,
    cpu_limit: Optional[str] = None,
    block_internet: bool = True,
    auto_run: bool = False,  # v5_runaway: 무한 도구 루프 차단
    extra_args: Optional[List[str]] = None,
) -> List[str]:
    """GUI-통합 모드용 docker run 명령 조립.

    중요한 차이점 (vs agent_sandbox._build_command):
        - `-t` (tty) 없음 — PIPE 모드용
        - `-i` (stdin) 있음 — 사용자 입력
        - `--rm` 자동 정리
        - --no_vision 안전장치 (system_message + env var)

    Args:
        profile_system_message: 프로필별 system 메시지 (영어)
        block_internet: True 면 --dns=0.0.0.0
        auto_run: True 면 --auto_run 추가 (샌드박스 안이라 안전)
    """
    cmd = [
        "docker", "run", "--rm", "-i",  # -t 없음!
        "--name", container_name,
        "-v", f"{workspace}:{workspace_mount}",
        "--add-host=host.docker.internal:host-gateway",
        # ErrorGuard: 환경변수로 vision 비활성 표시
        "-e", "DISABLE_VISION=1",
        "-e", "NO_DISPLAY=1",
        "-e", "DISPLAY=",  # 빈 값 — vision 라이브러리들이 fail-fast
        # v5_runaway: Python stdout 즉시 flush (block buffering 해소)
        "-e", "PYTHONUNBUFFERED=1",
        # v5_runaway: LiteLLM banner / 트레이닝 광고 메시지 억제
        "-e", "LITELLM_LOG=ERROR",
        "-e", "AGENT_REPL_SRC=" + _AGENT_REPL_SRC_B64,
    ]

    if block_internet:
        cmd += ["--dns=0.0.0.0"]
    if cpu_limit:
        cmd += [f"--cpus={cpu_limit}"]
    if memory_limit:
        cmd += [f"--memory={memory_limit}"]

    cmd += [
        image, "python3", "-c", _AGENT_REPL_BOOTSTRAP,
        "--model", f"ollama/{model_tag}",
        "--api_base", f"http://host.docker.internal:{ollama_port}",
        "--context_window", str(context_window),
        # v5_runaway: 응답 길이 제한 (stop 토큰 인식 실패 시 자동 cut)
        "--max_tokens", "512",
        "--system_message", profile_system_message,
    ]

    if auto_run:
        cmd += ["--auto_run"]
    if extra_args:
        cmd += list(extra_args)

    return cmd




# ─────────────────────────────────────────────
#  v7_1_unified: 호스트 직접 모드 PIPE 명령 조립
# ─────────────────────────────────────────────
def build_host_pipe_cmd(
    interpreter_exe: str,
    model_tag: str,
    ollama_url: str,
    profile_system_message: str,
    context_window: int = 4096,
    auto_run: bool = False,
    extra_args=None,
):
    """호스트 직접 모드용 interpreter 명령 조립 (PIPE 방식).

    agent_sandbox 의 build_sandbox_pipe_cmd 와 달리 docker 없이
    호스트의 interpreter.exe 를 직접 PIPE 로 실행.

    중요:
      - 컨테이너 격리 없음 (위험) — 호출자가 확인 게이트 통과 필수
      - auto_run 기본 False — 매 명령 사용자 확인 (안전)
      - PYTHONUNBUFFERED 등은 호출자가 env 로 전달

    Args:
        interpreter_exe: interpreter.exe 절대 경로
        model_tag: 모델 태그
        ollama_url: Ollama API URL (예: http://127.0.0.1:11434)
        profile_system_message: 프로필 system 메시지
        auto_run: True 면 --auto_run (위험, 기본 False)
    """
    cmd = [
        interpreter_exe,
        "--model", "ollama/" + model_tag,
        "--api_base", ollama_url,
        "--context_window", str(context_window),
        "--max_tokens", "512",
        "--system_message", profile_system_message,
    ]
    if auto_run:
        cmd += ["--auto_run"]
    if extra_args:
        cmd += list(extra_args)
    return cmd


__all__ = [
    "AgentMessage",
    "UnifiedAgent",
    "build_sandbox_pipe_cmd",
    "build_host_pipe_cmd",
    "looks_like_vision_attempt",
    "LEVEL_STDOUT", "LEVEL_STDERR", "LEVEL_INFO",
    "LEVEL_WARN", "LEVEL_ERROR", "LEVEL_TERMINATED",
]
