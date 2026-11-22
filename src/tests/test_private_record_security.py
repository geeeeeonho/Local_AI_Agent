"""기록 저장 실패-차단 및 공용 서버 로그 미기록의 계약 검사."""
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_windows_private_record_requires_dpapi(monkeypatch, tmp_path):
    from core import vault
    monkeypatch.setattr(vault, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setattr(vault, 'is_private_path', lambda _path: True)
    monkeypatch.setattr(vault, 'protector', lambda: None)
    with pytest.raises(vault.VaultError, match='DPAPI'):
        vault.require_private_record_encryption(tmp_path / 'personal.json')
    with pytest.raises(vault.VaultError, match='DPAPI'):
        vault.should_protect(tmp_path / 'personal.json')


def test_non_windows_dev_mode_keeps_existing_plaintext_behavior(monkeypatch, tmp_path):
    from core import vault
    monkeypatch.setattr(vault, 'os', SimpleNamespace(name='posix'))
    monkeypatch.setattr(vault, 'is_private_path', lambda _path: True)
    monkeypatch.setattr(vault, 'protector', lambda: None)
    vault.require_private_record_encryption(tmp_path / 'dev.json')
    assert not vault.should_protect(tmp_path / 'dev.json')


def test_shared_ollama_output_is_not_persisted():
    from launcher.services.ollama import OllamaService
    assert OllamaService._open_log(object()) is None


def test_private_calendar_path_composition(tmp_path):
    from services.tools.calendar import CalendarService
    data = tmp_path / 'users' / 'Alice' / 'user_data'
    service = CalendarService(data / 'tools' / 'calendar' / 'items.json')
    assert service.path == data / 'tools' / 'calendar' / 'items.json'
    assert service.list_items() == []
