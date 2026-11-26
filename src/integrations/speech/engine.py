"""whisper.cpp · ffmpeg 실행: 설치 위치 확인, 오디오 추출, 음성 인식(진행률·취소).

공용 위치(관리자만 쓰기)에 설치된 실행 파일만 쓴다.

  <environment>\\speech\\whisper\\cuda\\whisper-cli.exe   NVIDIA GPU 빌드(있으면 먼저)
  <environment>\\speech\\whisper\\cpu\\whisper-cli.exe    CPU 빌드
  <environment>\\speech\\ffmpeg\\ffmpeg.exe, ffprobe.exe
  <environment>\\speech\\vad\\ggml-silero-v6.2.0.bin      음성 구간 감지(VAD)
  <models>\\speech\\ggml-*.bin                             음성 인식 모델

whisper-cli는 명령줄 인자를 시스템 코드 페이지로 받으므로, 경로는 모두 ASCII 작업 폴더의
사본을 쓰고 인자는 UTF-8 응답 파일(@파일)로 넘긴다(한글 파일 이름·용어 힌트도 안전).
개발·시험용으로만 LOCAL_AI_WHISPER_CLI · LOCAL_AI_FFMPEG 로 실행 파일을 바꿀 수 있다.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import project_paths
from core.tools import speech

VAD_FILE = 'ggml-silero-v6.2.0.bin'
VARIANTS = ('cuda', 'cpu')
_EXE = '.exe' if os.name == 'nt' else ''
_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0
# '작은 목소리 우선' 음성 구간 감지(whisper-cli). 실측(FLEURS 4개 언어 8개 시나리오): 작은 목소리·건너뛴
# 발화가 있는 영상은 크게 좋아졌지만(en hard CER 0.194 → 0.034) 깨끗한 한중일 녹음은 나빠져
# (ja clean 0.030 → 0.095) 기본값은 whisper.cpp 그대로 두고 사용자가 고르게 한다.
SENSITIVE_VAD = ('-vt', '0.35', '-vspd', '150', '-vsd', '300', '-vp', '250')
_PROGRESS = re.compile(r'progress\s*=\s*(\d+)%')
# 여러 파일을 한 번에 인식할 때 다음 파일로 넘어가는 줄('main: processing 'a.wav' (…)').
_PROCESSING = re.compile(r": processing '")
# VAD가 무음을 잘라 낸 구간 대응표. whisper-cli의 JSON은 구간 시각만 원래 오디오 기준으로 되돌리고
# 토큰 시각은 잘라 낸 시간 그대로 내보내므로, 이 로그로 토큰 시각을 직접 되돌린다(core.tools.speech).
_VAD_MAP = re.compile(r'vad_segment_info: orig_start: ([\d.]+), orig_end: ([\d.]+), '
                      r'vad_start: ([\d.]+), vad_end: ([\d.]+)')


class EngineMissing(RuntimeError):
    pass


def probe_executable(exe, *args, expect):
    """Run a lightweight executable/DLL check; no model load or network access."""
    try:
        result = subprocess.run([str(exe), *args], capture_output=True, timeout=30,
                                creationflags=_NO_WINDOW, stdin=subprocess.DEVNULL, cwd=str(Path(exe).parent))
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    output = (result.stdout + result.stderr).decode('utf-8', 'replace')
    if result.returncode == 0 and expect in output:
        return True, ''
    return False, 'exit %s: %s' % (result.returncode, output[-500:].strip() or 'no output')


@dataclass(frozen=True)
class Status:
    builds: tuple = ()              # 사용할 수 있는 빌드('cuda', 'cpu') — 앞쪽 우선
    ffmpeg: bool = False
    vad: bool = False
    models: tuple = ()              # 설치된 모델 키(정확도 높은 순)
    version: str = ''
    issues: tuple = ()
    damaged_models: tuple = ()

    @property
    def ready(self):
        return bool(self.builds and self.models)


@dataclass
class Transcript:
    data: dict
    build: str
    seconds: float
    log: list = field(default_factory=list)


class SpeechEngine:
    def __init__(self, root=None, models=None):
        self.root = Path(root) if root is not None else project_paths.speech_engine_dir()
        self.models_dir = Path(models) if models is not None else project_paths.speech_model_dir()
        self._process = None
        self._lock = threading.Lock()

    # ── 위치 ──
    def cli(self, variant):
        override = os.environ.get('LOCAL_AI_WHISPER_CLI')
        if override and variant == 'cpu':
            return Path(override)
        return self.root / 'whisper' / variant / ('whisper-cli' + _EXE)

    def ffmpeg(self, name='ffmpeg'):
        """ffmpeg 또는 같은 폴더의 ffprobe."""
        override = os.environ.get('LOCAL_AI_FFMPEG')
        if override:
            base = Path(override)
            return base if name == 'ffmpeg' else base.with_name(name + base.suffix)
        return self.root / 'ffmpeg' / (name + _EXE)

    def vad_model(self):
        return self.root / 'vad' / VAD_FILE

    def model_path(self, key):
        return self.models_dir / speech.model(key).file

    def manifest(self):
        try:
            data = json.loads((self.root / 'install.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        # A syntactically valid but damaged/old manifest must be repairable.
        for name in ('whisper', 'ffmpeg', 'vad'):
            if not isinstance(data.get(name), dict):
                data.pop(name, None)
        whisper = data.get('whisper', {})
        variants = whisper.get('variants')
        whisper['variants'] = ({key: value for key, value in variants.items()
                                if key in VARIANTS and isinstance(value, dict)}
                               if isinstance(variants, dict) else {})
        return data

    def model_available(self, key):
        path = self.model_path(key)
        try:
            if not path.is_file():
                return False
            # Explicit external development/test CLI may use fixture models.
            if os.environ.get('LOCAL_AI_WHISPER_CLI'):
                return True
            size = path.stat().st_size
            nominal = speech.model(key).size_mib * 1048576
            if not nominal * 0.90 <= size <= nominal * 1.15:
                return False
            with path.open('rb') as stream:
                return stream.read(4) == b'lmgg'  # little-endian GGML magic
        except OSError:
            return False

    def vad_available(self):
        path = self.vad_model()
        if not path.is_file():
            return False
        if os.environ.get('LOCAL_AI_WHISPER_CLI'):
            return True  # explicit external development/test CLI
        from .install import VAD_SHA256, VAD_SIZE
        from .download import _hash_existing
        try:
            return (path.stat().st_size == VAD_SIZE
                    and _hash_existing(path, 'sha256').hexdigest() == VAD_SHA256)
        except OSError:
            return False

    def ffmpeg_available(self, *, verify=False):
        exe = self.ffmpeg()
        if not exe.is_file():
            return False
        return not verify or probe_executable(exe, '-version', expect='ffmpeg version')[0]

    def status(self, *, verify_runtime=False):
        issues, builds, models, damaged = [], [], [], []
        for variant in VARIANTS:
            cli = self.cli(variant)
            if not cli.is_file():
                continue
            if verify_runtime and not (variant == 'cpu' and os.environ.get('LOCAL_AI_WHISPER_CLI')):
                ok, detail = probe_executable(cli, '-h', expect='--vad')
                if not ok:
                    issues.append('Whisper %s 복구 필요: %s' % (variant.upper(), detail))
                    continue
            builds.append(variant)
        for item in speech.MODELS:
            if self.model_available(item.key):
                models.append(item.key)
            elif self.model_path(item.key).is_file():
                damaged.append(item.key)
        ffmpeg = self.ffmpeg().is_file() and self.ffmpeg('ffprobe').is_file()
        if verify_runtime and ffmpeg and not os.environ.get('LOCAL_AI_FFMPEG'):
            for name in ('ffmpeg', 'ffprobe'):
                ok, detail = probe_executable(self.ffmpeg(name), '-version', expect=name + ' version')
                if not ok:
                    issues.append('%s 복구 필요: %s' % (name, detail))
                    ffmpeg = False
        if self.ffmpeg().is_file() != self.ffmpeg('ffprobe').is_file():
            issues.append('FFmpeg/FFprobe 일부 파일 누락')
        vad = self.vad_available() if verify_runtime else self.vad_model().is_file()
        if verify_runtime and self.vad_model().is_file() and not vad:
            issues.append('VAD 복구 필요')
        manifest = self.manifest().get('whisper') or {}
        if builds and verify_runtime and not os.environ.get('LOCAL_AI_WHISPER_CLI'):
            from runtime_versions import WHISPER_CPP_VERSION, WHISPER_CPP_BUILD_TAG
            if (manifest.get('version') != WHISPER_CPP_VERSION or
                    manifest.get('build_tag') != WHISPER_CPP_BUILD_TAG):
                issues.append('Whisper 설치 기록 확인/복구 필요')
        return Status(tuple(builds), ffmpeg, vad, tuple(models), str(manifest.get('version') or ''),
                      tuple(issues), tuple(damaged))

    # ── 실행 공통 ──
    def abort(self):
        with self._lock:
            process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass

    def _run(self, command, *, on_line=None, cancelled=None, cwd=None, stdout_lines=False):
        """명령을 실행하며 stderr(또는 stdout) 줄을 on_line으로 넘긴다. 마지막 40줄을 돌려준다."""
        tail = []
        process = subprocess.Popen(
            [str(part) for part in command], cwd=cwd, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
        with self._lock:
            self._process = process

        def pump(stream, keep, report):
            for raw in iter(stream.readline, b''):
                line = raw.decode('utf-8', 'replace').rstrip()
                if keep:
                    tail.append(line)
                    del tail[:-40]
                if report and on_line and line:
                    try:
                        on_line(line)
                    except Exception:
                        pass
            stream.close()

        # stderr: 진행률·오류(마지막 40줄 보관). stdout: 필요할 때만 줄 단위로 넘기고 나머지는 버린다.
        readers = [threading.Thread(target=pump, args=(process.stderr, True, True), daemon=True),
                   threading.Thread(target=pump, args=(process.stdout, False, stdout_lines), daemon=True)]
        for reader in readers:
            reader.start()
        try:
            while process.poll() is None:
                if cancelled and cancelled():
                    self.abort()
                    raise InterruptedError('Cancelled')
                time.sleep(0.2)
        finally:
            for reader in readers:
                reader.join(timeout=5)
            with self._lock:
                self._process = None
        if cancelled and cancelled():
            # abort()로 끝난 프로세스를 실패로 보고 다른 빌드로 다시 시도하지 않게 한다.
            raise InterruptedError('Cancelled')
        return process.returncode, tail

    # ── 오디오 ──
    def duration_ms(self, media):
        """ffprobe로 재생 시간(ms). 알 수 없으면 None."""
        probe = self.ffmpeg('ffprobe')
        if not probe.is_file():
            return None
        try:
            result = subprocess.run(
                [str(probe), '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', str(media)],
                capture_output=True, timeout=60, creationflags=_NO_WINDOW, stdin=subprocess.DEVNULL)
            if result.returncode != 0:
                return None
            return int(float(result.stdout.decode('ascii', 'ignore').strip()) * 1000)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return None

    def has_audio(self, media):
        probe = self.ffmpeg('ffprobe')
        if not probe.is_file():
            return None
        try:
            result = subprocess.run(
                [str(probe), '-v', 'error', '-select_streams', 'a', '-show_entries',
                 'stream=index', '-of', 'csv=p=0', str(media)],
                capture_output=True, timeout=60, creationflags=_NO_WINDOW, stdin=subprocess.DEVNULL)
            return bool(result.stdout.strip()) if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    def extract_audio(self, media, wav, *, duration_ms=None, progress=None, cancelled=None):
        """미디어의 첫 오디오 트랙을 16kHz 모노 PCM WAV로 뽑는다(Whisper 입력 형식)."""
        ffmpeg = self.ffmpeg()
        if not ffmpeg.is_file():
            raise EngineMissing('ffmpeg is not installed')
        wav = Path(wav)
        wav.parent.mkdir(parents=True, exist_ok=True)
        partial = wav.with_name(wav.stem + '.part.wav')

        def on_line(line):
            if progress and duration_ms and line.startswith('out_time_us='):
                value = line.split('=', 1)[1]
                if value.isdigit():
                    progress(min(1.0, int(value) / 1000 / duration_ms))

        code, tail = self._run(
            [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-i', media,
             '-map', '0:a:0', '-vn', '-sn', '-dn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le',
             '-progress', 'pipe:1', '-nostats', partial],
            on_line=on_line, cancelled=cancelled, stdout_lines=True)
        if code != 0 or not partial.is_file():
            partial.unlink(missing_ok=True)
            detail = ' / '.join(line for line in tail[-3:] if line)
            raise RuntimeError('Could not read audio from the file (ffmpeg %s): %s' % (code, detail))
        os.replace(partial, wav)
        return wav

    # ── 음성 인식 ──
    def transcribe(self, audio, model_key, **options):
        """audio(ASCII 경로의 WAV/MP3/FLAC)를 인식해 Transcript(상세 JSON 등)를 돌려준다."""
        return self.transcribe_many([audio], model_key, **options)[0]

    def transcribe_many(self, audios, model_key, *, work, language='auto', quality='best', vad=True,
                        prompt='', gpu=True, threads=None, progress=None, cancelled=None, on_text=None,
                        sensitive=False):
        """여러 오디오를 whisper-cli 한 번에 인식한다(모델을 한 번만 올린다). 순서대로 Transcript 목록.
        언어 자동 감지는 파일마다 따로 한다. progress는 전체 진행률(0~1)."""
        audios = list(audios)
        if not audios:
            return []
        status = self.status()
        if not status.builds:
            raise EngineMissing('whisper.cpp is not installed')
        model_file = self.model_path(model_key)
        if not self.model_available(model_key):
            raise EngineMissing('Speech model is not installed or needs repair: ' + model_key)
        preset = speech.QUALITY.get(quality, speech.QUALITY['best'])
        work = Path(work)
        work.mkdir(parents=True, exist_ok=True)
        builds = [build for build in status.builds if gpu or build == 'cpu'] or ['cpu']
        if 'cpu' not in builds and 'cpu' in status.builds:
            builds.append('cpu')
        errors = []
        use_vad = vad and self.vad_available()
        count = len(audios)
        for build in builds:
            if not self.cli(build).is_file():
                continue
            outs = ([work / ('result-' + build)] if count == 1
                    else [work / ('result-%s-%d' % (build, index)) for index in range(count)])
            for out in outs:
                out.with_suffix('.json').unlink(missing_ok=True)
            args = ['-m', model_file]
            for audio, out in zip(audios, outs):
                args += ['-f', audio, '-of', out]
            args += ['-l', speech.whisper_code(language), '-ojf', '-pp', '-sns',
                     '-bs', str(preset['beam']), '-bo', str(preset['best_of']),
                     '-t', str(threads or _threads())]
            if preset['dtw']:
                args += ['-dtw', speech.model(model_key).dtw, '-nfa']
            if use_vad:
                args += ['--vad', '-vm', self.vad_model()] + (list(SENSITIVE_VAD) if sensitive else [])
            if prompt.strip():
                args += ['--prompt', ' '.join(prompt.split())[:600]]
            if build == 'cpu' or not gpu:
                args += ['-ng']
            response = work / ('args-' + build + '.txt')
            # 한 줄에 인자 하나. 줄바꿈 변환 없이 UTF-8 바이트로 쓴다.
            response.write_bytes(('\n'.join(str(arg).replace('\n', ' ') for arg in args) + '\n')
                                 .encode('utf-8'))

            mappings = [[] for _ in audios]
            current = [-1 if count > 1 else 0]

            def on_line(line, mappings=mappings, current=current):
                if count > 1 and _PROCESSING.search(line):
                    current[0] = min(count - 1, current[0] + 1)
                index = max(0, current[0])
                found = _PROGRESS.search(line)
                if found and progress:
                    progress((index + int(found.group(1)) / 100.0) / count)
                elif on_text and line.startswith('[') and '-->' in line:
                    on_text(line.split(']', 1)[-1].strip())
                vad_line = _VAD_MAP.search(line)
                if vad_line:
                    mappings[index].append([int(round(float(value) * 1000)) for value in vad_line.groups()])

            started = time.monotonic()
            try:
                code, tail = self._run([self.cli(build), '@' + str(response)], on_line=on_line,
                                       cancelled=cancelled, cwd=str(work), stdout_lines=True)
            except InterruptedError:
                raise
            except OSError as exc:
                errors.append('%s could not start: %s' % (build, exc))
                if progress:
                    progress(0.0)
                continue
            results = [out.with_suffix('.json') for out in outs]
            if code == 0 and all(result.is_file() for result in results):
                transcripts = []
                for result, mapping in zip(results, mappings):
                    raw = result.read_bytes().decode('utf-8', 'replace')
                    try:
                        data = json.loads(raw, strict=False)
                    except ValueError as exc:
                        errors.append('%s: unreadable result (%s)' % (build, exc))
                        break
                    if mapping:
                        data[speech.VAD_MAP_KEY] = mapping  # [원래 시작, 원래 끝, 처리 시작, 처리 끝] ms
                    transcripts.append(data)
                else:
                    seconds = time.monotonic() - started
                    return [Transcript(data, build, seconds / count, tail) for data in transcripts]
                continue
            errors.append('%s exit %s: %s' % (build, code, ' / '.join(line for line in tail[-4:] if line)))
            if progress:
                progress(0.0)
        raise RuntimeError('Speech recognition failed: ' + ' | '.join(errors))


def _threads():
    count = os.cpu_count() or 4
    return max(1, min(8, count - 1))
