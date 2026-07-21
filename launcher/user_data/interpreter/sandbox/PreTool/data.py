# -*- coding: utf-8 -*-
"""범용 데이터/텍스트 도구 — 안전 계산, JSON 처리, 텍스트 요약. 순수 stdlib."""
from __future__ import annotations
import ast as _ast
import json as _json
import operator as _op
import re

# ── 안전 산술 계산 (이름/함수 호출 없이 숫자·연산자만) ──────────────
_OPS = {_ast.Add: _op.add, _ast.Sub: _op.sub, _ast.Mult: _op.mul,
        _ast.Div: _op.truediv, _ast.FloorDiv: _op.floordiv, _ast.Mod: _op.mod,
        _ast.Pow: _op.pow, _ast.USub: _op.neg, _ast.UAdd: _op.pos}


def _ev(node):
    if isinstance(node, _ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, _ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_ev(node.left), _ev(node.right))
    if isinstance(node, _ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_ev(node.operand))
    raise ValueError("허용되지 않은 식")


def calc(expr):
    """'2*(3+4)**2' 같은 산술식을 안전하게 계산(eval 미사용). 실패 시 문자열 에러."""
    try:
        return _ev(_ast.parse(str(expr), mode="eval").body)
    except Exception as e:
        return "계산 불가: %s" % e


# ── JSON ────────────────────────────────────────────────────────────
def json_pretty(s, indent=2):
    try:
        obj = _json.loads(s) if isinstance(s, str) else s
        return _json.dumps(obj, ensure_ascii=False, indent=indent)
    except ValueError as e:
        return "JSON 오류: %s" % e


def json_query(data, path, default=None):
    """dot/인덱스 경로로 값 추출: 'a.b.0.c'. data 는 dict/list 또는 JSON 문자열."""
    if isinstance(data, str):
        try:
            data = _json.loads(data)
        except ValueError:
            return default
    cur = data
    for key in str(path).split("."):
        try:
            if isinstance(cur, list):
                cur = cur[int(key)]
            else:
                cur = cur[key]
        except (KeyError, IndexError, ValueError, TypeError):
            return default
    return cur


# ── 텍스트 요약(추출식, 단어 빈도 기반) ─────────────────────────────
_SENT = re.compile(r"[^.!?。\n]+[.!?。]?")
_WORD = re.compile(r"[가-힣A-Za-z0-9]+")


def summarize_text(text, n=3):
    """가장 대표적인 문장 n개를 원문 순서로 반환(외부 모델 불필요)."""
    text = (text or "").strip()
    sents = [s.strip() for s in _SENT.findall(text) if len(s.strip()) > 10]
    if len(sents) <= n:
        return " ".join(sents)
    freq = {}
    for w in _WORD.findall(text.lower()):
        if len(w) > 1:
            freq[w] = freq.get(w, 0) + 1
    scored = []
    for i, s in enumerate(sents):
        ws = _WORD.findall(s.lower())
        score = sum(freq.get(w, 0) for w in ws) / (len(ws) + 1)
        scored.append((score, i, s))
    top = sorted(scored, reverse=True)[:n]
    return " ".join(s for _, _, s in sorted(top, key=lambda x: x[1]))


def word_stats(text):
    words = _WORD.findall(text or "")
    return {"chars": len(text or ""), "words": len(words),
            "unique_words": len(set(w.lower() for w in words)),
            "lines": (text or "").count("\n") + 1}
