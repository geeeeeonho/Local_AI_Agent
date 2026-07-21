# -*- coding: utf-8 -*-
"""엑셀/표 도구 — 외부 패키지 없이 .xlsx / .csv 읽고 쓰기.

excel_write(path, rows, headers=None)  -> .xlsx 생성 (openpyxl 불필요)
csv_write(path, rows, headers=None)    -> .csv 생성
read_table(path)                       -> [[...], ...] (.csv 지원; .xlsx 는 셀 문자열 추출)
"""
from __future__ import annotations
import csv as _csv
import os
import re
import zipfile
from xml.sax.saxutils import escape as _esc


def _col(n):  # 0->A, 26->AA
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def excel_write(path, rows, headers=None):
    """rows: [[셀,...], ...]. headers 주면 첫 행. 순수 stdlib 로 유효한 .xlsx 작성."""
    if not path.lower().endswith(".xlsx"):
        path += ".xlsx"
    data = []
    if headers:
        data.append(list(headers))
    data.extend([list(r) for r in rows])

    sheet_rows = []
    for ri, row in enumerate(data, 1):
        cells = []
        for ci, val in enumerate(row):
            ref = "%s%d" % (_col(ci), ri)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                cells.append('<c r="%s"><v>%s</v></c>' % (ref, val))
            else:
                cells.append('<c r="%s" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>'
                             % (ref, _esc("" if val is None else str(val))))
        sheet_rows.append('<row r="%d">%s</row>' % (ri, "".join(cells)))
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<sheetData>%s</sheetData></worksheet>' % "".join(sheet_rows))
    ctypes = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
              '<Default Extension="xml" ContentType="application/xml"/>'
              '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
              '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
              '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>')
    wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
          '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>')
    wbrels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
              '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
              '</Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ctypes)
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", wbrels)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return os.path.abspath(path)


def csv_write(path, rows, headers=None):
    if not path.lower().endswith(".csv"):
        path += ".csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.writer(f)
        if headers:
            w.writerow(list(headers))
        for r in rows:
            w.writerow(list(r))
    return os.path.abspath(path)


def read_table(path):
    if path.lower().endswith(".csv"):
        with open(path, newline="", encoding="utf-8-sig") as f:
            return [row for row in _csv.reader(f)]
    if path.lower().endswith(".xlsx"):
        with zipfile.ZipFile(path) as z:
            xml = z.read("xl/worksheets/sheet1.xml").decode("utf-8", "ignore")
        cells = re.findall(r'<t[^>]*>(.*?)</t>|<v>(.*?)</v>', xml, re.S)
        vals = [a or b for a, b in cells]
        return [vals]  # 단순 평탄화(값 목록)
    raise ValueError("지원 형식 아님(.csv/.xlsx): %s" % path)
