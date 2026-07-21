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
except Exception:
    pass
