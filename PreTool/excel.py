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
from html import unescape as _unesc  # [XLSX_READ_v1]
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
    path = str(path)  # [FLEX_INPUT_v1] Path 객체 허용
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
    path = str(path)  # [FLEX_INPUT_v1]
    if not path.lower().endswith(".csv"):
        path += ".csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.writer(f)
        if headers:
            w.writerow(list(headers))
        for r in rows:
            w.writerow(list(r))
    return os.path.abspath(path)


# [XLSX_READ_v1]
_X_ROW = re.compile(r'<row\b[^>]*>(.*?)</row>', re.S)
_X_CELL = re.compile(r'<c\b([^>]*)>(.*?)</c>|<c\b([^>]*)/>', re.S)
_X_T = re.compile(r'<t\b[^>]*>(.*?)</t>', re.S)
_X_V = re.compile(r'<v\b[^>]*>(.*?)</v>', re.S)
_X_REF = re.compile(r'\br="([A-Z]+)\d+"')
_X_TYP = re.compile(r'\bt="([^"]+)"')


def _x_colidx(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _x_sheet(z):
    if "xl/worksheets/sheet1.xml" in z.namelist():
        return "xl/worksheets/sheet1.xml"
    for n in sorted(z.namelist()):
        if n.startswith("xl/worksheets/") and n.endswith(".xml"):
            return n
    raise ValueError("워크시트를 찾을 수 없습니다")


def _x_shared(z):
    """xl/sharedStrings.xml 해석. 엑셀이 만든 파일은 셀에 문자열 '인덱스' 만 들어 있다."""
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    raw = z.read("xl/sharedStrings.xml").decode("utf-8", "ignore")
    return [_unesc("".join(_X_T.findall(si)))
            for si in re.findall(r'<si\b[^>]*>(.*?)</si', raw, re.S)]


def read_table(path):
    """.csv/.tsv/.xlsx 를 [[셀,...], ...] 로 읽는다. 값은 항상 문자열.

    엑셀이 만든 .xlsx 는 sharedStrings 를 쓰므로 그것까지 해석해야
    숫자 인덱스가 데이터로 둔갑하지 않는다(조용한 오염 방지).
    """
    path = str(path)
    low = path.lower()
    if low.endswith((".csv", ".tsv")):
        delim = "\t" if low.endswith(".tsv") else ","
        with open(path, newline="", encoding="utf-8-sig") as f:
            return [row for row in _csv.reader(f, delimiter=delim)]
    if not low.endswith((".xlsx", ".xlsm")):
        raise ValueError("지원 형식 아님(.csv/.tsv/.xlsx): %s" % path)
    with zipfile.ZipFile(path) as z:
        shared = _x_shared(z)
        xml = z.read(_x_sheet(z)).decode("utf-8", "ignore")
    table = []
    for rowxml in _X_ROW.findall(xml):
        row = []
        for m in _X_CELL.finditer(rowxml):
            attrs = m.group(1) if m.group(1) is not None else (m.group(3) or "")
            inner = m.group(2) or ""
            rm = _X_REF.search(attrs)
            ci = _x_colidx(rm.group(1)) if rm else len(row)
            tm = _X_TYP.search(attrs)
            ctype = tm.group(1) if tm else ""
            if ctype == "inlineStr":
                val = _unesc("".join(_X_T.findall(inner)))
            elif ctype == "s":
                vs = _X_V.findall(inner)
                try:
                    val = shared[int(vs[0])] if vs else ""
                except (ValueError, IndexError):
                    val = ""
            else:
                vs = _X_V.findall(inner)
                val = _unesc(vs[0]) if vs else ""
            while len(row) < ci:
                row.append("")
            if len(row) == ci:
                row.append(val)
            else:
                row[ci] = val
        table.append(row)
    width = max((len(r) for r in table), default=0)
    for r in table:
        while len(r) < width:
            r.append("")
    return table
