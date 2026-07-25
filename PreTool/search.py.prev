# -*- coding: utf-8 -*-
"""검색/스크랩 도구 — SearXNG(로컬 JSON) 우선, DuckDuckGo 스크랩 폴백.

web_search(query)  -> [{"title","snippet","url"}]
  1) 로컬 SearXNG (host.docker.internal:8888) JSON API — 프록시 우회(직접), Tor 차단·HTML 파싱 회피
  2) 실패 시 DuckDuckGo lite 스크랩 (프록시 경유)
fetch_text(url), search_summary(query) 동일 인터페이스 유지.
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
# SearXNG 위치: 컨테이너에서 호스트 게시 포트로 (Ollama 와 동일 방식). env 로 오버라이드 가능.
_SEARX = os.environ.get("SEARXNG_URL", "http://llm_searxng:8080")  # 공유 네트워크 컨테이너명


def _strip(s):
    s = _TAG.sub(" ", s or "")
    s = _html.unescape(s)
    return " ".join(s.split())


def _direct_opener():
    """프록시 우회(직접) opener — host.docker.internal 로컬 서비스용."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _proxy_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # 기본 opener = HTTP_PROXY 사용
        return r.read().decode("utf-8", "ignore")


def _searxng(query, n=5, timeout=15):
    """로컬 SearXNG. 반환 (결과 or None, 에러문자열 or None)."""
    _err = []
    q = urllib.parse.quote(str(query))
    op = _direct_opener()
    # 1) JSON 포맷
    try:
        url = _SEARX + "/search?format=json&q=" + q
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        data = _json.loads(op.open(req, timeout=timeout).read().decode("utf-8", "ignore"))
        out = []
        for it in (data.get("results") or [])[:n]:
            out.append({"title": _strip(it.get("title", "")),
                        "snippet": _strip(it.get("content", "")),
                        "url": it.get("url", "")})
        if out:
            return out, None
    except Exception as _e:
        _err.append("json:%s" % _e)
    # 2) HTML 포맷 스크랩(포맷 json 비활성 대비)
    try:
        url = _SEARX + "/search?q=" + q
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        raw = op.open(req, timeout=timeout).read().decode("utf-8", "ignore")
        arts = re.findall(r'<article[^>]*class="result[^"]*"[^>]*>(.*?)</article>', raw, re.S)
        out = []
        for a in arts[:n]:
            hm = re.search(r'<a[^>]*href="([^"]*)"', a)
            tm = re.search(r'<h3[^>]*>(.*?)</h3>', a, re.S)
            cm = re.search(r'<p[^>]*class="content"[^>]*>(.*?)</p>', a, re.S)
            out.append({"title": _strip(tm.group(1)) if tm else "",
                        "snippet": _strip(cm.group(1)) if cm else "",
                        "url": _html.unescape(hm.group(1)) if hm else ""})
        if out:
            return out, None
    except Exception as _e:
        _err.append("html:%s" % _e)
    return None, ("; ".join(_err) if _err else "결과 없음")


def _ddg(query, n=5, timeout=30):
    """DuckDuckGo lite 스크랩 (프록시 경유)."""
    q = urllib.parse.quote(str(query))
    try:
        raw = _proxy_get("https://lite.duckduckgo.com/lite/?q=" + q, timeout)
    except Exception as e:
        return [{"title": "", "snippet": "검색 실패(프록시 경유): %s" % e, "url": ""}]
    anchors = re.findall(r'(<a\b[^>]*class="[^"]*result-link[^"]*"[^>]*>)(.*?)</a>', raw, re.S)
    snips = re.findall(r'class="[^"]*result-snippet[^"]*"[^>]*>(.*?)</td>', raw, re.S)
    out = []
    for i, (tag, inner) in enumerate(anchors[:n]):
        hm = re.search(r'href="([^"]*)"', tag)
        out.append({"title": _strip(inner),
                    "snippet": _strip(snips[i]) if i < len(snips) else "",
                    "url": _html.unescape(hm.group(1)) if hm else ""})
    if not out:
        body = _strip(raw)
        if body:
            out.append({"title": "", "snippet": body[:1500], "url": ""})
    return out


def web_search(query, n=5, timeout=30):
    """웹 검색 → [{title,snippet,url}]. SearXNG(로컬) 우선, 실패 시 DuckDuckGo."""
    errs = []
    res, e = _searxng(query, n=n)
    if res:
        return res
    if e:
        errs.append("SearXNG(직접 8888): " + str(e))
    ddg = _ddg(query, n=n, timeout=timeout)
    if ddg and not (len(ddg) == 1 and ddg[0].get("title") == "" and "검색 실패" in ddg[0].get("snippet", "")):
        return ddg
    if ddg:
        errs.append(ddg[0].get("snippet", ""))
    return [{"title": "검색 실패(모든 경로)", "snippet": " || ".join(errs) or "결과 없음", "url": ""}]


def fetch_text(url, timeout=30, limit=4000):
    try:
        return _strip(_proxy_get(url, timeout))[:limit]
    except Exception as e:
        return "가져오기 실패: %s" % e


def search_summary(query, n=5):
    rows = web_search(query, n=n)
    if not rows:
        return "검색 결과 없음: %s" % query
    lines = []
    for i, r in enumerate(rows, 1):
        lines.append("%d. %s\n   %s\n   %s" % (i, r.get("title") or "(제목 없음)",
                                                r.get("snippet", ""), r.get("url", "")))
    return "\n".join(lines)


def net_diag():
    """네트워크 경로 종합 진단 — 무엇이 도달 가능한지, host.docker.internal 이 어떤 IP 인지."""
    import socket
    out = []
    # 1) host.docker.internal 이 어떤 IP 로 해석되는지 (IPv4/IPv6)
    try:
        infos = socket.getaddrinfo("host.docker.internal", None)
        ips = sorted(set(i[4][0] for i in infos))
        out.append("host.docker.internal -> " + ", ".join(ips))
    except Exception as e:
        out.append("host.docker.internal 해석 실패: " + str(e))
    # 2) 기본 게이트웨이 (컨테이너 -> 호스트 경로)
    _gw = None
    try:
        with open("/proc/net/route") as f:
            for line in f.readlines()[1:]:
                p = line.split()
                if len(p) > 2 and p[1] == "00000000":
                    _gw = ".".join(str(int(p[2][i:i+2], 16)) for i in (6, 4, 2, 0))
                    out.append("기본 게이트웨이 -> " + _gw)
                    break
    except Exception:
        pass
    op = _direct_opener()
    def _try(name, url, opener=op, t=6):
        try:
            opener.open(url, timeout=t).read()
            out.append("OK   " + name)
        except Exception as e:
            out.append("FAIL " + name + " -> " + str(e))
    _try("Ollama  host.docker.internal:11434", "http://host.docker.internal:11434/api/version")
    _try("SearXNG host.docker.internal:8888", "http://host.docker.internal:8888/")
    if _gw:
        _try("SearXNG 게이트웨이 %s:8888" % _gw, "http://%s:8888/" % _gw)
    _try("SearXNG 컨테이너명 llm_searxng:8080", "http://llm_searxng:8080/")
    _try("Tor     컨테이너명 llm_tor:8118", "http://llm_tor:8118/")
    _try("인터넷 직접 example.com", "http://example.com/")
    _try("인터넷 프록시경유 8118", "https://lite.duckduckgo.com/lite/?q=t",
         urllib.request.build_opener(), 8)
    return "\n".join(out)
