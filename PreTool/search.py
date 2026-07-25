# -*- coding: utf-8 -*-
"""검색/열람 도구 (SEARCH_TOOLS_v4) — 병렬 경주 + 차단 감지 + 아카이브 우회.

제공 함수
─────────
  web_search(q)        DDG onion -> SearXNG -> DDG clearnet 순으로 시도
  search_summary(q)    번호·제목·요약·URL 로 정리한 문자열
  open_url(url)        한 페이지의 '읽을 만한 본문' 만 추출 (스크립트/메뉴/푸터 제거)
  page_links(url)      그 페이지의 링크 목록 (추가 탐색용)
  research(q, n)       검색 -> 상위 n건 본문까지 읽어와 한 번에 정리  <- 보고서용
  fetch_text(url)      본문 텍스트 (하위 호환)
  net_diag()           네트워크 경로 진단

속도 (v3)
─────────
예전에는 onion -> SearXNG -> clearnet 을 '순차' 로 시도해서, onion 이 느리면 최대 45초를
버린 뒤에야 다음 경로로 넘어갔다. v3 는 onion 과 clearnet 을 '동시에' 쏘고 먼저 도착한
결과를 쓴다(병렬 경주). 둘 다 Tor 를 지나므로 익명성은 동일하고, 지연만 줄어든다.

  SEARCH_PATH 환경변수로 강제할 수 있다:
    race(기본) | onion | clearnet | searxng

차단 대응 (v4)
──────────────
Cloudflare 등은 Tor 출구 IP 를 CAPTCHA/403 으로 막는다. 이건 코드로 '뚫을' 수 없다.
대신 v4 는 세 가지를 한다:
  1) 차단 감지 — CAPTCHA/챌린지 페이지를 '본문' 으로 착각하지 않는다.
     (이게 없으면 모델이 "Attention Required! Cloudflare Ray ID..." 를 근거로
      보고서를 쓰는 조용한 환각이 발생한다. 가장 위험한 실패 모드다.)
  2) 아카이브 우회 — 막히면 Wayback Machine 스냅샷으로 자동 재시도.
     archive.org 는 Tor 에 관대하고, 원본 대신 저장된 사본을 준다.
  3) 정직한 실패 — 그래도 안 되면 '차단됨' 이라고 명시한다. 추측하지 않는다.

익명성
──────
모든 경로가 Tor 를 지난다.
  - onion    : 출구 노드를 아예 거치지 않음(차단 불가, 최상)
  - clearnet : 출구 노드를 거치지만 HTTPS 로 암호화됨. DDG 는 출구 IP만 봄
계정/API 키/신용카드가 필요 없다 -> 검색이 신원에 묶이지 않는다.
(Brave Search API 는 카드 등록이 필수라 '키=실명' 이 되어 익명성에 역행한다.)

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


def _safe_url(u):
    """비ASCII URL 을 안전하게 인코딩.

    'https://ko.wikipedia.org/wiki/코스피지수' 같은 주소는 그대로 urlopen 에 넘기면
    UnicodeEncodeError('ascii' codec can't encode) 로 죽는다. 한국 사이트에서 흔하므로
    경로·쿼리는 퍼센트 인코딩, 호스트는 IDNA 로 변환한다.
    """
    if not u:
        return u
    try:
        u.encode("ascii")
        return u
    except UnicodeEncodeError:
        pass
    try:
        sp = urllib.parse.urlsplit(u)
        netloc = sp.netloc
        try:
            netloc = netloc.encode("idna").decode("ascii")
        except Exception:
            netloc = urllib.parse.quote(netloc, safe=":@")
        return urllib.parse.urlunsplit((
            sp.scheme,
            netloc,
            urllib.parse.quote(sp.path, safe="/%"),
            urllib.parse.quote(sp.query, safe="=&%+"),
            urllib.parse.quote(sp.fragment, safe="%"),
        ))
    except Exception:
        return u


def _proxy_get(url, timeout=30):
    """기본 opener = HTTP_PROXY 사용 -> Privoxy -> Tor."""
    req = urllib.request.Request(_safe_url(url), headers={"User-Agent": _UA})
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




# ─────────────────────────────────────────────
#  공용 SearXNG 중계 (PUBLIC_RELAY_v1)
#
#  구조:  내 PC -> Tor -> 공용 SearXNG 인스턴스 -> Google/Bing/DDG
#
#  왜 통하나
#    - 공용 인스턴스는 'Tor 출구 IP' 만 본다 -> 내 실제 IP 노출 0
#    - 구글 입장에서는 '인스턴스의 데이터센터 IP' 에서 온 요청 -> Tor 차단에 안 걸림
#    - 공용 SearXNG 운영자는 대개 프라이버시 지향이라 Tor 접속을 막지 않는다
#    - 비용 0, RAM 0 (네트워크 설정만)
#
#  한계 (정직하게)
#    - 인스턴스 운영자는 '어떤 질의가 왔는지' 는 본다. 다만 누가 보냈는지는 모른다
#      (Tor 뒤에 있으므로). 그래서 여러 인스턴스를 순환해 한 곳에 질의가 쌓이지 않게 한다.
#    - 인스턴스는 수시로 죽는다 -> 실패하면 다음 인스턴스로 넘어간다.
#    - 공용 인스턴스는 rate limit 이 있다 -> 남용하지 않는다.
#
#  SEARXNG_PUBLIC 환경변수로 목록을 덮어쓸 수 있다(쉼표 구분).
# ─────────────────────────────────────────────
_PUBLIC_DEFAULT = (
    "https://searx.be",
    "https://search.inetol.net",
    "https://priv.au",
    "https://opnxng.com",
    "https://searxng.site",
    "https://search.bus-hit.me",
)

PUBLIC_SEARX = tuple(
    u.strip().rstrip("/")
    for u in os.environ.get("SEARXNG_PUBLIC", ",".join(_PUBLIC_DEFAULT)).split(",")
    if u.strip()
)


def _public_searx(query, n=5, timeout=25, tries=3):
    """공용 SearXNG 인스턴스를 Tor 로 경유해 검색.

    인스턴스를 무작위 순서로 돌며 성공할 때까지 시도한다(부하 분산 + 질의 분산).
    """
    import random
    if not PUBLIC_SEARX:
        return None, "공용 인스턴스 목록이 비어 있음"
    cands = list(PUBLIC_SEARX)
    random.shuffle(cands)
    q = urllib.parse.quote(str(query))
    errs = []
    for base in cands[:max(1, tries)]:
        for path in ("/search?format=json&q=", "/search?q="):
            url = base + path + q
            try:
                raw = _proxy_get(url, timeout)
            except Exception as e:
                errs.append("%s: %s" % (base.split("//")[-1], str(e)[:60]))
                break
            if "format=json" in path:
                try:
                    data = _json.loads(raw)
                    rows = []
                    for it in (data.get("results") or [])[:n]:
                        rows.append({"title": _strip(it.get("title", "")),
                                     "snippet": _strip(it.get("content", "")),
                                     "url": it.get("url", "")})
                    if rows:
                        return rows, None
                    continue
                except ValueError:
                    pass  # JSON 미허용 인스턴스 -> HTML 파싱으로
            rows = _ddg_parse(raw, n)
            if rows:
                return rows, None
            errs.append("%s: 파싱 실패" % base.split("//")[-1])
    return None, ("; ".join(errs[:3]) if errs else "모든 공용 인스턴스 실패")


# ─────────────────────────────────────────────
#  병렬 경주 (SEARCH_TOOLS_v3)
# ─────────────────────────────────────────────
_PATH_MODE = os.environ.get("SEARCH_PATH", "race").strip().lower()


def _race_search(query, n=5, timeout=25):
    """onion 과 clearnet 을 동시에 쏘고 먼저 도착한 결과를 쓴다.

    순차 폴백은 첫 경로가 느릴 때 그 시간을 통째로 버린다. 두 경로 모두 Tor 를
    지나므로 익명성 차이가 없고, 검색 쿼리는 아주 가벼우므로 동시 발사의 부담도 작다.
    """
    import threading
    import queue as _q

    out = _q.Queue()

    def _run(name, fn):
        try:
            rows = fn()
            if rows:
                out.put((name, rows, None))
            else:
                out.put((name, None, "결과 없음"))
        except Exception as e:
            out.put((name, None, str(e)[:120]))

    def _onion():
        rows, err = _ddg_onion(query, n=n, timeout=timeout)
        if rows:
            return rows
        raise Exception(err or "onion 실패")

    def _clear():
        rows = _ddg(query, n=n, timeout=timeout)
        if rows and not (len(rows) == 1 and "검색 실패" in rows[0].get("snippet", "")):
            return rows
        raise Exception("clearnet 실패")

    def _pub():
        rows, err = _public_searx(query, n=n, timeout=timeout)
        if rows:
            return rows
        raise Exception(err or "public searx 실패")

    threads = []
    for name, fn in (("onion", _onion), ("clearnet", _clear), ("public-searx", _pub)):
        t = threading.Thread(target=_run, args=(name, fn), daemon=True)
        t.start()
        threads.append(t)

    errs = []
    for _ in range(3):
        try:
            name, rows, err = out.get(timeout=timeout + 10)
        except Exception:
            break
        if rows:
            return rows, None
        errs.append("%s: %s" % (name, err))
    return None, ("; ".join(errs) if errs else "모든 경로 실패")


def bench_search(query="코스피", n=3, timeout=45):
    """각 경로의 실제 소요 시간을 재서 표로 보여준다 (추측 대신 측정).

    예)  print(bench_search())
    """
    import time as _t
    rows_out = []

    def _one(label, fn):
        t0 = _t.time()
        try:
            r = fn()
            el = _t.time() - t0
            cnt = len(r) if r else 0
            ok = "OK  " if cnt else "빈결과"
            rows_out.append((label, ok, el, cnt, ""))
        except Exception as e:
            rows_out.append((label, "실패", _t.time() - t0, 0, str(e)[:60]))

    def _o():
        r, e = _ddg_onion(query, n=n, timeout=timeout)
        if not r:
            raise Exception(e or "실패")
        return r

    def _c():
        return _ddg(query, n=n, timeout=timeout)

    def _s():
        r, e = _searxng(query, n=n)
        if not r:
            raise Exception(e or "실패")
        return r

    def _r():
        r, e = _race_search(query, n=n, timeout=timeout)
        if not r:
            raise Exception(e or "실패")
        return r

    _one("DDG onion   (Tor 내부)", _o)
    _one("DDG clearnet(Tor 출구)", _c)
    _one("SearXNG     (로컬)", _s)

    def _p():
        r, e = _public_searx(query, n=n, timeout=timeout)
        if not r:
            raise Exception(e or "실패")
        return r

    _one("공용 SearXNG(Tor중계)", _p)
    _one("병렬 경주   (기본값)", _r)

    lines = ["[검색어] %s" % query, "-" * 52,
             "%-24s %-6s %8s %6s" % ("경로", "상태", "소요(초)", "건수")]
    for label, ok, el, cnt, err in rows_out:
        lines.append("%-24s %-6s %8.1f %6d %s" % (label, ok, el, cnt, err))
    lines.append("-" * 52)
    best = [r for r in rows_out if r[3] > 0]
    if best:
        best.sort(key=lambda x: x[2])
        lines.append("가장 빠른 경로: %s (%.1f초)" % (best[0][0].strip(), best[0][2]))
        lines.append("고정하려면 컨테이너 환경변수 SEARCH_PATH 를 설정하세요")
        lines.append("  (race | onion | clearnet | searxng)")
    else:
        lines.append("모든 경로 실패 — Tor 회로를 확인하세요.")
    return "\n".join(lines)


def web_search(query, n=5, timeout=30):
    """웹 검색 -> [{'title','snippet','url'}, ...]

    기본(race): onion 과 clearnet 을 동시에 쏘고 먼저 오는 것을 사용.
    실패하면 SearXNG -> clearnet 순으로 마저 시도한다.
    SEARCH_PATH 로 특정 경로만 강제할 수 있다.
    """
    errs = []
    if _PATH_MODE == "onion":
        res, e = _ddg_onion(query, n=n)
        if res:
            return res
        errs.append("onion: " + str(e))
    elif _PATH_MODE == "searxng":
        res, e = _searxng(query, n=n)
        if res:
            return res
        errs.append("SearXNG: " + str(e))
    elif _PATH_MODE == "clearnet":
        pass  # 아래 clearnet 로 바로
    else:
        res, e = _race_search(query, n=n)
        if res:
            return res
        if e:
            errs.append("race: " + str(e))
        res, e = _searxng(query, n=n)
        if res:
            return res
        if e:
            errs.append("SearXNG: " + str(e))
        res, e = _public_searx(query, n=n)
        if res:
            return res
        if e:
            errs.append("공용 SearXNG: " + str(e))
    ddg = _ddg(query, n=n, timeout=timeout)
    if ddg and not (len(ddg) == 1 and "검색 실패" in ddg[0].get("snippet", "")):
        return ddg
    if ddg:
        errs.append(ddg[0].get("snippet", "")[:120])
    return [{"title": "검색 실패(모든 경로)", "snippet": " || ".join(errs) or "결과 없음",
             "url": ""}]


def search_summary(query, n=5):
    """검색 결과를 사람이 읽는 형식으로.

    주의: 이 함수의 반환값은 '읽기용 텍스트' 다. 코드로 쪼개서 URL 을 뽑으려 하면
    형식이 어긋나 IndexError 가 난다(실측된 실패 사례). URL 이 필요하면
    web_search() 가 돌려주는 dict 를 쓰고, 보고서면 research() 를 쓴다.
    """
    rows = web_search(query, n=n)
    if not rows:
        return "검색 결과 없음: %s" % query
    lines = ["[검색] %s   (총 %d건)" % (query, len(rows)),
             "※ 이 텍스트를 split 으로 파싱하지 마세요. "
             "URL 목록이 필요하면 web_search(), 보고서면 research() 를 쓰세요."]
    for i, r in enumerate(rows, 1):
        lines.append("")
        lines.append("%d. %s" % (i, r.get("title") or "(제목 없음)"))
        lines.append("   URL: %s" % (r.get("url") or "(없음)"))
        sn = (r.get("snippet") or "").strip()
        if sn:
            lines.append("   요약: %s" % sn[:300])
    return "\n".join(lines)


def search_urls(query, n=5):
    """검색 결과의 URL 만 리스트로. (파싱 없이 바로 쓰라고 만든 함수)

    예)  for u in search_urls('코스피 마감'): print(open_url(u))
    """
    return [r.get("url") for r in web_search(query, n=n) if r.get("url")]


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




# ─────────────────────────────────────────────
#  차단 감지 · 아카이브 우회 (SEARCH_TOOLS_v4)
# ─────────────────────────────────────────────
# 강한 신호: 챌린지 페이지에서만 나타난다 -> 발견 즉시 차단으로 판정
_BLOCK_STRONG = (
    "attention required", "cf-browser-verification", "__cf_chl", "cf_chl_opt",
    "checking your browser", "just a moment",
    "enable javascript and cookies to continue",
    "ddos protection by", "incapsula", "cf-error-details",
    "자동입력 방지",
)
# 주의: hcaptcha/recaptcha 같은 '위젯 이름' 은 정상 페이지(로그인 폼 등)에도 마크업으로
#       존재할 수 있다. 강한신호로 두면 위키백과처럼 멀쩡한 출처를 통째로 버리게 된다.
#       -> 약한신호로 내려 본문 길이와 함께 판단한다.

# 약한 신호: 정상 기사 본문에도 우연히 나올 수 있다 -> 본문이 짧을 때만 차단으로 본다
_BLOCK_WEAK = (
    "access denied", "403 forbidden", "ray id", "request unsuccessful",
    "verify you are human", "g-recaptcha", "hcaptcha", "captcha-delivery",
    "recaptcha", "captcha",
)


def _looks_blocked(raw, text=None):
    """봇 차단/CAPTCHA 페이지인지 판정.

    차단 페이지를 '본문' 으로 넘기면 모델이 그걸 근거로 보고서를 쓴다(조용한 환각).
    반대로 정상 기사를 차단으로 오판하면 멀쩡한 출처를 버린다.
    그래서 신호를 강/약으로 나눈다:
      강한 신호 = 챌린지 페이지에만 나오는 문구 -> 즉시 차단
      약한 신호 = 기사에도 나올 수 있는 문구   -> 본문이 짧을 때만 차단
    """
    low = (raw or "")[:6000].lower()
    for s in _BLOCK_STRONG:
        if s in low:
            return True, s
    body = text if text is not None else _readable(raw or "")
    if len(body) < 400:
        for s in _BLOCK_WEAK:
            if s in low:
                return True, s + " (본문 부족)"
    if len(body) < 220 and ("cloudflare" in low or "captcha" in low):
        return True, "짧은 챌린지 페이지"
    return False, ""


def _wayback(url, timeout=40):
    """Wayback Machine 스냅샷 본문. 원본이 Tor 를 막을 때의 우회로."""
    try:
        api = ("https://archive.org/wayback/available?url="
               + urllib.parse.quote(_safe_url(url), safe=""))
        j = _json.loads(_proxy_get(api, timeout))
        snap = (((j.get("archived_snapshots") or {}).get("closest") or {}))
        if not snap.get("available"):
            return None, "스냅샷 없음"
        surl = snap.get("url", "")
        if surl.startswith("http://"):
            surl = "https://" + surl[7:]
        raw = _proxy_get(surl, timeout)
        body = _readable(raw)
        blocked, _ = _looks_blocked(raw, body)
        if blocked or len(body) < 120:
            return None, "스냅샷 본문 부족"
        stamp = snap.get("timestamp", "")
        head = "(아카이브 사본%s)" % ((" " + stamp[:8]) if stamp else "")
        # 원본과 같은 기준을 적용한다. 아카이브만 느슨하면 얇은 사본이 '성공' 으로
        # 집계되어 실제보다 좋아 보인다(측정 왜곡).
        thin = len(body) < MIN_BODY
        return head + "\n" + body, ("thin" if thin else None)
    except Exception as e:
        return None, str(e)[:110]


# ─────────────────────────────────────────────
#  사이트별 경로 정책 (SITE_POLICY_v1)
#
#  Tor 로 막히는 사이트가 일부 있다. '전부 상용 프록시로' 가 아니라,
#  '막히는 곳만' 직접 연결로 예외 처리하는 편이 익명성 손실이 훨씬 적다.
#
#  DIRECT_DOMAINS 에 넣은 도메인만 Tor 를 우회한다(= 호스트 네트워크로 나감).
#  호스트에 VPN(Mullvad 등)을 켜 두면 그 경로도 실제 IP 는 가려진다.
#
#  환경변수로 지정:
#    SEARCH_DIRECT_DOMAINS=kr.investing.com,finance.yahoo.com
#
#  기본값은 비어 있다 = 전부 Tor. 예외는 사용자가 명시적으로 허용해야 한다.
# ─────────────────────────────────────────────
DIRECT_DOMAINS = tuple(
    d.strip().lower()
    for d in os.environ.get("SEARCH_DIRECT_DOMAINS", "").split(",")
    if d.strip()
)


def _is_direct_domain(url):
    try:
        host = urllib.parse.urlparse(_safe_url(url)).netloc.lower()
    except Exception:
        return False
    host = host.split("@")[-1].split(":")[0]
    for d in DIRECT_DOMAINS:
        if host == d or host.endswith("." + d):
            return True
    return False


def _direct_get(url, timeout=25):
    """Tor 를 우회해 직접 가져온다. 이 도메인에 한해 익명성을 포기한다."""
    req = urllib.request.Request(_safe_url(url), headers={"User-Agent": _UA})
    op = _direct_opener()
    with op.open(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


MIN_BODY = 400   # 이보다 짧으면 '기사 본문' 으로 보지 않는다(메뉴/스켈레톤 페이지)


def _get_body(url, timeout=25, allow_archive=True, archive_timeout=20):
    """본문 가져오기 — 차단되면 아카이브로 우회. (본문, 출처, 오류) 반환.

    타임아웃을 짧게 잡는다. Tor 에서 25초 안에 응답하지 않는 사이트는 대개
    더 기다려도 안 온다(실측: 90초 기다려도 실패). 빨리 포기하고 아카이브로 넘어가는
    편이 전체 소요를 줄인다.
    """
    raw = None
    err = ""
    direct = _is_direct_domain(url)
    try:
        raw = (_direct_get(url, timeout) if direct else _proxy_get(url, timeout))
    except Exception as e:
        err = str(e)[:110]
    thin = None
    if raw is not None:
        body = _readable(raw)
        blocked, why = _looks_blocked(raw, body)
        if blocked:
            err = "봇 차단 감지(%s)" % why
        elif len(body) >= MIN_BODY:
            return body, ("원본(직접·Tor우회)" if direct else "원본"), None
        else:
            thin = body
            err = "본문 %d자 (기사로 보기엔 부족)" % len(body)
    if allow_archive:
        body, aerr = _wayback(url, archive_timeout)
        if body:
            return body, ("아카이브(짧음)" if aerr == "thin" else "아카이브"), None
        err = "%s / 아카이브 실패(%s)" % (err, aerr)
    # 아카이브도 없으면, 짧더라도 있는 것을 돌려주되 '얇음' 을 명시한다
    if thin and len(thin) >= 80:
        return thin, "원본(짧음)", None
    if not direct and DIRECT_DOMAINS:
        err += " / 이 도메인을 SEARCH_DIRECT_DOMAINS 에 추가하면 Tor 우회로 시도합니다"
    return None, None, err


def page_title(raw):
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    return _strip(m.group(1)) if m else ""


def open_url(url, limit=6000, timeout=40):
    """URL 한 개를 열어 제목 + 본문 텍스트를 반환 (서핑용).

    예)  print(open_url('https://www.yna.co.kr/view/AKR...'))
    """
    if not url:
        return "URL 이 비어 있습니다."
    body, src_kind, err = _get_body(url, timeout)
    if body is None:
        return ("열기 실패: %s\n%s\n"
                "-> 이 사이트는 Tor 접속을 차단할 수 있습니다. "
                "추측하지 말고 다른 출처를 찾으세요." % (err, url))
    tag = "" if src_kind == "원본" else "  [%s]" % src_kind
    return "%s%s\n\n%s" % (url, tag, body[:limit])


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
        body, src_kind, err = _get_body(u, timeout)
        if body:
            label = "[본문]" if src_kind == "원본" else "[본문 · %s]" % src_kind
            blocks.append(label + "\n" + body[:chars])
        else:
            blocks.append("[본문 없음] %s — 이 출처는 인용하지 마세요." % err)
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
