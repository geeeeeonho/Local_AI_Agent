# -*- coding: utf-8 -*-
# >>> PRETOOL_SPEC_v1  (APPLY_PRETOOL_SPEC.py 가 생성)  SPEC_REV=5
"""PreTool.agent — Ollama 자체 tool-calling 루프.

순수 stdlib. 기존 코드블록 miniloop 과 별개 경로이며 서로 간섭하지 않는다.

한 턴의 처리
  1) /api/chat 에 specs() -> to_openai() 도구 목록을 얹어 보낸다
  2) message.tool_calls 가 있으면 그것을 쓴다
  3) 없으면 message.content 에서 spec.recover() 로 되살린다
     (qwen2.5-coder + Ollama 조합에서 100% 이 경로를 탄다 - 실측)
  4) 되살린 호출은 정규 tool_calls 형태로 재구성해 대화에 넣는다
     그래야 모델이 자기 호출 이력을 템플릿대로 읽는다
  5) spec.call() 로 실행하고 role="tool" 로 결과를 되먹인다
  6) 호출이 없으면 그 content 가 최종 답이다

멈춤 조건
  - 도구 호출 없음 (정상 종료)
  - max_steps 도달
  - 같은 (도구, 인자) 재호출 -> 루프로 판단하고 중단

사용
  from PreTool.agent import run
  r = run("오늘 코스피 지수 알려줘", model="qwen2.5-coder:14b")
  print(r["text"])

  py -3 -m PreTool.agent --model qwen2.5-coder:14b "오늘 코스피 지수 알려줘"
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from . import spec
from . import tools as _tools           # import 만으로 레지스트리가 채워진다

__all__ = ["run", "DEFAULT_HOST"]

DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_MODEL = os.environ.get("PRETOOL_AGENT_MODEL", "qwen2.5-coder:14b")

RESULT_LIMIT = 6000        # 도구 결과 1건을 대화에 넣을 때의 상한
_MAX_STEPS = 6


def _post(host, path, obj, timeout):
    req = urllib.request.Request(
        host + path,
        data=json.dumps(obj, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _native_calls(msg):
    """message.tool_calls -> [(이름, 인자), ...]. 형식이 어긋나면 건너뛴다."""
    out = []
    for c in (msg.get("tool_calls") or []):
        fn = c.get("function") or {}
        name, args = fn.get("name"), fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                continue
        if isinstance(name, str) and isinstance(args, dict):
            out.append((name, args))
    return out


def _as_tool_calls(calls):
    """(이름, 인자) 목록 -> Ollama 가 이해하는 tool_calls 구조."""
    return [{"function": {"name": n, "arguments": a}} for n, a in calls]


def _key(name, args):
    return name + "|" + json.dumps(args, ensure_ascii=False, sort_keys=True)


def run(user, model=None, system=None, max_steps=_MAX_STEPS, safe_only=True,
        host=None, timeout=180, trace=None, temperature=0.0):
    """도구를 쓰는 한 번의 대화를 끝까지 돌린다.

    Args:
        user: 사용자 요청 문자열.
        model: Ollama 모델 태그. 생략 시 PRETOOL_AGENT_MODEL 환경변수.
        system: 시스템 메시지. 생략하면 넣지 않는다(실측상 영향 없음).
        max_steps: 도구 호출 왕복 최대 횟수.
        safe_only: True 면 부수효과 도구를 노출하지도 실행하지도 않는다.
        host: Ollama 주소. 생략 시 OLLAMA_HOST.
        trace: 진행 상황을 받을 콜백 f(단계, 종류, 내용). 생략 가능.
        temperature: 기본 0.

    반환:
        {'ok', 'text', 'steps', 'calls', 'stop', 'error'}
          calls: [{'step','name','args','via','ok','result'}, ...]
                 via 는 'native'(tool_calls) 또는 'recovered'(본문 복구)
          stop:  'answer' | 'max_steps' | 'loop' | 'error'
    """
    host = (host or DEFAULT_HOST).rstrip("/")
    model = model or DEFAULT_MODEL
    say = trace or (lambda *a: None)

    tool_specs = [spec.to_openai(s) for s in spec.specs(safe_only=safe_only)]
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": user})

    calls_log, seen = [], set()
    text, stop = "", "max_steps"

    for step in range(1, max_steps + 1):
        body = {"model": model, "stream": False,
                "options": {"temperature": temperature},
                "messages": msgs, "tools": tool_specs}
        try:
            resp = _post(host, "/api/chat", body, timeout)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            return {"ok": False, "text": "", "steps": step - 1,
                    "calls": calls_log, "stop": "error",
                    "error": "HTTP %s %s" % (e.code, detail)}
        except Exception as e:
            return {"ok": False, "text": "", "steps": step - 1,
                    "calls": calls_log, "stop": "error",
                    "error": "%s: %s" % (type(e).__name__, e)}

        msg = (resp or {}).get("message") or {}
        content = msg.get("content") or ""

        pairs = _native_calls(msg)
        via = "native"
        if not pairs and content:
            pairs = spec.recover(content, safe_only=safe_only)
            via = "recovered"

        if not pairs:
            text, stop = content, "answer"
            say(step, "answer", content)
            break

        # 모델 턴을 정규 형태로 기록 (복구분도 tool_calls 로 재구성)
        msgs.append({"role": "assistant", "content": "",
                     "tool_calls": _as_tool_calls(pairs)})

        looped = False
        for name, args in pairs:
            k = _key(name, args)
            if k in seen:
                say(step, "loop", name)
                looped = True
                break
            seen.add(k)

            say(step, "call", "%s(%s)" % (name, json.dumps(args, ensure_ascii=False)))
            r = spec.call(name, args, safe_only=safe_only)
            out = (r["data"] if r["ok"] else "ERROR: " + r["error"])
            if not isinstance(out, str):
                out = json.dumps(out, ensure_ascii=False)
            out = out[:RESULT_LIMIT]
            say(step, "result", out[:200])

            calls_log.append({"step": step, "name": name, "args": args,
                              "via": via, "ok": r["ok"], "result": out})
            msgs.append({"role": "tool", "content": out, "tool_name": name})

        if looped:
            stop = "loop"
            text = content
            break
    else:
        stop = "max_steps"

    return {"ok": stop in ("answer", "max_steps", "loop"), "text": text,
            "steps": len(calls_log), "calls": calls_log,
            "stop": stop, "error": None}


# ── CLI ─────────────────────────────────────────────────────────────
def _main(argv=None):
    import argparse
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(prog="PreTool.agent")
    ap.add_argument("prompt", nargs="+")
    ap.add_argument("--model", default=None)
    ap.add_argument("--host", default=None)
    ap.add_argument("--steps", type=int, default=_MAX_STEPS)
    ap.add_argument("--all", action="store_true", help="쓰기 도구도 허용")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    def tr(step, kind, body):
        if a.quiet:
            return
        tag = {"call": "호출", "result": "결과", "answer": "답변",
               "loop": "반복중단"}.get(kind, kind)
        print("  [%d] %-6s %s" % (step, tag, body.replace("\n", " ")[:160]))

    r = run(" ".join(a.prompt), model=a.model, host=a.host,
            max_steps=a.steps, safe_only=not a.all, trace=tr)
    print("-" * 60)
    if r["error"]:
        print("실패: %s" % r["error"])
        return 1
    print(r["text"] or "(빈 응답)")
    print("-" * 60)
    print("도구 %d회 / 종료=%s / 복구경로 %d회"
          % (len(r["calls"]), r["stop"],
             sum(1 for c in r["calls"] if c["via"] == "recovered")))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
# <<< PRETOOL_SPEC_v1
