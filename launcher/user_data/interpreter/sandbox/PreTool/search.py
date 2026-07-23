# -*- coding: utf-8 -*-
"""검색/열람 도구 (SEARCH_TOOLS_v2) — 검색 + 본문 읽기 + 다중 페이지 조사.

제공 함수
─────────
  web_search(q)        DDG onion -> SearXNG -> DDG clearnet 순으로 시도
  search_summary(q)    번호·제목·요약·URL 로 정리한 문자열
  open_url(url)        한 페이지의 '읽을 만한 본문' 만 추출 (스크립트/메뉴/푸터 제거)
  page_links(url)      그 페이지의 링크 목록 (추가 탐색용)
  research(q, n)       검색 -> 상위 n건 본문까지 읽어와 한 번에 정리  <- 보고서용
  fetch_text(url)      본문 텍스트 (하위 호환)
  net_diag()           네트워크 경로 진단

익명성
──────
DuckDuckGo 공식 onion 을 1순위로 쓴다. onion 은 Tor 망 내부에서 종단되어 출구 노드가
없으므로 차단할 IP 자체가 존재하지 않고, 계정·API 키·카드도 필요 없다.

엔드포인트
──────────
주소 정본은 launcher/config.py 다. 컨테이너 안에서는 config 를 import 할 수 없으므로
환경변수로 주입받고, 아래 기본값은 그 값을 '미러' 한 것이다.
(미러가 어긋나면 CHECK_ENDPOINTS 가 잡아낸다 — 여기 값을 직접 고치지 말 것)

순수 stdlib.
"""
from __future__ import annotations

import html as _html
import json as _json
import os
import re
import urllib.parse
import urllib.request

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
_TAG = re.compile(r"<[^>]+>")

_SEARX = os.environ.get("SEARXNG_URL", "http://llm_searxng:8080")
_DDG_LITE = os.environ.get("DDG_LITE_URL", "https://lite.duckduckgo.com/lite/")
_DDG_ONION = os.environ.get(
    "DDG_ONION_HOST",
    "duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion")


# ─────────────────────────────────────────────
#  공통
# ─────────────────────────────────────────────
def _strip(s):
    s = _TAG.sub(" ", s or "")
    s = _html.unescape(s)
    return " ".join(s.split())


def _direct_opener():
    """프록시 우회(직접) — 같은 도커 네트워크의 로컬 서비스용."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _proxy_get(url, timeout=30):
    """기본 opener = HTTP_PROXY 사용 -> Privoxy -> Tor."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def _unwrap(u):
    """DDG 리다이렉트(/l/?uddg=...) 를 원래 URL 로 복원."""
    if not u:
        return ""
    u = _html.unescape(u)
    if "uddg=" in u:
        try:
            v = urllib.parse.parse_qs(urllib.parse.urlparse(u).query).get("uddg")
            if v:
                return urllib.parse.unquote(v[0])
        except Exception:
            pass
    if u.startswith("//"):
        u = "https:" + u
    return u


def _is_result_url(u):
    if not u or u.startswith("#"):
        return False
    low = u.lower()
    if low.startswith("javascript:"):
        return False
    bad = ("duckduckgo.com/?", "/settings", "/params", "/about", "/privacy",
           "/traffic", "/feedback", "/bang", "?q=", ".onion/lite")
    return low.startswith("http") and not any(b in low for b in bad)


# ─────────────────────────────────────────────
#  결과 파싱 — 마크업이 바뀌어도 견디는 4중 전략
# ─────────────────────────────────────────────
def _ddg_parse(raw, n=5):
    rows = []

    # 1) lite 마크업 (result-link / result-snippet)
    anchors = re.findall(r'(<a\b[^>]*class="[^"]*result-link[^"]*"[^>]*>)(.*?)</a>', raw, re.S)
    snips = re.findall(r'class="[^"]*result-snippet[^"]*"[^>]*>(.*?)</td>', raw, re.S)
    if anchors:
        for i, (tag, inner) in enumerate(anchors[:n]):
            hm = re.search(r'href="([^"]*)"', tag)
            rows.append({"title": _strip(inner),
                         "snippet": _strip(snips[i]) if i < len(snips) else "",
                         "url": _unwrap(hm.group(1) if hm else "")})
        if rows:
            return rows

    # 2) html 엔드포인트 마크업 (result__a / result__snippet)
    a2 = re.findall(r'<a\b[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
                    raw, re.S)
    if not a2:
        a2 = re.findall(r'<a\b[^>]*href="([^"]*)"[^>]*class="[^"]*result__a[^"]*"[^>]*>(.*?)</a>',
                        raw, re.S)
    s2 = re.findall(r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', raw, re.S)
    if a2:
        for i, (href, inner) in enumerate(a2[:n]):
            rows.append({"title": _strip(inner),
                         "snippet": _strip(s2[i]) if i < len(s2) else "",
                         "url": _unwrap(href)})
        if rows:
            return rows

    # 3) 알려진 클래스가 없는 새 마크업 — 외부 링크만 추림
    seen = set()
    for href, inner in re.findall(r'<a\b[^>]*href="([^"]*)"[^>]*>(.*?)</a>', raw, re.S):
        u = _unwrap(href)
        t = _strip(inner)
        if not (_is_result_url(u) and len(t) >= 2):
            continue
        key = u.split("#")[0]
        if key in seen:
            continue
        seen.add(key)
        rows.append({"title": t, "snippet": "", "url": u})
        if len(rows) >= n:
            break
    if rows:
        sn = re.findall(r'class="[^"]*result-snippet[^"]*"[^>]*>(.*?)</td>', raw, re.S)
        for i, r in enumerate(rows):
            if not r["snippet"] and i < len(sn):
                r["snippet"] = _strip(sn[i])
        return rows

    # 4) 텍스트 폴백 — "1. 제목 ... 도메인/경로" 를 항목으로 분해
    #    태그가 다 날아간 페이지에서도 최소한 제목과 URL 은 건진다.
    txt = _strip(raw)
    parts = re.split(r"(?:(?<=\s)|^)(\d{1,2})\.\s", txt)
    if len(parts) >= 3:
        for i in range(1, len(parts) - 1, 2):
            body = parts[i + 1].strip()
            if not body:
                continue
            m = re.search(r"((?:https?://)?(?:[\w-]+\.)+[a-z]{2,}(?:/[^\s]*)?)", body)
            url = m.group(1) if m else ""
            title = (body[: m.start()].strip() if m else body)
            rest = (body[m.end():].strip() if m else "")
            rows.append({
                "title": (title[:110] or "(제목 없음)"),
                "snippet": (title[110:] + " " + rest).strip()[:400],
                "url": ("https://" + url) if url and not url.startswith("http") else url,
            })
            if len(rows) >= n:
                break
    return rows


# ─────────────────────────────────────────────
#  검색 경로
# ─────────────────────────────────────────────
def _ddg_onion(query, n=5, timeout=45):
    """DDG onion 경유. 출구 노드가 없어 차단되지 않는다."""
    q = urllib.parse.quote(str(query))
    last = ""
    for scheme in ("https", "http"):
        try:
            raw = _proxy_get("%s://%s/lite/?q=%s" % (scheme, _DDG_ONION, q), timeout)
            rows = _ddg_parse(raw, n)
            if rows:
                return rows, None
            last = "결과 파싱 실패"
        except Exception as e:
            last = str(e)[:150]
    return None, last


def _searxng(query, n=5, timeout=20):
    """로컬 SearXNG (같은 도커 네트워크, 프록시 우회)."""
    errs = []
    q = urllib.parse.quote(str(query))
    op = _direct_opener()
    for url in (_SEARX + "/search?format=json&q=" + q, _SEARX + "/search?q=" + q):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            body = op.open(req, timeout=timeout).read().decode("utf-8", "ignore")
            if "format=json" in url:
                try:
                    data = _json.loads(body)
                    out = []
                    for it in (data.get("results") or [])[:n]:
                        out.append({"title": _strip(it.get("title", "")),
                                    "snippet": _strip(it.get("content", "")),
                                    "url": it.get("url", "")})
                    if out:
                        return out, None
                    continue
                except ValueError:
                    pass
            rows = _ddg_parse(body, n)
            if rows:
                return rows, None
        except Exception as e:
            errs.append(str(e)[:90])
    return None, ("; ".join(errs) if errs else "결과 없음")


def _ddg(query, n=5, timeout=30):
    """DuckDuckGo clearnet lite (프록시 경유)."""
    q = urllib.parse.quote(str(query))
    try:
        raw = _proxy_get(_DDG_LITE + "?q=" + q, timeout)
    except Exception as e:
        return [{"title": "", "snippet": "검색 실패(프록시 경유): %s" % e, "url": ""}]
    out = _ddg_parse(raw, n)
    if not out:
        body = _strip(raw)
        if body:
            out.append({"title": "(파싱 실패)", "snippet": body[:1200], "url": ""})
    return out


def web_search(query, n=5, timeout=30):
    """웹 검색 -> [{'title','snippet','url'}, ...]

    순서: DDG onion(완전 익명) -> SearXNG(로컬 메타검색) -> DDG clearnet.
    """
    errs = []
    res, e = _ddg_onion(query, n=n)
    if res:
        return res
    if e:
        errs.append("DDG onion: " + str(e))
    res, e = _searxng(query, n=n)
    if res:
        return res
    if e:
        errs.append("SearXNG: " + str(e))
    ddg = _ddg(query, n=n, timeout=timeout)
    if ddg and not (len(ddg) == 1 and "검색 실패" in ddg[0].get("snippet", "")):
        return ddg
    if ddg:
        errs.append(ddg[0].get("snippet", "")[:120])
    return [{"title": "검색 실패(모든 경로)", "snippet": " || ".join(errs) or "결과 없음",
             "url": ""}]


def search_summary(query, n=5):
    """검색 결과를 읽기 좋은 텍스트로."""
    rows = web_search(query, n=n)
    if not rows:
        return "검색 결과 없음: %s" % query
    lines = []
    for i, r in enumerate(rows, 1):
        lines.append("%d. %s\n   %s\n   %s" % (
            i, r.get("title") or "(제목 없음)",
            (r.get("snippet") or "")[:300], r.get("url", "")))
    return "\n".join(lines)


# ─────────────────────────────────────────────
#  페이지 열람 (서핑)
# ─────────────────────────────────────────────
_DROP_BLOCKS = re.compile(
    r"(?is)<(script|style|noscript|svg|iframe|form|nav|header|footer|aside)[^>]*>.*?</\1>")
_BLOCK_END = re.compile(r"(?is)</(p|div|br|li|h[1-6]|tr|section|article)\s*>")


def _readable(raw):
    """페이지 HTML 에서 '읽을 만한 본문' 만 남긴다."""
    raw = _DROP_BLOCKS.sub(" ", raw)
    m = re.search(r"(?is)<(article|main)[^>]*>(.*?)</\1>", raw)
    body = m.group(2) if m else raw
    body = _BLOCK_END.sub("\n", body)
    body = _TAG.sub(" ", body)
    body = _html.unescape(body)
    lines = []
    for ln in body.splitlines():
        ln = " ".join(ln.split())
        if len(ln) >= 2:
            lines.append(ln)
    # 짧은 메뉴 조각이 연속되는 구간은 네비게이션으로 보고 줄인다
    out, run = [], 0
    for ln in lines:
        if len(ln) < 12:
            run += 1
            if run > 3:
                continue
        else:
            run = 0
        out.append(ln)
    return "\n".join(out)


def page_title(raw):
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    return _strip(m.group(1)) if m else ""


def open_url(url, limit=6000, timeout=40):
    """URL 한 개를 열어 제목 + 본문 텍스트를 반환 (서핑용).

    예)  print(open_url('https://www.yna.co.kr/view/AKR...'))
    """
    if not url:
        return "URL 이 비어 있습니다."
    try:
        raw = _proxy_get(url, timeout)
    except Exception as e:
        return "열기 실패: %s (%s)" % (str(e)[:120], url)
    t = page_title(raw)
    body = _readable(raw)[:limit]
    head = ("# " + t + "\n" + url + "\n\n") if t else (url + "\n\n")
    return head + (body or "(본문을 추출하지 못했습니다)")


def page_links(url, n=25, timeout=40, same_site=False):
    """페이지 안의 링크 목록 -> [{'text','url'}, ...] (추가 탐색용)."""
    try:
        raw = _proxy_get(url, timeout)
    except Exception as e:
        return [{"text": "가져오기 실패: %s" % str(e)[:100], "url": ""}]
    base = urllib.parse.urlparse(url)
    out, seen = [], set()
    for href, inner in re.findall(r'<a\b[^>]*href="([^"]*)"[^>]*>(.*?)</a>', raw, re.S):
        u = _html.unescape(href)
        if u.startswith("//"):
            u = base.scheme + ":" + u
        elif u.startswith("/"):
            u = "%s://%s%s" % (base.scheme, base.netloc, u)
        elif not u.lower().startswith("http"):
            continue
        if same_site and urllib.parse.urlparse(u).netloc != base.netloc:
            continue
        key = u.split("#")[0]
        if key in seen:
            continue
        seen.add(key)
        t = _strip(inner)
        if len(t) < 2:
            continue
        out.append({"text": t[:100], "url": u})
        if len(out) >= n:
            break
    return out


def fetch_text(url, timeout=30, limit=4000):
    """URL 본문 텍스트 (하위 호환)."""
    try:
        raw = _proxy_get(url, timeout)
    except Exception as e:
        return "가져오기 실패: %s" % e
    return _readable(raw)[:limit]


def research(query, n=3, chars=1800, timeout=40):
    """검색 -> 상위 n건의 '본문까지' 읽어와 한 번에 정리 (보고서 작성용).

    검색 요약만으로는 근거가 부족하므로 실제 페이지 본문을 붙여 준다.
    예)  print(research('어제 코스피 마감', n=3))
    """
    rows = web_search(query, n=max(n, 3))
    if not rows or (len(rows) == 1 and not rows[0].get("url")):
        return "검색 결과 없음: %s\n%s" % (
            query, (rows[0].get("snippet", "") if rows else ""))
    blocks = ["[검색어] %s" % query]
    got = 0
    for r in rows:
        u = r.get("url") or ""
        if not u:
            continue
        blocks.append("\n" + "=" * 56)
        blocks.append("## %s\n%s" % (r.get("title") or "(제목 없음)", u))
        sn = (r.get("snippet") or "").strip()
        if sn:
            blocks.append("[요약] " + sn[:300])
        try:
            raw = _proxy_get(u, timeout)
            body = _readable(raw)[:chars]
        except Exception as e:
            body = "(본문 열기 실패: %s)" % str(e)[:100]
        blocks.append("[본문]\n" + (body or "(추출 실패)"))
        got += 1
        if got >= n:
            break
    if got == 0:
        return "URL 이 있는 결과를 찾지 못했습니다.\n" + search_summary(query, n=n)
    blocks.append("\n" + "=" * 56)
    blocks.append("위 [본문] 에 실제로 나온 내용만 근거로 작성하세요.")
    return "\n".join(blocks)


# ─────────────────────────────────────────────
#  진단
# ─────────────────────────────────────────────
def net_diag():
    """네트워크 경로 진단 — 무엇이 도달 가능한지."""
    lines = []

    def _try(label, url, direct=False, timeout=20):
        try:
            op = _direct_opener() if direct else None
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            r = (op.open(req, timeout=timeout) if op
                 else urllib.request.urlopen(req, timeout=timeout))
            lines.append("[ OK ] %s (HTTP %s)" % (label, getattr(r, "status", "?")))
        except Exception as e:
            lines.append("[FAIL] %s -> %s" % (label, str(e)[:110]))

    _try("SearXNG (%s)" % _SEARX, _SEARX + "/", direct=True)
    _try("DDG onion (Tor 내부)", "https://%s/lite/?q=test" % _DDG_ONION, timeout=45)
    _try("DDG clearnet (프록시)", _DDG_LITE + "?q=test")
    _try("Tor 확인", "https://check.torproject.org/api/ip", timeout=40)
    return "\n".join(lines)
