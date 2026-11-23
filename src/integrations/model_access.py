"""Who may install or remove models in the machine-shared LocalAI store.

The shared library (``<runtime root>\\models``) is read by every allowed
account and changed only by a LocalAI administrator - the account that
installed LocalAI, or one it made administrator. The Windows ACL is the real
boundary (``integrations.windows.program_security``); this check answers the
same question *before* a download starts, so an ordinary account is told why
instead of watching a pull fail half-way.

Administrators are what Windows vouches for (``windows.trusted_policy``), not
whatever ``machine.json`` lists. A store outside the shared root (an explicit
``LLM_MODEL_DIR``) belongs to whoever configured it and is left to its ACL.
"""
from __future__ import annotations

import time
from pathlib import Path

#: Re-reading group membership spawns PowerShell; a management screen asks
#: often, membership changes rarely (and needs UAC when it does).
_CACHE_SECONDS = 60.0
_cache: dict = {}

DENIED = ('모델 설치·삭제는 LocalAI 관리자(처음 설치한 계정 또는 관리자로 지정된 계정)만 '
          '할 수 있습니다. 이 계정은 설치된 모델을 사용할 수 있습니다.')
UNVERIFIED = ('LocalAI 관리자 정보를 Windows에서 확인하지 못해 모델 변경을 막았습니다. '
              '관리자 계정에서 [설치 / 복구]를 실행하세요.')


def _same(a, b) -> bool:
    from core import ollama_paths
    try:
        return ollama_paths._same_windows_path(Path(a), Path(b))
    except Exception:
        return str(a) == str(b)


def is_shared_store(model_dir) -> bool:
    import project_paths
    from core import ollama_paths, runtime_root
    canonical = Path(project_paths.runtime_dir()) / runtime_root.MODELS
    return _same(model_dir, canonical) or ollama_paths.models_dir_is_shared(path=model_dir)


def _decide(model_dir) -> dict:
    from integrations.windows import acl
    if not acl.on_windows():
        return {'allowed': True, 'admin': None, 'reason': ''}
    if not is_shared_store(model_dir):
        return {'allowed': True, 'admin': None, 'reason': ''}
    import project_paths
    from integrations.windows import machine as windows
    if acl.is_elevated():
        return {'allowed': True, 'admin': True, 'reason': ''}
    sid = acl.current_user_sid()
    try:
        policy = windows.load_trusted_policy(project_paths.runtime_dir())
    except Exception:
        policy = None
    if policy is None or not sid:
        return {'allowed': False, 'admin': False, 'reason': UNVERIFIED}
    if policy.is_admin(sid, windows.token_group_sids()):
        return {'allowed': True, 'admin': True, 'reason': ''}
    return {'allowed': False, 'admin': False, 'reason': DENIED}


def management_access(model_dir, *, refresh=False) -> dict:
    """``{'allowed': bool, 'admin': bool|None, 'reason': str}`` for this account."""
    key = str(model_dir)
    now = time.monotonic()
    hit = _cache.get(key)
    if not refresh and hit and now - hit[0] < _CACHE_SECONDS:
        return dict(hit[1])
    answer = _decide(model_dir)
    _cache[key] = (now, answer)
    return dict(answer)


def require_management(model_dir) -> None:
    """Raise ``PermissionError`` unless this account may change the store."""
    answer = management_access(model_dir, refresh=True)
    if not answer['allowed']:
        raise PermissionError(answer['reason'])


def clear_cache() -> None:
    _cache.clear()


__all__ = ['management_access', 'require_management', 'is_shared_store',
           'clear_cache', 'DENIED', 'UNVERIFIED']
