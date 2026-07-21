# -*- coding: utf-8 -*-
"""PreTool — 모델의 처리 부담을 줄이는 사전 구현 도구 모음 (순수 stdlib, 유연 입력).

from PreTool import web_search, run_tests, check_syntax, excel_write, report_write, ...
전체 도구는 PreTool.catalog() 로 확인.
"""
from .search import web_search, fetch_text, search_summary, net_diag
from .excel import excel_write, csv_write, read_table
from .report import report_write
from .files import move, copy, list_files, organize_by_ext
from .dev import (check_syntax, run_tests, run_python, lint, outline, diff, complexity)
from .data import calc, json_pretty, json_query, summarize_text, word_stats

__all__ = [
    # 검색/웹
    "web_search", "search_summary", "fetch_text", "net_diag",
    # 표/엑셀
    "excel_write", "csv_write", "read_table",
    # 문서
    "report_write",
    # 파일
    "move", "copy", "list_files", "organize_by_ext",
    # 개발/코드
    "check_syntax", "run_tests", "run_python", "lint", "outline", "diff", "complexity",
    # 데이터/텍스트
    "calc", "json_pretty", "json_query", "summarize_text", "word_stats",
    "catalog",
]


def catalog():
    return {
        "web_search(query, n=5)": "웹 검색 → [{title,snippet,url}] (SearXNG 우선)",
        "net_diag()": "네트워크 경로 진단(무엇이 도달 가능한지)",
        "search_summary(query)": "검색 결과를 읽기 좋은 텍스트로",
        "fetch_text(url)": "URL 본문 텍스트(태그 제거)",
        "excel_write(path, rows, headers=None)": ".xlsx 생성(외부 패키지 불필요)",
        "csv_write / read_table": ".csv 쓰기 / .csv·.xlsx 읽기",
        "report_write(path, title, sections)": "Markdown/HTML 보고서",
        "move/copy/list_files/organize_by_ext": "파일 이동·복사·정리",
        "check_syntax(code, lang='python')": "문법/완성 체크 (python·json 정밀, 그 외 괄호 균형)",
        "run_tests(code, cases, func=None)": "모의 테스트: 케이스로 함수 실행→통과/실패 보고",
        "run_python(code, timeout=15)": "코드 격리 실행(subprocess)→stdout/stderr/rc",
        "lint(code)": "가벼운 정적 점검(미사용 import·긴 줄·TODO)",
        "outline(code)": "함수/클래스 시그니처+줄번호",
        "diff(a, b)": "unified diff(문자열/파일)",
        "complexity(code)": "라인·함수·분기·근사 복잡도",
        "calc(expr)": "안전 산술 계산(eval 미사용)",
        "json_pretty / json_query(data, 'a.b.0')": "JSON 정렬 / 경로 추출",
        "summarize_text(text, n=3) / word_stats": "추출식 요약 / 텍스트 통계",
    }
