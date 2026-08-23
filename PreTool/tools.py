# -*- coding: utf-8 -*-
# >>> PRETOOL_SPEC_v1  (APPLY_PRETOOL_SPEC.py 가 생성)  SPEC_REV=5
"""PreTool.tools — 도구 선언 레지스트리.

원함수는 수정하지 않는다. 여기서는 '인자 타입' 만 선언하고,
설명은 독스트링에서, required 는 실제 기본값 유무에서 자동으로 나온다.

선언이 실제 시그니처와 어긋나면 spec.register() 가 그 도구만 드롭한다.
무엇이 드롭됐는지는 spec.problems() 로 확인한다.

  import PreTool.tools as T
  T.load()                      # 등록 (import 시 자동 1회 실행)
  T.spec.specs()                # 안전 도구 스펙
  T.spec.problems()             # 드롭된 것과 이유
"""
from __future__ import annotations

from . import spec

# 선언 형식:  (모듈, 함수명, safe, 카테고리, {인자: 타입})
#   타입: "string" | "integer" | "number" | "boolean" | "array" | "object" | "any"
#         또는 완전한 JSON Schema dict
#   선언하지 않은 인자는 노출되지 않는다(= 모델이 못 건드림). 기본값이 그대로 쓰인다.

_JSON_TEXT = {"type": "string",
              "description": "JSON 문자열. 객체/배열 모두 가능."}

_SECTIONS = {"type": "array",
             "description": "보고서 절 목록.",
             "items": {"type": "object",
                       "properties": {"heading": {"type": "string"},
                                      "body": {"type": "string"}},
                       "required": ["heading", "body"]}}

_TABLE = [
    # ── 웹 (읽기 전용) ────────────────────────────────────────────
    #  통용 명칭으로 노출한다: web_search / web_fetch / web_research / web_links.
    #  구현 함수명은 그대로 두고 name= 으로 노출 이름만 바꾼다.
    #  search_summary·search_urls·fetch_text 는 web_search·web_fetch 와
    #  입력이 같고 출력 형식만 달라 모델이 고를 근거가 없다 -> 노출 제외.
    #  (코드블록 경로에서는 PreTool.search 로 계속 그대로 쓸 수 있다.)
    #  net_diag 는 사람이 보는 진단이라 모델 표면에 두지 않는다.
    ("search", "web_search",  True,  "web",
     {"query": "string", "n": "integer"}),
    ("search", "open_url",    True,  "web",
     {"url": "string"}),
    ("search", "research",    True,  "web",
     {"query": "string", "n": "integer"}),
    ("search", "page_links",  True,  "web",
     {"url": "string", "n": "integer", "same_site": "boolean"}),

    # ── 데이터 / 텍스트 ────────────────────────────────────────────
    ("data",   "calc",           True,  "data",
     {"expr": "string"}),
    ("data",   "json_pretty",    True,  "data",
     {"s": _JSON_TEXT, "indent": "integer"}),
    ("data",   "json_query",     True,  "data",
     {"data": _JSON_TEXT,
      "path": {"type": "string", "description": "점 표기 경로. 예: 'a.b.0.c'"}}),
    ("data",   "summarize_text", True,  "data",
     {"text": "string", "n": "integer"}),
    ("data",   "word_stats",     True,  "data",
     {"text": "string"}),

    # ── 개발 / 코드 (읽기 전용) ────────────────────────────────────
    ("dev",    "check_syntax",   True,  "dev",
     {"code": "string", "lang": "string"}),
    ("dev",    "lint",           True,  "dev",
     {"code": "string"}),
    ("dev",    "outline",        True,  "dev",
     {"code": "string"}),
    ("dev",    "complexity",     True,  "dev",
     {"code": "string"}),

    # ── 파일 (읽기) ────────────────────────────────────────────────
    ("files",  "list_files",     True,  "file",
     {"folder": "string"}),
    ("excel",  "read_table",     True,  "file",
     {"path": "string"}),

    # ── 부수효과 있음: safe=False → 원격 노출 기본 제외 ────────────
    ("dev",    "run_python",     False, "dev",
     {"code": "string", "stdin": "string", "timeout": "integer"}),
    ("files",  "move",           False, "file",
     {"src": "string", "dst": "string"}),
    ("files",  "copy",           False, "file",
     {"src": "string", "dst": "string"}),
    ("files",  "organize_by_ext", False, "file",
     {"folder": "string"}),
    ("report", "report_write",   False, "doc",
     {"path": "string", "title": "string", "sections": _SECTIONS}),
    ("excel",  "excel_write",    False, "file",
     {"path": "string",
      "rows": {"type": "array", "items": {"type": "array"},
               "description": "행 목록. 각 행은 값의 배열."},
      "headers": {"type": "array", "items": {"type": "string"}}}),
    ("excel",  "csv_write",      False, "file",
     {"path": "string",
      "rows": {"type": "array", "items": {"type": "array"}},
      "headers": {"type": "array", "items": {"type": "string"}}}),
    # run_tests 는 cases 가 튜플 구조라 JSON 표현이 확정되지 않았다 → 보류.
]

# 원함수에 독스트링이 없는 도구들 — 여기서 설명을 공급한다.
# (원함수는 수정하지 않는다. 도구 설명은 '무엇을 하고 언제 쓰는가' 라
#  코드 독스트링과 목적이 다르므로 레지스트리가 제자리다.)
# 통용 명칭으로 노출할 도구 (구현 함수는 그대로).
#   web_search / web_fetch 는 주요 벤더·MCP 레퍼런스 구현이 공유하는 이름이라
#   모델이 별도 설명 없이도 용도를 안다.
_NAME = {
    "open_url": "web_fetch",
    "research": "web_research",
    "page_links": "web_links",
}

_DESC = {
    "web_search": "웹을 검색해 상위 결과를 반환한다 -> "
                  "[{'title','snippet','url'}, ...]. 최신 정보나 확실하지 않은 "
                  "사실이 필요할 때 가장 먼저 쓴다. 요약문만으로 부족하면 "
                  "반환된 url 을 web_fetch 에 넣어 본문을 읽는다.",
    "open_url": "URL 한 개를 열어 제목과 본문 텍스트를 반환한다. HTML 태그와 "
                "스크립트는 제거된다. web_search 가 준 링크를 실제로 읽거나 "
                "사용자가 준 주소를 확인할 때 쓴다. 검색어가 아니라 완전한 "
                "URL 이 필요하다.",
    "research": "검색과 본문 읽기를 한 번에 한다. 상위 n건의 페이지 본문까지 "
                "받아 하나의 텍스트로 정리해 반환한다. 근거가 필요한 조사나 "
                "보고서 작성처럼 web_search 와 web_fetch 를 여러 번 부를 상황을 "
                "한 번으로 끝낸다. 단순 사실 확인에는 web_search 가 더 빠르다.",
    "page_links": "페이지 안의 링크 목록을 반환한다 -> [{'text','url'}, ...]. "
                  "목차·색인·게시판처럼 다음에 읽을 문서를 골라야 할 때 쓴다. "
                  "same_site=true 면 같은 사이트 링크만 남긴다.",
    "move": "파일이나 폴더를 다른 경로로 옮긴다. 대상 폴더가 없으면 만든다. "
            "원본 위치에는 남지 않는다.",
    "copy": "파일이나 폴더를 다른 경로로 복사한다. 원본은 그대로 둔다.",
    "list_files": "폴더 안의 항목 목록을 반환한다 -> "
                  "[{'name','is_dir','size'}, ...]. 하위 폴더는 펼치지 않는다.",
    "json_pretty": "JSON 문자열이나 객체를 들여쓴 읽기 좋은 문자열로 바꾼다.",
    "word_stats": "텍스트의 글자·단어·고유단어·줄 수를 센다 -> "
                  "{'chars','words','unique_words','lines'}.",
    "report_write": "제목과 절 목록으로 Markdown(.md) 또는 HTML(.html) 보고서 파일을 "
                    "만든다. 확장자로 형식이 정해지며 저장된 절대경로를 반환한다.",
    "run_python": "파이썬 코드를 별도 프로세스에서 격리 실행하고 "
                  "{'rc','stdout','stderr','timeout'} 을 반환한다.",
    "outline": "소스 코드에서 함수·클래스 시그니처와 줄번호를 뽑는다. "
               "파일 전체를 읽지 않고 구조만 볼 때 쓴다.",
    "complexity": "소스 코드의 줄 수·함수 수·분기 수와 근사 복잡도를 센다.",
    "csv_write": "행 목록을 .csv 파일로 쓴다. headers 를 주면 첫 행이 된다.",
}

_loaded = False


def load():
    """레지스트리를 spec 에 등록. 여러 번 불러도 안전(멱등)."""
    global _loaded
    if _loaded:
        return spec
    import importlib
    for mod_name, fn_name, safe, cat, types in _TABLE:
        try:
            mod = importlib.import_module("." + mod_name, __package__)
        except Exception:
            continue                       # 모듈 자체가 없으면 조용히 건너뜀
        fn = getattr(mod, fn_name, None)
        if fn is None:
            continue
        spec.register(fn, types=types, safe=safe, category=cat,
                      name=_NAME.get(fn_name), desc=_DESC.get(fn_name))
    _loaded = True
    return spec


def report():
    """등록 현황을 사람이 읽는 텍스트로. 진단용."""
    load()
    ok = spec.specs(safe_only=False)
    lines = ["등록 %d개 (안전 %d / 부수효과 %d)"
             % (len(ok), len(spec.specs()), len(ok) - len(spec.specs()))]
    for s in ok:
        alias = "" if s["impl"] == s["name"] else " <-%s" % s["impl"]
        lines.append("  %-14s%-12s [%s]%s %s"
                     % (s["name"], alias, s["category"],
                        "" if s["safe"] else " *쓰기",
                        s["description"][:46]))
    bad = spec.problems()
    if bad:
        lines.append("")
        lines.append("등록 거부 %d개:" % len(bad))
        for nm, why in bad:
            lines.append("  %-16s %s" % (nm, why))
    return "\n".join(lines)


load()
# <<< PRETOOL_SPEC_v1
