# -*- coding: utf-8 -*-
# >>> PRETOOL_SPEC_v1  (APPLY_PRETOOL_SPEC.py 가 생성)  SPEC_REV=5
"""PreTool.spec — 도구 스펙(JSON Schema) 생성기.

순수 stdlib. 원함수를 수정하지 않는다.

  타입    : 레지스트리(tools.py)가 선언
  설명    : 원함수 독스트링에서 자동 추출
  required: 실제 시그니처의 기본값 유무에서 자동 판정

register() 는 선언을 실제 시그니처와 대조한다. 어긋나면 등록을 거부하므로,
레지스트리가 낡아도 잘못된 스키마가 모델에게 나가지 않는다.
"""
from __future__ import annotations

import inspect
import json
import re

__all__ = ["register", "describe", "specs", "catalog_like", "problems",
           "to_openai", "to_mcp", "to_anthropic", "call", "call_text",
           "recover"]

_REG = {}        # name -> {"fn","types","safe","category","desc"}
_PROBLEMS = []   # [(name, 이유)] — 등록이 거부된 것

# 짧은 별칭 -> JSON Schema 조각
_ALIAS = {
    "string": {"type": "string"},
    "integer": {"type": "integer"},
    "number": {"type": "number"},
    "boolean": {"type": "boolean"},
    "array": {"type": "array"},
    "object": {"type": "object"},
    "any": {},
}


def _schema_of(decl):
    """레지스트리 값 -> JSON Schema 조각. 문자열 별칭 또는 완전한 dict."""
    if isinstance(decl, dict):
        return dict(decl)
    return dict(_ALIAS.get(decl, {}))


# ── 독스트링 파싱 (Google 스타일 + 한국어 헤더) ─────────────────────
_ARGS_HDR = re.compile(r"^\s*(Args|Arguments|인자|매개변수)\s*:\s*$", re.I)
_SECT_HDR = re.compile(r"^\s*(Returns|Raises|Examples?|반환|예|주의)\s*:?\s*$", re.I)
_ARG_LINE = re.compile(r"^\s{2,}(\*{0,2}\w+)\s*(?:\([^)]*\))?\s*:\s*(.+)$")


def parse_doc(doc):
    """독스트링 -> (요약, {인자명: 설명}). 요약은 첫 문단."""
    if not doc:
        return "", {}
    summary, params, cur = [], {}, None
    in_args = False
    done = False
    for ln in inspect.cleandoc(doc).splitlines():
        if _ARGS_HDR.match(ln):
            in_args, cur, done = True, None, True
            continue
        if in_args and _SECT_HDR.match(ln):
            in_args, cur = False, None
            continue
        if in_args:
            m = _ARG_LINE.match(ln)
            if m:
                cur = m.group(1).lstrip("*")
                params[cur] = m.group(2).strip()
            elif cur and ln.strip():
                params[cur] += " " + ln.strip()
            continue
        if not ln.strip():
            if summary:
                done = True
            continue
        if not done:
            summary.append(ln.strip())
    return " ".join(summary).strip(), params


# ── 등록 (시그니처 대조 포함) ───────────────────────────────────────
def _accepts_kwargs(sig):
    return any(p.kind is p.VAR_KEYWORD for p in sig.parameters.values())


def register(fn, types=None, safe=True, category="", name=None, desc=None):
    """도구 등록. 선언이 실제 시그니처와 어긋나면 등록하지 않고 False.

    Args:
        fn: 대상 함수 (원본 그대로. 수정하지 않는다).
        types: {인자명: 별칭|JSON Schema}. 선언한 인자만 노출된다.
        safe: False 면 부수효과(쓰기/실행). 원격 노출에서 기본 제외.
        category: 묶음 이름.
        name: 노출 이름 (기본 fn.__name__).
        desc: 설명 (기본 독스트링 첫 문단).
    """
    nm = name or getattr(fn, "__name__", None)
    if not callable(fn) or not nm:
        _PROBLEMS.append((str(name), "호출 가능한 함수가 아님"))
        return False
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError) as e:
        _PROBLEMS.append((nm, "시그니처 조회 실패: %s" % e))
        return False

    types = dict(types or {})
    real = sig.parameters
    kw = _accepts_kwargs(sig)

    # (1) 선언했는데 실제로 없는 인자 -> 거부
    unknown = [k for k in types if k not in real and not kw]
    if unknown:
        _PROBLEMS.append((nm, "실제 시그니처에 없는 인자: %s" % ", ".join(sorted(unknown))))
        return False

    # (2) 기본값 없는 필수 인자를 선언에서 빠뜨림 -> 거부
    missing = [k for k, p in real.items()
               if p.default is p.empty
               and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
               and not k.startswith("_")
               and k not in types]
    if missing:
        _PROBLEMS.append((nm, "필수 인자가 선언되지 않음: %s" % ", ".join(missing)))
        return False

    summary, _ = parse_doc(fn.__doc__)
    _REG[nm] = {"fn": fn, "types": types, "safe": bool(safe),
                "category": category, "desc": desc or summary or nm}
    return True


def problems():
    """등록이 거부된 목록 -> [(이름, 이유)]. 진단용."""
    return list(_PROBLEMS)


# ── 스펙 생성 ───────────────────────────────────────────────────────
def describe(name):
    e = _REG[name]
    fn, sig = e["fn"], inspect.signature(e["fn"])
    _, pdocs = parse_doc(fn.__doc__)
    props, required = {}, []
    for k, decl in e["types"].items():
        sub = _schema_of(decl)
        if k in pdocs and "description" not in sub:
            sub["description"] = pdocs[k]
        p = sig.parameters.get(k)
        if p is not None and p.default is not p.empty:
            if isinstance(p.default, (str, int, float, bool)) and not isinstance(p.default, type(None)):
                sub.setdefault("default", p.default)
        else:
            required.append(k)
        props[k] = sub
    return {"name": name, "description": e["desc"], "safe": e["safe"],
            "category": e["category"],
            "impl": getattr(fn, "__name__", name),
            "parameters": {"type": "object", "properties": props,
                           "required": required}}


def specs(names=None, safe_only=True, category=None):
    out = []
    for nm in sorted(_REG):
        e = _REG[nm]
        if names is not None and nm not in names:
            continue
        if safe_only and not e["safe"]:
            continue
        if category is not None and e["category"] != category:
            continue
        out.append(describe(nm))
    return out


def catalog_like(safe_only=False):
    """catalog() 와 같은 모양({'name(sig)': '설명'}) 으로. 기존 catalog() 는 건드리지 않는다."""
    out = {}
    for s in specs(safe_only=safe_only):
        args = ", ".join(
            k if k in s["parameters"]["required"]
            else "%s=%r" % (k, v["default"]) if "default" in v else k
            for k, v in s["parameters"]["properties"].items())
        out["%s(%s)" % (s["name"], args)] = s["description"]
    return out


# ── 규약 어댑터 ─────────────────────────────────────────────────────
def to_openai(s):
    return {"type": "function", "function": {
        "name": s["name"], "description": s["description"],
        "parameters": s["parameters"]}}


def to_anthropic(s):
    return {"name": s["name"], "description": s["description"],
            "input_schema": s["parameters"]}


def to_mcp(s):
    return {"name": s["name"], "description": s["description"],
            "inputSchema": s["parameters"]}


# ── 호출 계약 ───────────────────────────────────────────────────────
def call(name, arguments=None, safe_only=True):
    """{'ok': bool, 'data'|'error'}. 예외를 밖으로 던지지 않는다."""
    e = _REG.get(name)
    if e is None:
        return {"ok": False, "error": "unknown tool: %s" % name}
    if safe_only and not e["safe"]:
        return {"ok": False, "error": "tool not permitted here: %s" % name}
    args = dict(arguments or {})
    extra = [k for k in args if k not in e["types"]]
    if extra:
        return {"ok": False, "error": "선언되지 않은 인자: %s" % ", ".join(sorted(extra))}
    try:
        return {"ok": True, "data": e["fn"](**args)}
    except TypeError as ex:
        return {"ok": False, "error": "bad arguments: %s" % ex}
    except Exception as ex:
        return {"ok": False, "error": "%s: %s" % (type(ex).__name__, ex)}


def call_text(name, arguments=None, safe_only=True, limit=20000):
    r = call(name, arguments, safe_only)
    if not r["ok"]:
        return "ERROR: " + r["error"]
    d = r["data"]
    s = d if isinstance(d, str) else json.dumps(d, ensure_ascii=False, indent=1)
    return s[:limit]

# ── 텍스트로 흘러나온 도구 호출 복구 ───────────────────────────────
# 일부 모델·런타임 조합에서 모델이 올바른 호출 JSON 을 만들고도
# <tool_call> 태그를 빼먹어 tool_calls 로 승격되지 않는다.
# (실측: qwen2.5-coder:14b + Ollama 0.32.13 에서 100% 발생)
# 그럴 때 본문에서 호출을 되살린다. 등록된 이름과 대조하므로
# 아무 JSON 이나 도구 호출로 오인하지 않는다.
_TAG = re.compile(r"<tool_call>(.*?)</tool_call>", re.S)
_FENCE = re.compile(r"```(?:json|tool_call)?\s*(.*?)```", re.S)


def _objects(text):
    """문자열에서 최상위 JSON 객체들을 순서대로 뽑는다."""
    dec = json.JSONDecoder()
    i, n = 0, len(text)
    while i < n:
        j = text.find("{", i)
        if j < 0:
            return
        try:
            obj, end = dec.raw_decode(text, j)
        except ValueError:
            i = j + 1
            continue
        yield obj
        i = end


def _as_call(obj):
    """{'name','arguments'} 또는 {'function':{...}} 를 (이름, 인자) 로."""
    if not isinstance(obj, dict):
        return None
    if isinstance(obj.get("function"), dict):
        obj = obj["function"]
    name = obj.get("name")
    args = obj.get("arguments", obj.get("parameters", {}))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return None
    if not isinstance(name, str) or not isinstance(args, dict):
        return None
    return name, args


def recover(content, safe_only=True):
    """본문 텍스트에서 도구 호출을 복구 -> [(이름, 인자), ...].

    등록되지 않은 이름은 버린다. 호출은 하지 않는다(판단은 호출자 몫).

    Args:
        content: 모델 응답의 message.content.
        safe_only: True 면 부수효과 도구는 복구 대상에서 제외한다.
    """
    text = content or ""
    chunks = _TAG.findall(text) or _FENCE.findall(text) or [text]
    out = []
    for ch in chunks:
        for obj in _objects(ch):
            c = _as_call(obj)
            if c is None:
                continue
            name, args = c
            e = _REG.get(name)
            if e is None:
                continue
            if safe_only and not e["safe"]:
                continue
            if any(k not in e["types"] for k in args):
                continue
            out.append((name, args))
    return out
# <<< PRETOOL_SPEC_v1
