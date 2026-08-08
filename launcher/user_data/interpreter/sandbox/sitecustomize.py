# -*- coding: utf-8 -*-
"""sitecustomize — PreTool 함수를 모든 파이썬 코드블록에서 import 없이 사용 가능하게 주입.

PYTHONPATH(/home/agent/.agent_state)에 위치하면 python 시작 시 자동 실행된다.
=> 모델이 web_search(...) / report_write(...) 를 import 없이 바로 호출해도 동작.
"""
try:
    import builtins as _b
    import PreTool as _pt
    for _n in getattr(_pt, "__all__", []):
        if _n == "catalog":
            continue
        _fn = getattr(_pt, _n, None)
        if _fn is not None and not hasattr(_b, _n):
            setattr(_b, _n, _fn)
    _b.PreTool = _pt
except Exception as _e:  # [SITECUSTOM_DIAG_v1]
    # 조용히 삼키면 모델은 web_search() 에서 NameError 만 보고 원인을 알 수 없다.
    # 평소에는 침묵하되, PRETOOL_DEBUG=1 이면 이유를 stderr 로 알린다.
    import os as _os
    import sys as _sys
    if _os.environ.get("PRETOOL_DEBUG"):
        _sys.stderr.write("[PreTool] 전역 주입 실패: %s: %s\n"
                          % (type(_e).__name__, _e))
