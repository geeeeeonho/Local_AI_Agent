"""The records LocalAI itself writes are encrypted where they are written.

Agent traces (prompts, commands, results), session logs and the account's
documents go through ``core.vault`` at the point of writing, so nothing has
to remember to encrypt afterwards. Setup converts what older versions left.
"""
import json

import pytest

from core import vault
from test_vault import Key


@pytest.fixture
def account(tmp_path, monkeypatch):
    root = tmp_path / 'users' / 'Tester'
    (root / 'logs').mkdir(parents=True)
    (root / 'user_data').mkdir()
    import project_paths
    monkeypatch.setattr(project_paths, 'account_dir', lambda: root)
    monkeypatch.setattr(project_paths, 'logs_dir', lambda: root / 'logs')
    monkeypatch.setattr(project_paths, 'user_data_dir', lambda: root / 'user_data')
    with vault.using(Key()):
        yield root


def test_an_agent_trace_never_holds_a_prompt_in_plaintext(account):
    from launcher.agent.agent_trace import AgentTrace
    trace = AgentTrace(mode='host', model='m', network_mode='block', profile_name='p',
                       workspace=account, detailed=True)
    trace.record('turn', details={'prompt': 'my bank password hint'}, detailed=True)
    trace.close()
    raw = trace.path.read_text(encoding='utf-8')
    assert 'bank' not in raw and raw.startswith(vault.LINE_PREFIX)
    rows = [json.loads(line) for line in vault.iter_lines(trace.path)]
    assert rows[0]['details']['prompt'] == 'my bank password hint'


def test_account_documents_are_encrypted_and_shared_ones_are_not(account, tmp_path):
    from core.persistence import JsonStore
    private = JsonStore(account / 'user_data' / 'projects' / 'registry.json')
    shared = JsonStore(tmp_path / 'models' / '.localai' / 'registry.json')
    private.update(lambda data: {'schema_version': 1, 'projects': ['Thesis']})
    shared.update(lambda data: {'roles': {}})
    assert b'Thesis' not in private.path.read_bytes()
    assert private.read()['projects'] == ['Thesis']
    assert json.loads(shared.path.read_text(encoding='utf-8')) == {'roles': {}}


def test_folder_policy_and_user_settings_round_trip_encrypted(account):
    from launcher.agent import folder_policy
    from launcher.core import user_data
    assert folder_policy.save({'allowed': ['D:/Private'], 'denied': []})
    stored = account / 'user_data' / 'settings' / 'folder_policy.json'
    assert b'Private' not in stored.read_bytes()
    assert folder_policy.load()['allowed'] == ['D:/Private']
    path = account / 'user_data' / 'settings' / 'user_config.json'
    assert user_data.save_json(path, {'language': 'ko'})
    assert user_data.load_json(path) == {'language': 'ko'}
    assert b'language' not in path.read_bytes()


def test_session_logs_are_encrypted_line_by_line(account):
    from launcher.core import lifelog
    stream = vault.open_log(account / 'logs' / 'launcher_1.log', 'w')
    lifelog.log_session(stream, 'INFO', '사용자 질문: 비밀')
    stream.close()
    raw = (account / 'logs' / 'launcher_1.log').read_text(encoding='utf-8')
    assert '비밀' not in raw
    assert '비밀' in ''.join(vault.iter_lines(account / 'logs' / 'launcher_1.log'))


def test_setup_converts_what_older_versions_left(account):
    from installer.core import filesystem
    logs = account / 'logs'
    (logs / 'launcher_20260101_000000.log').write_text('old secret line\n', encoding='utf-8')
    (logs / 'agent_trace_1.jsonl').write_text('{"prompt": "old"}\n', encoding='utf-8')
    (logs / 'ollama_run.log').write_text('[GIN] 200 POST /api/chat\n', encoding='utf-8')
    settings = account / 'user_data' / 'settings'
    settings.mkdir()
    (settings / 'localai.json').write_text('{"schema_version": 1}', encoding='utf-8')
    assert filesystem.protect_existing_records(account) == 3
    assert 'secret' not in (logs / 'launcher_20260101_000000.log').read_text(encoding='utf-8')
    assert (logs / 'ollama_run.log').read_text(encoding='utf-8').startswith('[GIN]'), \
        'Ollama keeps appending plaintext to its own log; it is not ours to rewrite'
    assert vault.read_text(settings / 'localai.json') == '{"schema_version": 1}'
    assert filesystem.protect_existing_records(account) == 0, 'idempotent'


def test_the_records_tool_reads_them_back_for_their_owner(account, capsys, tmp_path):
    from tools import records
    with vault.open_log(account / 'logs' / 'launcher_2.log', 'w') as stream:
        stream.write('visible to me\n')
    assert records.main(['--records', 'show', 'launcher_2.log']) == 0
    assert 'visible to me' in capsys.readouterr().out
    out = tmp_path / 'export'
    assert records.main(['export', str(out)]) == 0
    assert (out / 'launcher_2.log').read_text(encoding='utf-8') == 'visible to me\n'
    records.main(['list'])
    assert '암호화됨' in capsys.readouterr().out


def test_another_account_running_the_tool_gets_nothing(account, capsys):
    from tools import records
    with vault.open_log(account / 'logs' / 'launcher_3.log', 'w') as stream:
        stream.write('private\n')
    with vault.using(Key(b'administrator')):
        records.main(['show', 'launcher_3.log'])
    assert 'private' not in capsys.readouterr().out
