"""자막 도구의 음성 런타임 설치·갱신과 음성 인식 모델 받기·지우기.

* whisper.cpp — 고정 태그(runtime_versions.WHISPER_CPP_TAG)의 공식 Windows x64 빌드.
  CPU 빌드는 항상, NVIDIA GPU가 있으면 CUDA 빌드도 받는다. 각 ZIP은 GitHub가 릴리스
  자산마다 기록한 SHA-256(digest)과 대조한다. digest가 없으면 설치하지 않는다.
* ffmpeg — 고정 빌드 태그(FFMPEG_BUILD_TAG)의 LGPL Windows x64 빌드. 같은 릴리스의
  checksums.sha256과 GitHub digest 둘 다와 대조한다.
* VAD(Silero) — 고정 커밋의 파일을 이 코드에 적은 SHA-256과 대조한다.
* 음성 인식 모델 — Hugging Face 파일을 whisper.cpp(고정 버전) 표의 SHA-1과 대조한다.

압축은 경로를 검사하며 임시 폴더에 풀고, 실행 확인까지 통과한 뒤에만 기존 폴더와 바꾼다.
실패해도 기존 설치와 LocalAI의 다른 기능(Chat·Agent·번역)에는 영향이 없다.
"""
from __future__ import annotations

import io
import json
import os
import platform
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

from core.tools import speech
from runtime_versions import FFMPEG_BUILD_TAG, WHISPER_CPP_COMMIT, WHISPER_CPP_TAG, WHISPER_CPP_VERSION

from . import download
from .engine import VAD_FILE, SpeechEngine

WHISPER_RELEASE = 'https://api.github.com/repos/ggml-org/whisper.cpp/releases/tags/' + WHISPER_CPP_TAG
FFMPEG_RELEASE = 'https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/tags/' + FFMPEG_BUILD_TAG
VAD_URL = ('https://raw.githubusercontent.com/ggml-org/whisper.cpp/' + WHISPER_CPP_COMMIT +
           '/models/for-tests-silero-v6.2.0-ggml.bin')
VAD_SHA256 = '2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987'
VAD_SIZE = 885098

ASSETS = {'cpu': 'whisper-bin-x64.zip', 'cuda': 'whisper-bin-win-cuda-12.4.0-x64.zip'}
LIMITS = {'cpu': 200 * 1024 * 1024, 'cuda': 1500 * 1024 * 1024, 'ffmpeg': 400 * 1024 * 1024}
# 릴리스 분기 빌드(ffmpeg-n8.0.1-…-win64-lgpl-8.0.zip)를 고르고, 없으면 master 빌드
FFMPEG_ASSET = re.compile(r'^ffmpeg-n(\d+(?:\.\d+)*)-.*-win64-lgpl-\d+(?:\.\d+)*\.zip$')
FFMPEG_MASTER = re.compile(r'^ffmpeg-N-\d+-g[0-9a-f]+-win64-lgpl\.zip$')
_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0


def _say(log, text):
    if log is not None:
        log(text)


def _asset_digest(asset):
    value = str(asset.get('digest') or '')
    if not value.startswith('sha256:') or len(value) != 71:
        raise ValueError('GitHub did not record a SHA-256 digest for ' + str(asset.get('name')))
    return value.split(':', 1)[1].lower()


def _assets(release_url):
    release = download.get_json(release_url)
    return {str(asset.get('name')): asset for asset in release.get('assets') or ()}


def _safe_extract(payload, target):
    """ZIP을 target에 푼다. 절대 경로·'..'·링크가 있으면 거부한다."""
    target = Path(target)
    with zipfile.ZipFile(io.BytesIO(payload) if isinstance(payload, bytes) else payload) as archive:
        for info in archive.infolist():
            name = info.filename.replace('\\', '/')
            parts = [part for part in name.split('/') if part]
            if name.startswith('/') or ':' in name or '..' in parts:
                raise ValueError('Unsafe path in archive: ' + info.filename)
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Link in archive: ' + info.filename)
        archive.extractall(target)
    return target


def _find(root, name):
    found = [path for path in Path(root).rglob(name) if path.is_file()]
    if len(found) != 1:
        raise ValueError('Expected one %s in the archive, found %d' % (name, len(found)))
    return found[0]


def _replace_dir(staged, final):
    """검증을 마친 staged 폴더를 final로 바꾼다(기존 폴더는 다 바꾼 뒤에 지운다)."""
    final = Path(final)
    old = final.with_name(final.name + '.old')
    shutil.rmtree(old, ignore_errors=True)
    if final.exists():
        os.replace(final, old)
    try:
        os.replace(staged, final)
    except OSError:
        if old.exists() and not final.exists():
            os.replace(old, final)
        raise
    shutil.rmtree(old, ignore_errors=True)


def _runs(exe, *args, expect):
    """실행 파일이 이 PC에서 실제로 시작되고 기대한 글을 출력하는지(DLL 누락·차단 확인)."""
    try:
        result = subprocess.run([str(exe), *args], capture_output=True, timeout=60,
                                creationflags=_NO_WINDOW, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return expect in (result.stdout + result.stderr).decode('utf-8', 'replace')


def _staging(root):
    """압축을 풀 빈 임시 폴더. 받은 압축 파일은 이어받기를 위해 '.downloads'에 따로 둔다."""
    folder = Path(root) / '.staging'
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _archive(root, name):
    folder = Path(root) / '.downloads'
    folder.mkdir(parents=True, exist_ok=True)
    return folder / name


def _install_whisper(engine, variant, assets, log, cancelled):
    asset = assets.get(ASSETS[variant])
    if asset is None:
        raise ValueError('Release %s has no %s' % (WHISPER_CPP_TAG, ASSETS[variant]))
    staging = _staging(engine.root)
    archive = _archive(engine.root, ASSETS[variant])
    _say(log, '자막 엔진: whisper.cpp %s (%s) 받는 중…' % (WHISPER_CPP_VERSION, variant.upper()))
    download.fetch(asset['browser_download_url'], archive, algorithm='sha256',
                   expected=_asset_digest(asset), limit=LIMITS[variant], cancelled=cancelled,
                   progress=_percent(log, 'whisper.cpp ' + variant.upper()))
    with open(archive, 'rb') as stream:
        _safe_extract(stream, staging / 'unpacked')
    cli = _find(staging / 'unpacked', 'whisper-cli.exe')
    folder = cli.parent
    if not _runs(cli, '-h', expect='--vad'):
        raise ValueError('whisper-cli did not start (%s build)' % variant)
    final = engine.root / 'whisper' / variant
    final.parent.mkdir(parents=True, exist_ok=True)
    _replace_dir(folder, final)
    shutil.rmtree(staging, ignore_errors=True)
    archive.unlink(missing_ok=True)
    return {'asset': ASSETS[variant], 'sha256': _asset_digest(asset)}


def _ffmpeg_asset(assets):
    released = []
    for name in assets:
        match = FFMPEG_ASSET.match(name)
        if match:
            released.append((tuple(int(part) for part in match.group(1).split('.')), name))
    if released:
        return assets[max(released)[1]]
    master = [name for name in assets if FFMPEG_MASTER.match(name)]
    if len(master) == 1:
        return assets[master[0]]
    raise ValueError('No LGPL Windows x64 build in ' + FFMPEG_BUILD_TAG)


def _install_ffmpeg(engine, log, cancelled):
    assets = _assets(FFMPEG_RELEASE)
    asset = _ffmpeg_asset(assets)
    name = asset['name']
    digest = _asset_digest(asset)
    sums = assets.get('checksums.sha256')
    if sums is None:
        raise ValueError('ffmpeg release has no checksums.sha256')
    listed = download.get_bytes(sums['browser_download_url'], limit=256 * 1024).decode('utf-8', 'replace')
    line = next((row for row in listed.splitlines() if row.strip().endswith(name)), '')
    if line.split()[:1] != [digest]:
        raise ValueError('ffmpeg checksum file does not match GitHub digest')
    staging = _staging(engine.root)
    archive = _archive(engine.root, name)
    _say(log, '자막 엔진: ffmpeg(LGPL) 받는 중…')
    download.fetch(asset['browser_download_url'], archive, algorithm='sha256', expected=digest,
                   limit=LIMITS['ffmpeg'], cancelled=cancelled, progress=_percent(log, 'ffmpeg'))
    with open(archive, 'rb') as stream:
        _safe_extract(stream, staging / 'unpacked')
    ready = staging / 'ffmpeg'
    ready.mkdir()
    for exe in ('ffmpeg.exe', 'ffprobe.exe'):
        shutil.copy2(_find(staging / 'unpacked', exe), ready / exe)
    license_files = list((staging / 'unpacked').rglob('LICENSE*'))
    if license_files:
        shutil.copy2(license_files[0], ready / 'LICENSE.txt')
    if not _runs(ready / 'ffmpeg.exe', '-version', expect='ffmpeg version'):
        raise ValueError('ffmpeg did not start')
    _replace_dir(ready, engine.root / 'ffmpeg')
    shutil.rmtree(staging, ignore_errors=True)
    archive.unlink(missing_ok=True)
    return {'tag': FFMPEG_BUILD_TAG, 'asset': name, 'sha256': digest}


def _install_vad(engine, log, cancelled):
    _say(log, '자막 엔진: 음성 구간 감지(VAD) 모델 확인')
    target = engine.vad_model()
    download.fetch(VAD_URL, target, algorithm='sha256', expected=VAD_SHA256,
                   limit=VAD_SIZE + 1024, cancelled=cancelled)
    return {'file': VAD_FILE, 'sha256': VAD_SHA256}


def _percent(log, label):
    state = {'last': -10}

    def report(done, total):
        if not total or log is None:
            return
        value = int(done * 100 / total)
        if value >= state['last'] + 10 or value == 100 and state['last'] != 100:
            state['last'] = value
            log('  %s %d%% (%.0f / %.0f MB)' % (label, value, done / 1048576, total / 1048576))
    return report


def supported():
    """이 PC에서 자막 엔진을 설치할 수 있는지. (가능 여부, 이유)"""
    if os.name != 'nt':
        return False, '자막 엔진은 Windows에서만 설치합니다.'
    machine = platform.machine().lower()
    if machine not in ('amd64', 'x86_64'):
        return False, '자막 엔진은 x64 Windows용 공식 빌드만 지원합니다(현재: %s).' % machine
    return True, ''


def has_nvidia_gpu():
    try:
        from core.gpu_memory import detect_gpu_memory
        return detect_gpu_memory() is not None
    except Exception:
        return False


def install(root=None, *, log=None, cancelled=None, gpu=None, force=False):
    """엔진(whisper.cpp CPU[+CUDA]·ffmpeg·VAD)을 설치하거나 갱신한다. 성공하면 True.
    이미 같은 고정 버전이 설치되어 있으면 받지 않는다. CUDA 빌드 실패는 CPU만으로 계속한다."""
    ok, reason = supported()
    if not ok:
        _say(log, reason)
        return False
    engine = SpeechEngine(root)
    engine.root.mkdir(parents=True, exist_ok=True)
    manifest = engine.manifest()
    whisper = dict(manifest.get('whisper') or {})
    variants = dict(whisper.get('variants') or {}) if whisper.get('version') == WHISPER_CPP_VERSION else {}
    wanted = ['cpu'] + (['cuda'] if (has_nvidia_gpu() if gpu is None else gpu) else [])
    success = True
    try:
        pending = [v for v in wanted if force or v not in variants or not engine.cli(v).is_file()]
        assets = _assets(WHISPER_RELEASE) if pending else {}
        for variant in pending:
            try:
                variants[variant] = _install_whisper(engine, variant, assets, log, cancelled)
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                if variant == 'cpu':
                    raise
                _say(log, '자막 엔진: GPU(CUDA) 빌드를 설치하지 못해 CPU로 실행합니다: ' + str(exc))
        manifest['whisper'] = {'version': WHISPER_CPP_VERSION, 'variants': variants}
        ffmpeg = manifest.get('ffmpeg') or {}
        if force or ffmpeg.get('tag') != FFMPEG_BUILD_TAG or not engine.ffmpeg().is_file():
            try:
                manifest['ffmpeg'] = _install_ffmpeg(engine, log, cancelled)
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                success = False
                _say(log, '자막 엔진: ffmpeg 설치 실패(영상은 처리할 수 없고 WAV·MP3·FLAC만 됩니다): '
                     + str(exc))
        manifest['vad'] = _install_vad(engine, log, cancelled)
    except download.DownloadCancelled:
        _say(log, '자막 엔진 설치를 중단했습니다. 다시 시작하면 이어서 받습니다.')
        return False
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        _say(log, '자막 엔진 설치 실패(다른 기능에는 영향 없음): ' + str(exc))
        return False
    finally:
        shutil.rmtree(engine.root / '.staging', ignore_errors=True)
        if manifest:
            try:
                (engine.root / 'install.json').write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
            except OSError:
                pass
    _say(log, '자막 엔진 준비 완료: whisper.cpp %s (%s)%s' % (
        WHISPER_CPP_VERSION, ' + '.join(v.upper() for v in variants),
        ' · ffmpeg' if engine.ffmpeg().is_file() else ''))
    return success


def install_model(key, models_dir=None, *, progress=None, cancelled=None):
    """음성 인식 모델 하나를 받는다(SHA-1 검증, 이어받기). 받은 경로를 돌려준다."""
    item = speech.model(key)
    engine = SpeechEngine(models=models_dir)
    target = engine.model_path(key)
    return download.fetch(speech.MODEL_URL + item.file, target, algorithm='sha1', expected=item.sha1,
                          limit=int(item.size_mib * 1.15 * 1048576), progress=progress,
                          cancelled=cancelled)


def remove_model(key, models_dir=None):
    engine = SpeechEngine(models=models_dir)
    target = engine.model_path(key)
    for path in (target, target.with_name(target.name + '.part')):
        path.unlink(missing_ok=True)
