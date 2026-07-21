# -*- coding: utf-8 -*-
"""보고서 작성 도구 — 제목/섹션을 받아 Markdown 또는 HTML 보고서 생성.

report_write(path, title, sections)  sections: [(heading, body), ...]
"""
from __future__ import annotations
import html as _html
import os
import time


def report_write(path, title, sections, fmt=None):
    fmt = fmt or ("html" if path.lower().endswith((".html", ".htm")) else "md")
    stamp = time.strftime("%Y-%m-%d %H:%M")
    if fmt == "html":
        body = ["<h1>%s</h1>" % _html.escape(str(title)),
                "<p><em>%s</em></p>" % stamp]
        for h, b in sections:
            body.append("<h2>%s</h2>" % _html.escape(str(h)))
            body.append("<p>%s</p>" % _html.escape(str(b)).replace("\n", "<br>"))
        doc = ("<!doctype html><meta charset='utf-8'><title>%s</title>"
               "<body style='font-family:Segoe UI,sans-serif;max-width:760px;margin:40px auto;line-height:1.6'>%s</body>"
               % (_html.escape(str(title)), "".join(body)))
        if not path.lower().endswith((".html", ".htm")):
            path += ".html"
    else:
        lines = ["# %s" % title, "", "_%s_" % stamp, ""]
        for h, b in sections:
            lines += ["## %s" % h, "", str(b), ""]
        doc = "\n".join(lines)
        if not path.lower().endswith(".md"):
            path += ".md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return os.path.abspath(path)
