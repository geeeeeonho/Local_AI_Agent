"""Speech installer regression checks; small local fixtures, no network/GPU."""
import hashlib
import io
import json
import urllib.error

import pytest

from core.tools import speech
from integrations.speech import download, install
from integrations.speech.engine import SpeechEngine


def test_actual_release_contract():
    from runtime_versions import WHISPER_CPP_TAG, WHISPER_CPP_BUILD_TAG
    assert WHISPER_CPP_TAG == 'v1.9.5'
    assert WHISPER_CPP_BUILD_TAG == 'b5454'
    assert install.WHISPER_RELEASE.endswith('/b5454')
    assert install.ASSETS == {'cpu': 'whisper-bin-x64.zip', 'cuda': 'whisper-bin-win-cuda-12.4.0-x64.zip'}
    assert 'repos/FFmpeg-Builds/FFmpeg-Builds/' in install.FFMPEG_RELEASE


def _mock_install(monkeypatch, tmp_path, *, bad=()):
    monkeypatch.setattr(install, 'supported', lambda: (True, ''))
    monkeypatch.setattr(install, '_assets', lambda url, **kw: {})
    calls = []
    engine = SpeechEngine(tmp_path)
    def whisper(eng, variant, assets, log, cancelled):
        calls.append(variant)
        if variant in bad:
            raise ValueError(variant + ' failed')
        exe = eng.cli(variant)
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(b'valid')
        return {'asset': install.ASSETS[variant], 'sha256': 'a' * 64}
    def ffmpeg(eng, log, cancelled):
        calls.append('ffmpeg')
        for name in ('ffmpeg', 'ffprobe'):
            exe = eng.ffmpeg(name)
            exe.parent.mkdir(parents=True, exist_ok=True)
            exe.write_bytes(b'valid')
        return {'tag': install.FFMPEG_BUILD_TAG}
    def vad(eng, log, cancelled):
        calls.append('vad')
        return {'file': 'vad'}
    monkeypatch.setattr(install, '_install_whisper', whisper)
    monkeypatch.setattr(install, '_install_ffmpeg', ffmpeg)
    monkeypatch.setattr(install, '_install_vad', vad)
    monkeypatch.setattr(install, '_runs', lambda exe, *args, **kwargs:
                        exe.is_file() and exe.read_bytes() == b'valid')
    return engine, calls


def test_selective_repair_and_no_model_download(monkeypatch, tmp_path):
    engine, calls = _mock_install(monkeypatch, tmp_path)
    assert install.install(tmp_path, gpu=True)
    assert calls == ['cpu', 'cuda', 'ffmpeg', 'vad']
    assert engine.manifest()['whisper']['build_tag'] == 'b5454'
    calls.clear()
    assert install.install(tmp_path, gpu=True)
    assert calls == ['vad']
    engine.cli('cpu').write_bytes(b'broken')
    engine.ffmpeg('ffprobe').unlink()
    calls.clear()
    assert install.install(tmp_path, gpu=True)
    assert calls == ['cpu', 'ffmpeg', 'vad']
    assert not list(tmp_path.rglob('ggml-*.bin'))


def test_cpu_failure_does_not_block_other_components(monkeypatch, tmp_path):
    engine, calls = _mock_install(monkeypatch, tmp_path, bad=('cpu',))
    with pytest.raises(install.InstallFailed, match='Whisper CPU'):
        install.install(tmp_path, gpu=True, raise_on_error=True)
    assert calls == ['cpu', 'cuda', 'ffmpeg', 'vad']
    assert 'cpu' not in engine.manifest()['whisper']['variants']
    assert 'cuda' in engine.manifest()['whisper']['variants']


def test_cuda_is_optional_and_cancel_is_not_failure(monkeypatch, tmp_path):
    engine, calls = _mock_install(monkeypatch, tmp_path, bad=('cuda',))
    assert install.install(tmp_path, gpu=True)
    assert 'cpu' in engine.manifest()['whisper']['variants']
    with pytest.raises(download.DownloadCancelled):
        install.install(tmp_path, gpu=True, cancelled=lambda: True, raise_on_error=True)
    assert not install.install(tmp_path, gpu=True, cancelled=lambda: True)


def test_missing_dll_probe_and_damaged_model_status(monkeypatch, tmp_path):
    from integrations.speech import engine as module
    eng = SpeechEngine(tmp_path / 'engine', tmp_path / 'models')
    cli = eng.cli('cpu')
    cli.parent.mkdir(parents=True)
    cli.write_bytes(b'broken')
    model = eng.model_path('small')
    model.parent.mkdir()
    model.write_bytes(b'truncated')
    monkeypatch.delenv('LOCAL_AI_WHISPER_CLI', raising=False)
    monkeypatch.setattr(module, 'probe_executable', lambda *a, **k: (False, 'DLL missing'))
    status = eng.status(verify_runtime=True)
    assert status.builds == () and status.models == ()
    assert status.damaged_models == ('small',)
    assert 'DLL missing' in status.issues[0]


class Response(io.BytesIO):
    def __init__(self, data, status, **headers):
        super().__init__(data)
        self.status = status
        self.headers = headers


def test_bad_resume_restarts_from_zero(monkeypatch, tmp_path):
    payload = b'abcdef'
    target = tmp_path / 'weights'
    part = tmp_path / 'weights.part'
    part.write_bytes(payload[:2])
    responses = iter([Response(b'cdef', 206, **{'Content-Range': 'bytes 1-4/6', 'Content-Length': '4'}),
                      Response(payload, 200, **{'Content-Length': '6'})])
    monkeypatch.setattr(download.urllib.request, 'urlopen', lambda *a, **k: next(responses))
    monkeypatch.setattr(download.time, 'sleep', lambda _: None)
    assert download.fetch('https://example.com/model', target, algorithm='sha1',
                          expected=hashlib.sha1(payload).hexdigest(), limit=10).read_bytes() == payload
    assert not part.exists()


def test_network_failure_resumes_and_does_not_overwrite_existing(monkeypatch, tmp_path):
    payload = b'abcdef'
    target = tmp_path / 'weights'
    target.write_bytes(b'old')
    responses = iter([Response(b'ab', 200, **{'Content-Length': '6'}),
                      Response(b'cdef', 206, **{'Content-Range': 'bytes 2-5/6', 'Content-Length': '4'})])
    def open_response(*a, **kw):
        assert target.read_bytes() == b'old'
        return next(responses)
    monkeypatch.setattr(download.urllib.request, 'urlopen', open_response)
    monkeypatch.setattr(download.time, 'sleep', lambda _: None)
    assert download.fetch('https://example.com/model', target, algorithm='sha1',
                          expected=hashlib.sha1(payload).hexdigest(), limit=10).read_bytes() == payload


def test_complete_partial_is_promoted_offline(monkeypatch, tmp_path):
    data = b'abcdef'
    target = tmp_path / 'weights'
    target.with_name('weights.part').write_bytes(data)
    monkeypatch.setattr(download.urllib.request, 'urlopen', lambda *a, **k: pytest.fail('unexpected network'))
    assert download.fetch('https://example.com/model', target, algorithm='sha1',
                          expected=hashlib.sha1(data).hexdigest(), limit=10).read_bytes() == data


def test_exclusive_lock_blocks_duplicate_mutation(tmp_path):
    path = tmp_path / 'lock'
    with download.exclusive_lock(path):
        with pytest.raises(OSError, match='설치 또는 복구 중'):
            with download.exclusive_lock(path):
                pytest.fail('concurrent mutation allowed')
    with download.exclusive_lock(path):
        pass


def test_corrupt_manifest_can_be_repaired(monkeypatch, tmp_path):
    engine, calls = _mock_install(monkeypatch, tmp_path)
    tmp_path.joinpath('install.json').write_text('{"whisper": {"variants": "bad"}, "ffmpeg": []}',
                                                encoding='utf-8')
    assert install.install(tmp_path, gpu=False)
    assert calls == ['cpu', 'ffmpeg', 'vad']
    assert engine.manifest()['whisper']['variants']['cpu']['asset'] == install.ASSETS['cpu']


def test_cancel_before_metadata_network(monkeypatch):
    monkeypatch.setattr(download.urllib.request, 'urlopen', lambda *a, **kw: pytest.fail('unexpected network'))
    with pytest.raises(download.DownloadCancelled):
        download.get_json('https://example.com/release', cancelled=lambda: True)


def test_failed_ffprobe_is_not_no_audio(monkeypatch, tmp_path):
    from integrations.speech import engine as module
    eng = SpeechEngine(tmp_path, tmp_path / 'models')
    exe = eng.ffmpeg('ffprobe')
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b'broken')
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **kw:
                        type('Result', (), {'returncode': 1, 'stdout': b'', 'stderr': b'error'})())
    assert eng.has_audio(tmp_path / 'media.mp4') is None


def test_corrupt_vad_is_not_used(monkeypatch, tmp_path):
    eng = SpeechEngine(tmp_path, tmp_path / 'models')
    monkeypatch.delenv('LOCAL_AI_WHISPER_CLI', raising=False)
    vad = eng.vad_model()
    vad.parent.mkdir(parents=True)
    vad.write_bytes(b'broken')
    assert not eng.vad_available()
    assert not eng.status(verify_runtime=True).vad
