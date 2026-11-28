"""화면 없이 자막 검토 내역 글만 만든다(tkinter가 없는 환경에서도)."""


def report(result):
    try:
        from apps.shared.subtitle_controller import report_text
    except ImportError:            # tkinter가 없는 환경
        import pytest
        pytest.skip('report text needs the desktop package (tkinter)')
    return report_text(result)
