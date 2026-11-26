"""자막 만들기: 영상·음성 → (음성 인식) → 자막 문법에 맞는 SRT·WebVTT → (선택) 번역 자막.

흐름
  1. ffmpeg로 첫 오디오 트랙을 16kHz 모노 WAV로 뽑는다(영상이 아니고 ffmpeg가 없으면 원본 사본).
  2. whisper.cpp로 인식한다(GPU 빌드 → 실패 시 CPU). 결과는 개인 작업 폴더에 보관해, 번역만
     다시 하거나 형식만 바꿀 때 다시 인식하지 않는다.
  3. 반복·환각·소리 표기를 정리하고, 단어 시각으로 큐를 만든다(core.tools.subtitles 규칙).
  4. 원본 옆에 원본과 같은 이름 '이름.srt'로 쓴다(재생기가 자동으로 불러온다). 원본과 기존 파일은
     덮어쓰지 않는다. 여러 파일·폴더는 옆에 자막이 이미 있는 파일을 건너뛴다.
  5. 번역을 함께 고르면, 큐마다 한 줄로 합친 사본을 기존 번역 도구(TranslationService)로 번역한 뒤
     번역 언어의 줄 길이 규칙으로 다시 나눠 '이름.<번역 언어>.srt'로 쓴다(원어 자막과 이름이 겹치지 않게).

모델·엔진 설치와 삭제는 공용 모델 저장소와 같은 규칙으로 LocalAI 관리자만 할 수 있다.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
import wave
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from core.tools import asr_review, speech, subtitles
from integrations.speech.engine import EngineMissing, SpeechEngine
from services.tools.languages import LANGUAGES, detect_language
from services.tools.translation import natural_key

AUTO = ('auto', '자동 감지', '')
CACHE_DAYS = 14
CACHE_ENTRIES = 30
MAX_FILES = 500


@dataclass(frozen=True)
class Options:
    model: str
    language: str = 'auto'          # 화면 언어 이름(한국어·日本語 …) 또는 'auto'
    formats: tuple = ('srt',)
    quality: str = 'best'
    vad: bool = True
    keep_sounds: bool = False
    prompt: str = ''
    max_chars: int | None = None
    max_lines: int | None = None
    gpu: bool = True
    sensitive_vad: bool = False     # 작은 목소리 우선(누락 줄이기). 깨끗한 녹음은 오히려 나빠질 수 있다.


@dataclass(frozen=True)
class Translate:
    target: str                     # 화면 언어 이름
    model: str                      # Ollama 모델
    style: str = 'natural'          # 정보 생략 없이(줄 길이는 자막 규칙이 다시 나눈다)
    glossary: str = ''
    precise: bool = False
    keep_failed: bool = True
    # True: 번역 자막을 원본 이름(영상.srt)으로, 원어 자막은 영상.<원어>.srt로(재생기가 번역 자막을 바로 불러옴).
    # False: 원어 자막이 영상.srt, 번역 자막은 영상.<번역 언어>.srt.
    main_name: bool = True


@dataclass(frozen=True)
class Result:
    source: Path
    outputs: tuple
    language: str                   # Whisper 언어 코드(ko, ja …)
    language_label: str
    cues: tuple
    text: str
    review: tuple = ()              # ((큐 번호, 이유), …)
    removed: tuple = ()             # ((시작 ms, 글, 이유), …)
    build: str = ''
    seconds: float = 0.0
    duration_ms: int | None = None
    reused: bool = False            # 보관한 인식 결과를 다시 썼는지
    decisions: tuple = ()           # 다시 인식한 구간의 판단 기록(asr_review.Decision)
    names: tuple = ()               # 비슷한 이름 후보 ((이름, 횟수, 이름, 횟수), …) — 통일하지 않음
    review_note: str = ''
    translated: object = None       # services.tools.translation.Result
    translated_outputs: tuple = ()
    translated_text: str = ''
    translation_skipped: str = ''
    translation_error: str = ''     # 번역만 실패(원어 자막은 만들었음). 다시 실행하면 번역만 다시 한다.


@dataclass(frozen=True)
class Batch:
    results: tuple = ()             # ((파일, Result), …)
    failed: tuple = ()              # ((파일, 오류), …)
    skipped: tuple = ()             # ((파일, 이미 있는 자막), …) — 다시 인식하지 않음


def language_label(code, text=''):
    """Whisper 언어 코드 → 화면 언어 이름. 중국어는 글자로 간체·번체를 가른다. 없으면 코드."""
    code = speech.whisper_code(code)
    if code == 'zh':
        name = detect_language(text) if text else ''
        return '繁體中文' if name == 'Traditional Chinese' else '简体中文'
    found = next((item for item in LANGUAGES if item.code.split('-')[0] == code), None)
    return found.label if found else code


def language_code(label):
    """화면 언어 이름 → 파일 접미사·규칙 코드(zh-Hant 등). 자동 감지면 'auto'."""
    if label in AUTO:
        return 'auto'
    found = next((item for item in LANGUAGES if item.label == label or item.name == label), None)
    if found is None:
        raise ValueError('Unsupported language: ' + str(label))
    return found.code


def numbered(path):
    """이미 있으면 '이름 (2).srt'처럼 번호를 붙인 새 경로."""
    path = Path(path)
    candidate, number = path, 2
    while candidate.exists() and number < 1000:
        candidate = path.with_name('%s (%d)%s' % (path.stem, number, path.suffix))
        number += 1
    return candidate


# 재생기가 영상과 함께 불러오는 자막 확장자(이미 자막이 있는지 볼 때)
SUBTITLE_SUFFIXES = ('.srt', '.vtt', '.ass', '.ssa', '.sub', '.smi')


def original_path(media, fmt, folder=None):
    """원어 자막: 원본과 같은 이름(영상.mp4 → 영상.srt). 재생기가 자동으로 불러온다."""
    media = Path(media)
    name = media.stem + subtitles.FORMATS[fmt][0]
    return numbered((Path(folder) / name) if folder is not None else media.with_name(name))


def existing_subtitles(media):
    """원본 옆에 이미 있는 자막: 영상.srt, 영상.ko.srt, 영상.en.vtt, 영상.ass 등."""
    media = Path(media)
    found = []
    for path in media.parent.glob(glob_escape(media.stem) + '*'):
        if path.suffix.lower() not in SUBTITLE_SUFFIXES or not path.is_file():
            continue
        middle = path.name[len(media.stem):-len(path.suffix)]
        if middle == '' or (middle.startswith('.') and 0 < len(middle) <= 12 and ' ' not in middle):
            found.append(path)
    return sorted(found)


def glob_escape(text):
    return ''.join('[%s]' % char if char in '[]*?' else char for char in text)


def output_path(media, code, fmt, folder=None):
    """원본 옆(또는 folder 안)의 '이름.<언어>.srt'. 이미 있으면 번호를 붙인다."""
    media = Path(media)
    name = '%s.%s%s' % (media.stem, code, subtitles.FORMATS[fmt][0])
    return numbered((Path(folder) / name) if folder is not None else media.with_name(name))


def _format_of(path):
    return next(fmt for fmt, (suffix, _) in subtitles.FORMATS.items() if Path(path).suffix.lower() == suffix)


def language_label_from(answer):
    """번역 결과(Result)에 기록된 번역 언어의 화면 이름."""
    return answer.revision['target'] if getattr(answer, 'revision', None) else '한국어'


def scan(folder):
    """폴더(하위 포함)의 영상·음성 파일. 숨김 항목·바로가기는 건너뛰고 사람이 읽는 순서로."""
    folder = Path(folder)
    found = []
    for root, dirs, names in os.walk(folder):
        here = Path(root)
        dirs[:] = sorted(name for name in dirs if not name.startswith('.') and not (here / name).is_symlink())
        for name in names:
            path = here / name
            if not name.startswith('.') and not path.is_symlink() and path.suffix.lower() in speech.MEDIA:
                found.append(path)
        if len(found) > MAX_FILES:
            raise ValueError('Too many media files in the folder (maximum %d)' % MAX_FILES)
    return sorted(found, key=lambda path: natural_key(path.relative_to(folder)))


def _write_new(path, text):
    """새 파일로만 쓴다(같은 이름이 생겼으면 실패). 반쯤 쓴 파일이 남지 않게 임시 이름 → 이동."""
    path = Path(path)
    temporary = path.with_name('.%s.%d.tmp' % (path.name, os.getpid()))
    temporary.write_text(text, encoding='utf-8-sig', newline='')
    try:
        if path.exists():
            raise FileExistsError('Subtitle file already exists: ' + str(path))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _language_name(code):
    """'ko' → 'Korean'(번역 도구의 언어 이름). 모르면 ''."""
    base = str(code or '').split('-')[0]
    found = next((item for item in LANGUAGES if item.code == code), None) or \
        next((item for item in LANGUAGES if item.code.split('-')[0] == base), None)
    return found.name if found else ''


def _segment_dict(segment):
    return {'start': segment.start, 'end': segment.end, 'text': segment.text, 'prob': segment.prob,
            'words': [[word.start, word.end, word.text, word.prob] for word in segment.words]}


def _segments_from(items):
    return [speech.Segment(int(item['start']), int(item['end']), str(item['text']),
                           tuple(speech.Word(int(a), int(b), str(t), float(p)) for a, b, t, p in item['words']),
                           float(item['prob'])) for item in items]


def _decision_dict(decision):
    return {'start': decision.range.start, 'end': decision.range.end, 'reason': decision.range.reason,
            'original': decision.original, 'candidate': decision.candidate,
            'accepted': decision.accepted, 'why': decision.why}


def _decision_from(item):
    return asr_review.Decision(asr_review.Range(int(item['start']), int(item['end']), str(item['reason'])),
                               str(item['original']), str(item['candidate']), bool(item['accepted']),
                               str(item['why']))


class SubtitleService:
    def __init__(self, translator, *, work_dir, store_dir, engine=None, access=None):
        self.translator = translator
        self.engine = engine or SpeechEngine()
        self.work_dir = Path(work_dir)
        self.store_dir = Path(store_dir)
        self._access = access
        self._abort = threading.Event()

    # ── 상태·관리 ──
    def status(self):
        return self.engine.status(verify_runtime=True)

    def management(self, refresh=False):
        """{'allowed', 'admin', 'reason'}: 엔진·모델 설치/삭제 권한(공용 모델 저장소와 같은 규칙)."""
        if self._access is not None:
            return dict(self._access(refresh))
        from integrations import model_access
        return model_access.management_access(self.store_dir, refresh=refresh)

    def _require_management(self):
        answer = self.management(refresh=True)
        if not answer.get('allowed'):
            from integrations import model_access
            raise PermissionError(answer.get('reason') or model_access.DENIED)

    @staticmethod
    def supported():
        from integrations.speech import install
        return install.supported()

    def install_engine(self, *, log=None, cancelled=None):
        self._require_management()
        from integrations.speech import install
        return install.install(self.engine.root, log=log, cancelled=cancelled, raise_on_error=True)

    def install_model(self, key, *, progress=None, cancelled=None):
        self._require_management()
        from integrations.speech import install
        return install.install_model(key, self.engine.models_dir, progress=progress, cancelled=cancelled)

    def remove_model(self, key):
        self._require_management()
        from integrations.speech import install
        install.remove_model(key, self.engine.models_dir)

    def recommend_model(self, installed, last=''):
        """지난번 모델 → 설치된 모델 중 가장 정확한 모델."""
        installed = tuple(installed)
        if last in installed:
            return last
        return next((item.key for item in speech.MODELS if item.key in installed), '')

    def media_info(self, path):
        """(재생 시간 ms 또는 None, 오디오 트랙 여부 또는 None)."""
        return self.engine.duration_ms(path), self.engine.has_audio(path)

    def abort(self):
        self._abort.set()
        self.engine.abort()
        if hasattr(self.translator, 'abort'):
            self.translator.abort()

    # ── 작업 폴더(개인) ──
    def _key(self, path, options):
        info = Path(path).stat()
        raw = json.dumps([str(Path(path).resolve()), info.st_size, info.st_mtime_ns, options.model,
                          speech.whisper_code(language_code(options.language)), options.quality,
                          options.vad, ' '.join(options.prompt.split())]
                         + (['sensitive'] if options.sensitive_vad else []), ensure_ascii=False)
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]

    def _prune(self):
        if not self.work_dir.is_dir():
            return
        entries = sorted((item for item in self.work_dir.iterdir() if item.is_dir()),
                         key=lambda item: item.stat().st_mtime, reverse=True)
        limit = time.time() - CACHE_DAYS * 86400
        for index, item in enumerate(entries):
            if index >= CACHE_ENTRIES or item.stat().st_mtime < limit:
                shutil.rmtree(item, ignore_errors=True)

    def _audio(self, media, work, duration, report, cancelled):
        suffix = media.suffix.lower()
        if self.engine.ffmpeg_available(verify=True):
            return self.engine.extract_audio(media, work / 'audio.wav', duration_ms=duration,
                                             progress=lambda f: report('audio', f, ''), cancelled=cancelled)
        if suffix in speech.NATIVE_AUDIO:
            # whisper.cpp가 직접 읽는 형식. 경로 문자 문제를 피하려고 ASCII 작업 폴더로 복사한다.
            target = work / ('input' + suffix)
            shutil.copyfile(media, target)
            return target
        raise EngineMissing('ffmpeg is not installed; only WAV, MP3 and FLAC can be read')

    def _recognize(self, media, options, work, duration, report, cancelled, on_text):
        """(최초 인식 JSON, 빌드, 걸린 초, 보관본 재사용 여부). 최초 결과는 바꾸지 않고 보관한다."""
        cache = work / 'transcript.json'
        if cache.is_file():
            try:
                saved = json.loads(cache.read_text(encoding='utf-8'))
                return saved['data'], saved.get('build', ''), float(saved.get('seconds', 0)), True
            except (OSError, ValueError, KeyError):
                cache.unlink(missing_ok=True)
        audio = self._prepared_audio(media, work, duration, report, cancelled)
        report('speech', 0.0, '')
        transcript = self.engine.transcribe(
            audio, options.model, work=work, language=language_code(options.language),
            quality=options.quality, vad=options.vad, prompt=options.prompt, gpu=options.gpu,
            progress=lambda f: report('speech', f, ''), cancelled=cancelled, on_text=on_text,
            sensitive=options.sensitive_vad)
        cache.write_text(json.dumps({'data': transcript.data, 'build': transcript.build,
                                     'seconds': transcript.seconds}, ensure_ascii=False),
                         encoding='utf-8')
        return transcript.data, transcript.build, transcript.seconds, False

    def _prepared_audio(self, media, work, duration, report, cancelled):
        """작업 폴더의 인식용 오디오(있으면 재사용). 작업이 끝나면 make가 지운다."""
        for name in ('audio.wav',) + tuple('input' + suffix for suffix in sorted(speech.NATIVE_AUDIO)):
            if (work / name).is_file():
                return work / name
        report('audio', 0.0, '')
        return self._audio(media, work, duration, report, cancelled)

    # ── 선택적 재인식 ──
    def _review(self, media, options, work, segments, code, rules, duration, report, cancelled, vad_map=()):
        """오류 의심·발언 누락 구간만 다시 인식해, 명확히 나은 후보만 반영한다.
        (구간, 판단 기록, 비슷한 이름). 판단 기록은 작업 폴더에 보관해 다시 계산하지 않는다."""
        cache = work / ('review-%s.json' % options.quality)
        names = tuple(asr_review.similar_names(segments))
        if options.quality == 'fast':
            return segments, (), names, ''
        if cache.is_file():
            try:
                saved = json.loads(cache.read_text(encoding='utf-8'))
                return (_segments_from(saved['segments']), tuple(_decision_from(item) for item in saved['decisions']),
                        names, saved.get('note', ''))
            except (OSError, ValueError, KeyError, TypeError):
                cache.unlink(missing_ok=True)
        audio = self._prepared_audio(media, work, duration, report, cancelled)
        try:
            source = wave.open(str(audio), 'rb')
        except (wave.Error, EOFError, OSError):
            return segments, (), names, 'audio is not PCM WAV; selective re-recognition skipped'
        with source:
            return self._review_audio(source, options, work, segments, code, rules, report, cancelled,
                                      cache, names, vad_map)

    def _review_audio(self, source, options, work, segments, code, rules, report, cancelled, cache, names,
                      vad_map):
        params = source.getparams()
        if params.sampwidth != 2:
            return segments, (), names, 'audio is not 16-bit PCM; selective re-recognition skipped'
        total = int(params.nframes * 1000 / params.framerate)
        main = _language_name(code)
        mismatched = []
        for segment in segments:
            if len(speech.normalize(segment.text)) >= 12 and main:
                found = detect_language(segment.text)
                if found and found != main and not ('Chinese' in found and 'Chinese' in main):
                    mismatched.append(segment.start)
        found = asr_review.suspicious_ranges(segments, mismatched=mismatched)
        found += [asr_review.Range(start, end, 'possible missing speech')
                  for start, end in asr_review.unrecognized_speech(segments, vad_map)]
        ranges = asr_review.merge_ranges(found, limit=24 if options.quality == 'best' else 12, total=total)
        installed = self.engine.status().models
        retry_model = ('large-v3' if options.quality == 'best' and 'large-v3' in installed
                       else options.model)
        chosen = language_code(options.language)
        retry = work / 'retry'
        shutil.rmtree(retry, ignore_errors=True)
        retry.mkdir(parents=True, exist_ok=True)
        snippets, languages = [], []
        for index, item in enumerate(ranges):
            snippet = retry / ('%d.wav' % index)
            first = min(params.nframes, item.start * params.framerate // 1000)
            source.setpos(first)
            piece = source.readframes(max(0, item.end * params.framerate // 1000 - first))
            with wave.open(str(snippet), 'wb') as handle:
                handle.setnchannels(params.nchannels)
                handle.setsampwidth(2)
                handle.setframerate(params.framerate)
                handle.writeframes(piece)
            snippets.append(snippet)
            # 다른 언어로 의심되는 구간과 건너뛴 말소리(대개 다른 언어)는 그 구간만 언어를 다시 감지한다.
            languages.append('auto' if item.reason in ('language mismatch', 'possible missing speech')
                             or chosen == 'auto' and code == 'und'
                             else chosen if chosen != 'auto' else speech.whisper_code(code))
        try:
            answers = self._recognize_snippets(snippets, languages, retry_model, options, retry, report,
                                               cancelled)
        finally:
            shutil.rmtree(retry, ignore_errors=True)
        decisions = []
        for item, answer in zip(ranges, answers):
            missing = item.reason == 'possible missing speech'
            original = [] if missing else [segment for segment in segments
                                           if segment.end > item.start and segment.start < item.end]
            if isinstance(answer, Exception):
                decisions.append(asr_review.Decision(item, ' '.join(s.text for s in original), '', False,
                                                     'retry failed: ' + str(answer)[:120]))
                continue
            _, candidate = speech.parse_result(answer.data, spaced=rules.spaced)
            candidate = asr_review.shift(candidate, item.start)
            decision = asr_review.choose(item, original, candidate)
            decisions.append(decision)
            if decision.accepted:
                segments = (asr_review.insert_range(segments, item, candidate) if missing
                            else asr_review.replace_range(segments, item, candidate))
        report('review', 1.0, '')
        note = ('re-recognized with ' + retry_model) if ranges else ''
        cache.write_text(json.dumps({'segments': [_segment_dict(item) for item in segments],
                                     'decisions': [_decision_dict(item) for item in decisions],
                                     'note': note}, ensure_ascii=False), encoding='utf-8')
        return segments, tuple(decisions), names, note

    def _recognize_snippets(self, snippets, languages, model, options, work, report, cancelled):
        """재인식 구간들을 언어별로 묶어 whisper-cli 한 번에 인식한다(모델을 구간마다 다시 올리지 않는다).
        묶음이 실패하면 그 묶음만 구간별로 다시 시도해, 한 구간의 문제가 다른 구간을 막지 않게 한다.
        구간 순서대로 Transcript 또는 그 구간의 예외."""
        answers = [None] * len(snippets)
        groups = {}
        for index, language in enumerate(languages):
            groups.setdefault(language, []).append(index)
        finished = 0

        def run(indexes, language):
            done = finished

            def progress(fraction):
                report('review', (done + fraction * len(indexes)) / max(1, len(snippets)),
                       '%d/%d' % (min(len(snippets), done + 1 + int(fraction * len(indexes))), len(snippets)))
            return self.engine.transcribe_many([snippets[index] for index in indexes], model, work=work,
                                               language=language, quality='best', vad=False,
                                               prompt=options.prompt, gpu=options.gpu, progress=progress,
                                               cancelled=cancelled)
        for language, indexes in groups.items():
            if cancelled():
                raise InterruptedError('Cancelled')
            try:
                for index, answer in zip(indexes, run(indexes, language)):
                    answers[index] = answer
            except InterruptedError:
                raise
            except (OSError, RuntimeError, ValueError) as exc:
                if len(indexes) == 1:
                    answers[indexes[0]] = exc
                else:
                    for index in indexes:
                        try:
                            answers[index] = run([index], language)[0]
                        except InterruptedError:
                            raise
                        except (OSError, RuntimeError, ValueError) as single:
                            answers[index] = single
            finished += len(indexes)
        return answers

    # ── 만들기 ──
    def make(self, path, options: Options, *, translate: Translate | None = None,
             progress: Callable[[str, float, str], None] | None = None,
             cancelled: Callable[[], bool] | None = None,
             on_text: Callable[[str], None] | None = None, output_dir=None,
             existing_original=None, naming: Translate | None = None) -> Result:
        """progress(단계, 0~1, 설명): 단계는 'audio'·'speech'·'review'·'write'·'translate'.
        output_dir를 주면 원본 옆 대신 그 폴더에 자막을 쓴다(폴더 번역의 결과 폴더).
        existing_original: 앞선 실행이 만든 원어 자막(번역만 실패했던 경우). 다시 쓰지 않고 번역만 한다.
        naming: 번역은 다른 곳(폴더 번역)이 하지만 원어 자막 이름은 번역 이름 규칙을 따를 때."""
        self._abort.clear()
        user_cancelled = cancelled
        cancelled = lambda: self._abort.is_set() or bool(user_cancelled and user_cancelled())
        report = progress or (lambda stage, fraction, note: None)
        media = Path(path)
        if not media.is_file():
            raise FileNotFoundError('File not found: ' + str(media))
        if media.suffix.lower() not in speech.MEDIA:
            raise ValueError('Unsupported media file: ' + media.suffix)
        if options.model not in speech.BY_KEY:
            raise ValueError('Unknown speech model: ' + options.model)
        formats = tuple(fmt for fmt in options.formats if fmt in subtitles.FORMATS) or ('srt',)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._prune()
        work = self.work_dir / self._key(media, options)
        work.mkdir(parents=True, exist_ok=True)
        os.utime(work)
        duration = self.engine.duration_ms(media)
        data, build, seconds, reused = self._recognize(media, options, work, duration, report,
                                                       cancelled, on_text)
        if cancelled():
            raise InterruptedError('Cancelled')

        detected = speech.whisper_code(str(((data.get('result') or {}).get('language')) or ''))
        chosen = language_code(options.language)
        code = chosen if chosen != 'auto' else (detected if detected not in ('', 'auto') else 'und')
        rules = subtitles.rules_for(code, max_chars=options.max_chars, max_lines=options.max_lines)
        _, segments = speech.parse_result(data, spaced=rules.spaced)
        try:
            segments, decisions, names, review_note = self._review(
                media, options, work, segments, code, rules, duration, report, cancelled,
                data.get(speech.VAD_MAP_KEY) or ())
        finally:
            for name in ('audio.wav',) + tuple('input' + suffix for suffix in sorted(speech.NATIVE_AUDIO)):
                (work / name).unlink(missing_ok=True)       # 큰 임시 오디오는 끝나면 지운다
        report('write', 0.0, '')
        cleaned = speech.clean(segments, keep_sounds=options.keep_sounds)
        cues = subtitles.build_cues(speech.words_of(cleaned.segments), rules)
        if not cues:
            raise ValueError('No speech was recognized in the file')
        joined = ' '.join(cue.text for cue in cues)
        label = language_label(code, joined)
        if code == 'zh' and label == '繁體中文':
            code = 'zh-Hant'
        review = list(subtitles.review(cues, rules))
        for start, text, reason in cleaned.flagged:
            number = next((i for i, cue in enumerate(cues, 1) if cue.end > start), len(cues))
            review.append(subtitles.Review(number, reason))
        review = tuple(sorted({(item.index, item.reason) for item in review}))
        if output_dir is not None:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
        probe = Result(media, (), code, label, tuple(cues), '')
        # 번역 자막이 원본 이름을 쓰면 원어 자막은 영상.<원어>.srt로 비켜 준다(번역이 생략되면 그대로 영상.srt).
        rule = translate or naming
        translated_main = bool(rule and rule.main_name and not self.same_language(probe, rule.target))
        if existing_original is not None:
            outputs = (Path(existing_original),)
        else:
            outputs = tuple(_write_new(output_path(media, code, fmt, output_dir) if translated_main
                                       else original_path(media, fmt, output_dir), subtitles.render(cues, fmt))
                            for fmt in formats)
        result = Result(media, outputs, code, label, tuple(cues), subtitles.render(cues, formats[0]),
                        review, tuple(cleaned.removed), build, seconds, duration, reused,
                        decisions=decisions, names=names, review_note=review_note)
        if translate is None:
            return result
        try:
            return self._translate(result, translate, formats, work, report, cancelled, output_dir)
        except InterruptedError:
            raise
        except (OSError, ValueError, RuntimeError) as exc:
            # 인식과 원어 자막은 끝났다. 번역 실패(예: Ollama가 막 켜지는 중) 때문에 그 결과를 버리지 않는다.
            return replace(result, translation_error=str(exc) or exc.__class__.__name__)

    @staticmethod
    def same_language(result, target_label):
        """번역할 필요가 없는지(같은 언어). 간체 ↔ 번체 중국어는 다른 자막으로 본다."""
        target = language_code(target_label)
        same_base = target.split('-')[0] == result.language.split('-')[0]
        return target == result.language or (same_base and target.split('-')[0] != 'zh')

    @staticmethod
    def translation_source(result, path):
        """번역 도구에 넘길 사본: 큐마다 한 줄(번역 도구는 줄 단위로 번역하므로 두 줄로 나뉜 문장을 잇는다).
        번역 도구에 알려 줄 원문 언어(화면 이름 또는 'auto')를 돌려준다."""
        rules = subtitles.rules_for(result.language)
        single = [subtitles.Cue(cue.start, cue.end, ((' ' if rules.spaced else '').join(cue.lines),),
                                cue.confidence) for cue in result.cues]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(subtitles.to_srt(single), encoding='utf-8', newline='')
        return result.language_label if any(item.label == result.language_label for item in LANGUAGES) else 'auto'

    @staticmethod
    def finish_translation(translated, target_label, destinations, *, overwrite=False):
        """번역된 한 줄 자막을 번역 언어 규칙으로 다시 나눠 형식별 경로 {fmt: Path}에 쓴다.
        (쓴 경로들, 첫 형식의 글). overwrite는 이 도구가 만든 번역 자막을 고쳐 쓸 때만."""
        rules = subtitles.rules_for(language_code(target_label))
        cues = subtitles.reflow(subtitles.parse(Path(translated).read_text(encoding='utf-8-sig')), rules)
        written = []
        for fmt, path in destinations.items():
            text = subtitles.render(cues, fmt)
            if overwrite:
                temporary = Path(path).with_name('.%s.%d.tmp' % (Path(path).name, os.getpid()))
                temporary.write_text(text, encoding='utf-8-sig', newline='')
                os.replace(temporary, path)
                written.append(Path(path))
            else:
                written.append(_write_new(path, text))
        return tuple(written), subtitles.render(cues, next(iter(destinations)))

    def _translate(self, result, options, formats, work, report, cancelled, output_dir=None):
        if self.same_language(result, options.target):
            return replace(result, translation_skipped='same language')
        target = language_code(options.target)
        source = work / 'translate-source.srt'
        source_language = self.translation_source(result, source)
        translated = work / ('translate-%s.srt' % target)
        translated.unlink(missing_ok=True)
        report('translate', 0.0, '')
        answer = self.translator.translate_file(
            source, model=options.model, target=options.target, kind='subtitle', style=options.style,
            output_path=translated, resume=True, keep_failed=options.keep_failed,
            glossary=options.glossary, precise=options.precise, source_language=source_language,
            progress=lambda done, total: report('translate', done / total if total else 0.0,
                                                '%d/%d' % (done, total)),
            cancelled=cancelled)
        destination = (original_path if options.main_name else
                       lambda media, fmt, folder: output_path(media, target, fmt, folder))
        outputs, text = self.finish_translation(
            translated, options.target, {fmt: destination(result.source, fmt, output_dir) for fmt in formats})
        for item in (source, translated):
            item.unlink(missing_ok=True)
        return replace(result, translated=answer, translated_outputs=outputs, translated_text=text)

    def revise_terms(self, result, changes, *, progress=None, cancelled=None):
        """번역 자막의 용어를 고친다: 그 용어가 든 큐만 다시 번역하고 번역 자막 파일을 고쳐 쓴다."""
        if result.translated is None or not result.translated_outputs:
            raise ValueError('There is no translated subtitle to revise')
        scratch = self.work_dir / 'revise'
        scratch.mkdir(parents=True, exist_ok=True)
        temporary = scratch / ('revise-%d.srt' % os.getpid())
        try:
            answer = self.translator.revise_terms(result.translated, changes, output_path=temporary,
                                                  progress=progress, cancelled=cancelled)
            target = language_label_from(answer)
            outputs, text = self.finish_translation(
                temporary, target, {_format_of(path): path for path in result.translated_outputs}, overwrite=True)
        finally:
            temporary.unlink(missing_ok=True)
        return replace(result, translated=answer, translated_outputs=outputs, translated_text=text)

    def folder_media(self, options: Options, *, main_name=True):
        """번역 도구의 폴더 번역이 영상·음성 파일에 쓰는 처리기(FolderMedia).
        main_name이면 결과 폴더에서 번역 자막이 영상.srt, 원어 자막이 영상.<원어>.srt가 된다."""
        return FolderMedia(self, options, main_name=main_name)

    @staticmethod
    def already_done(media, options, translate):
        """(건너뛸 근거가 되는 자막 또는 None, 다시 쓸 원어 자막 또는 None).
        번역도 만들 때는 번역 자막까지 있어야 끝난 것으로 본다. 원어 자막만 있으면(앞선 실행에서 번역만
        실패) 인식 결과를 재사용해 번역만 한다."""
        existing = existing_subtitles(media)
        if not existing:
            return None, None
        if translate is None:
            return existing[0], None
        fmt = next((fmt for fmt in options.formats if fmt in subtitles.FORMATS), 'srt')
        suffix = subtitles.FORMATS[fmt][0]
        media = Path(media)
        main = media.with_name(media.stem + suffix)
        tagged = media.with_name('%s.%s%s' % (media.stem, language_code(translate.target), suffix))
        if translate.main_name:
            if main.exists():
                return main, None
            others = [path for path in existing if path.suffix.lower() == suffix and path != tagged]
            return None, (others[0] if others else None)
        if tagged.exists():
            return tagged, None
        return None, (main if main.exists() else None)

    def make_many(self, paths, options: Options, *, translate: Translate | None = None,
                  progress=None, on_file=None, cancelled=None, on_text=None, skip_existing=True) -> Batch:
        """여러 파일을 차례로 만든다. 한 파일이 실패해도 나머지는 계속한다(취소는 즉시 멈춤).
        skip_existing이면 옆에 자막이 이미 있는 파일은 인식하지 않고 건너뛴다(폴더를 다시 돌려도 새 파일만)."""
        results, failed, skipped = [], [], []
        paths = [Path(path) for path in paths]
        for index, path in enumerate(paths, 1):
            if cancelled and cancelled():
                break
            reuse = None
            if skip_existing:
                done, reuse = self.already_done(path, options, translate)
                if done is not None:
                    skipped.append((path, done))
                    continue
            if on_file:
                on_file(index, len(paths), path)
            try:
                results.append((path, self.make(path, options, translate=translate, progress=progress,
                                                cancelled=cancelled, on_text=on_text, existing_original=reuse)))
            except InterruptedError:
                raise
            except (OSError, ValueError, RuntimeError) as exc:
                failed.append((path, exc))
        return Batch(tuple(results), tuple(failed), tuple(skipped))


@dataclass
class MediaJob:
    """폴더 번역에서 영상·음성 하나: 원어 자막을 만든 뒤 번역 도구가 번역할 한 줄 자막(source)."""
    media: Path
    result: Result | None
    source: Path | None
    language: str                   # 번역 도구에 알려 줄 원문 언어
    destinations: dict              # {형식: 결과 폴더의 번역 자막 경로}
    target: str = ''                # 번역 언어(화면 이름)
    skip: str = ''


class FolderMedia:
    """TranslationService.translate_folder가 영상·음성 파일을 다루는 방법.

    prepare: 결과 폴더에 원어 자막을 만들고, 번역 도구에 넘길 한 줄 자막을 작업 폴더에 둔다.
             번역 자막이 이미 있으면(중단 후 다시 실행) 인식하지 않고 건너뛴다.
    finish : 번역된 한 줄 자막을 번역 언어 규칙으로 다시 나눠 결과 폴더에 쓴다.
    """
    suffixes = speech.MEDIA

    def __init__(self, service, options, *, main_name=True):
        self.service = service
        self.options = options
        self.main_name = main_name
        self.formats = tuple(fmt for fmt in options.formats if fmt in subtitles.FORMATS) or ('srt',)

    def prepare(self, media, out_dir, target_label, *, cancelled=None, progress=None):
        media, out_dir = Path(media), Path(out_dir)
        code = language_code(target_label)
        name = (lambda fmt: '%s%s' % (media.stem, subtitles.FORMATS[fmt][0])) if self.main_name else \
            (lambda fmt: '%s.%s%s' % (media.stem, code, subtitles.FORMATS[fmt][0]))
        destinations = {fmt: out_dir / name(fmt) for fmt in self.formats}
        if any(path.exists() for path in destinations.values()):
            return MediaJob(media, None, None, 'auto', destinations, target_label, 'already translated')
        # 앞선 실행이 원어 자막만 남긴 경우(번역 실패): 다시 쓰지 않고 그 자막으로 번역만 한다.
        mirror = out_dir / media.name
        reuse = next((path for path in existing_subtitles(mirror) if path not in destinations.values()), None) \
            if out_dir.is_dir() else None
        translate = Translate(target=target_label, model='', main_name=self.main_name)
        result = self.service.make(media, self.options, output_dir=out_dir, cancelled=cancelled,
                                   progress=progress, existing_original=reuse,
                                   naming=translate)
        if self.service.same_language(result, target_label):
            return MediaJob(media, result, None, result.language_label, destinations, target_label,
                            'already in the target language')
        key = hashlib.sha256(str(media.resolve()).encode('utf-8')).hexdigest()[:16]
        source = self.service.work_dir / 'folder' / (key + '.srt')
        language = self.service.translation_source(result, source)
        return MediaJob(media, result, source, language, destinations, target_label)

    def finish(self, job, translated):
        outputs, _ = self.service.finish_translation(translated, job.target, job.destinations)
        job.source.unlink(missing_ok=True)
        return outputs
