"""launcher.agent 패키지 초기화.

레거시 에이전트 설정 경로는 ``user_data/settings`` 로 연결해
과거 코드가 별도 설정 파일을 만들지 않도록 한다.
"""
try:
    from launcher import settings_store as _settings_store
    _settings_store.ensure_legacy_bridges()
except Exception:
    # 패키지 import 자체가 설정 링크 문제로 실패해서는 안 된다.
    pass
