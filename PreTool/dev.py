# -*- coding: utf-8 -*-
"""개발/코드 도구 — 모의 테스트, 문법·완성 체크, 린트, 구조 분석, diff, 복잡도.

모두 순수 stdlib. 입력은 유연하게: code 는 문자열 또는 파일 경로 모두 허용.
"""
from __future__ import annotations
import ast
import difflib
import io
import os
import subprocess
import sys
import tokenize


def _src(code):
    """문자열이면 그대로, 존재하는 파일 경로면 읽어서 반환(유연)."""
    if isinstance(code, str) and len(code) < 260 and os.path.isfile(code):
        with open(code, encoding="utf-8") as f:
            return f.read()
    return code


# ── 1) 문법 / 완성 체크 ─────────────────────────────────────────────
def check_syntax(code, lang="python"):
    """반환 {ok, error, line, col}. python/json 은 정밀, 그 외는 괄호 균형 검사."""
    src = _src(code)
    lang = (lang or "python").lower()
    if lang in ("py", "python"):
        try:
            compile(src, "<check>", "exec")
            return {"ok": True, "error": None, "line": None}
        except SyntaxError as e:
            return {"ok": False, "error": e.msg, "line": e.lineno, "col": e.offset}
    if lang == "json":
        import json
        try:
            json.loads(src); return {"ok": True, "error": None, "line": None}
        except ValueError as e:
            return {"ok": False, "error": str(e), "line": getattr(e, "lineno", None)}
    # 일반 언어(js/c/...): 괄호·중괄호·대괄호 균형만 확인
    pairs = {")": "(", "]": "[", "}": "{"}
    stack = []
    for i, ch in enumerate(src):
        if ch in "([{":
            stack.append((ch, i))
        elif ch in ")]}":
            if not stack or stack[-1][0] != pairs[ch]:
                ln = src.count("\n", 0, i) + 1
                return {"ok": False, "error": "괄호 불균형 '%s'" % ch, "line": ln}
            stack.pop()
    if stack:
        ln = src.count("\n", 0, stack[-1][1]) + 1
        return {"ok": False, "error": "닫히지 않은 '%s'" % stack[-1][0], "line": ln}
    return {"ok": True, "error": None, "line": None, "note": "괄호 균형만 검사(정밀 파서 아님)"}


# ── 2) 모의 테스트 러너 ─────────────────────────────────────────────
def _norm_case(c):
    """유연: (args, expect) | {'args','kwargs','expect'} | {'input','expect'} 모두 허용."""
    if isinstance(c, dict):
        if "args" in c or "kwargs" in c:
            return list(c.get("args", [])), dict(c.get("kwargs", {})), c.get("expect")
        if "input" in c:
            inp = c["input"]
            args = list(inp) if isinstance(inp, (list, tuple)) else [inp]
            return args, {}, c.get("expect")
    if isinstance(c, (list, tuple)) and len(c) == 2:
        inp, exp = c
        args = list(inp) if isinstance(inp, (list, tuple)) else [inp]
        return args, {}, exp
    raise ValueError("케이스 형식 불명: %r" % (c,))


def run_tests(code, cases, func=None):
    """code 안의 함수를 cases 로 실행해 통과/실패 보고.

    func 미지정 시 top-level 함수가 하나면 자동 선택.
    반환 {total, passed, failed, results:[{args,got,expect,ok,error}]}.
    """
    src = _src(code)
    ns = {}
    try:
        exec(compile(src, "<tests>", "exec"), ns)
    except Exception as e:
        return {"total": 0, "passed": 0, "failed": 0, "error": "코드 실행 실패: %s" % e, "results": []}
    if func is None:
        fns = [k for k, v in ns.items() if callable(v) and not k.startswith("_")
               and getattr(v, "__module__", None) is None]
        if len(fns) == 1:
            func = fns[0]
        else:
            return {"total": 0, "passed": 0, "failed": 0,
                    "error": "함수를 지정하세요(후보: %s)" % ", ".join(fns), "results": []}
    fn = ns.get(func)
    if not callable(fn):
        return {"total": 0, "passed": 0, "failed": 0, "error": "함수 없음: %s" % func, "results": []}
    results = []
    passed = 0
    for c in cases:
        args, kwargs, expect = _norm_case(c)
        row = {"args": args, "expect": expect}
        try:
            got = fn(*args, **kwargs)
            row["got"] = got
            row["ok"] = (got == expect)
            if row["ok"]:
                passed += 1
        except Exception as e:
            row["got"] = None
            row["ok"] = False
            row["error"] = "%s: %s" % (type(e).__name__, e)
        results.append(row)
    return {"total": len(results), "passed": passed,
            "failed": len(results) - passed, "func": func, "results": results}


# ── 3) 임의 코드 실행(격리 subprocess + 타임아웃) ───────────────────
def run_python(code, stdin="", timeout=15):
    src = _src(code)
    try:
        p = subprocess.run([sys.executable, "-c", src], input=stdin,
                           capture_output=True, text=True, timeout=timeout)
        return {"rc": p.returncode, "stdout": p.stdout, "stderr": p.stderr, "timeout": False}
    except subprocess.TimeoutExpired:
        return {"rc": None, "stdout": "", "stderr": "시간 초과 %ss" % timeout, "timeout": True}


# ── 4) 기본 린트 ────────────────────────────────────────────────────
def lint(code):
    """가벼운 정적 점검: 문법·미사용 import·긴 줄·TODO. 반환 {ok, issues:[...]}"""
    src = _src(code)
    issues = []
    syn = check_syntax(src, "python")
    if not syn["ok"]:
        return {"ok": False, "issues": ["문법 오류 (line %s): %s" % (syn["line"], syn["error"])]}
    tree = ast.parse(src)
    imported = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imported[(a.asname or a.name).split(".")[0]] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name != "*":
                    imported[a.asname or a.name] = node.lineno
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for name, ln in imported.items():
        if name not in used:
            issues.append("미사용 import '%s' (line %d)" % (name, ln))
    for i, line in enumerate(src.splitlines(), 1):
        if len(line) > 120:
            issues.append("긴 줄 %d (%d자)" % (i, len(line)))
        if "TODO" in line or "FIXME" in line:
            issues.append("TODO/FIXME (line %d)" % i)
    return {"ok": len(issues) == 0, "issues": issues}


# ── 5) 구조 개요(함수/클래스 시그니처) ──────────────────────────────
def outline(code):
    src = _src(code)
    tree = ast.parse(src)
    items = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            items.append({"kind": "def", "name": node.name,
                          "signature": "%s(%s)" % (node.name, ", ".join(args)),
                          "line": node.lineno})
        elif isinstance(node, ast.ClassDef):
            items.append({"kind": "class", "name": node.name, "line": node.lineno})
    items.sort(key=lambda x: x["line"])
    return items


# ── 6) 텍스트/코드 diff ─────────────────────────────────────────────
def diff(a, b, label_a="a", label_b="b"):
    a_s = _src(a).splitlines(keepends=True)
    b_s = _src(b).splitlines(keepends=True)
    return "".join(difflib.unified_diff(a_s, b_s, label_a, label_b))


# ── 7) 간단 복잡도 지표 ─────────────────────────────────────────────
def complexity(code):
    src = _src(code)
    tree = ast.parse(src)
    branch = sum(isinstance(n, (ast.If, ast.For, ast.While, ast.Try,
                                ast.With, ast.BoolOp, ast.ExceptHandler))
                 for n in ast.walk(tree))
    funcs = sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree))
    classes = sum(isinstance(n, ast.ClassDef) for n in ast.walk(tree))
    lines = len([l for l in src.splitlines() if l.strip()])
    return {"code_lines": lines, "functions": funcs, "classes": classes,
            "branches": branch, "approx_cyclomatic": branch + 1}
