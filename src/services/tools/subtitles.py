"""자막 만들기: 영상·음성 → (음성 인식) → 자막 문법에 맞는 SRT·WebVTT → (선택) 번역 자막.

흐름
  1. ffmpeg로 첫 오디오 트랙을 16kHz 모노 WAV로 뽑는다(영상이 아니고 ffmpeg가 없으면 원본 사본).
  2. whisper.cpp로 인식한다(GPU 빌드 → 실패 시 CPU). 결과는 개인 작업 폴더에 보관해, 번역만
     다시 하거나 형식만 바꿀 때 다시 인식하지 않는다.
  3. 반복·환각·소리 표기를 정리하고, 단어 시각으로 큐를 만든다(core.tools.subtitles 규칙).
  4. 원본 옆에 '이름.<언어>.srt'(이미 있으면 번호)로 쓴다. 원본과 기존 파일은 덮어쓰지 않는다.
  5. 번역을 함께 고르면, 큐마다 한 줄로 합친 사본을 기존 번역 도구(TranslationService)로 번역한 뒤
     번역 언어의 줄 길이 규칙으로 다시 나눠 '이름.<번역 언어>.srt'로 쓴다.

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


@dataclass(frozen=True)
class Translate:
    target: str                     # 화면 언어 이름
    model: str                      # Ollama 모델
    style: str = 'natural'          # 정보 생략 없이(줄 길이는 자막 규칙이 다시 나눈다)
    glossary: str = ''
    precise: bool = False
    keep_failed: bool = True


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


@dataclass(frozen=True)
class Batch:
    results: tuple = ()             # ((파일, Result), …)
    failed: tuple = ()              # ((파일, 오류), …)


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


def output_path(media, code, fmt):
    media = Path(media)
    return numbered(media.with_name('%s.%s%s' % (media.stem, code, subtitles.FORMATS[fmt][0])))


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
        return self.engine.status()

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
        return install.install(self.engine.root, log=log, cancelled=cancelled)

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
                          options.vad, ' '.join(options.prompt.split())], ensure_ascii=False)
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
        if self.engine.ffmpeg().is_file():
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
            progress=lambda f: report('speech', f, ''), cancelled=cancelled, on_text=on_text)
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
    def _review(self, media, options, work, segments, code, rules, duration, report, cancelled):
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
                                      cache, names)

    def _review_audio(self, source, options, work, segments, code, rules, report, cancelled, cache, names):
        params = source.getparams()
        if params.sampwidth != 2:
            return segments, (), names, 'audio is not 16-bit PCM; selective re-recognition skipped'
        total = int(params.nframes * 1000 / params.framerate)
        # 100ms씩 흘려 읽어 에너지만 남긴다(긴 영상도 오디오 전체를 메모리에 올리지 않음).
        window = max(1, params.framerate // 10)
        profile = []
        while True:
            chunk = source.readframes(window)
            if not chunk:
                break
            profile.append(asr_review.rms(chunk))
        main = _language_name(code)
        mismatched = []
        for segment in segments:
            if len(speech.normalize(segment.text)) >= 12 and main:
                found = detect_language(segment.text)
                if found and found != main and not ('Chinese' in found and 'Chinese' in main):
                    mismatched.append(segment.start)
        found = asr_review.suspicious_ranges(segments, spaced=rules.spaced, mismatched=mismatched)
        found += [asr_review.Range(start, end, 'possible missing speech')
                  for start, end in asr_review.uncovered_speech(segments, profile)]
        ranges = asr_review.merge_ranges(found, limit=24 if options.quality == 'best' else 12, total=total)
        installed = self.engine.status().models
        retry_model = ('large-v3' if options.quality == 'best' and 'large-v3' in installed
                       else options.model)
        chosen = language_code(options.language)
        decisions = []
        for index, item in enumerate(ranges):
            if cancelled():
                raise InterruptedError('Cancelled')
            report('review', index / max(1, len(ranges)), '%d/%d' % (index + 1, len(ranges)))
            folder = work / 'retry' / str(index)
            folder.mkdir(parents=True, exist_ok=True)
            snippet = folder / 'audio.wav'
            first = min(params.nframes, item.start * params.framerate // 1000)
            source.setpos(first)
            piece = source.readframes(max(0, item.end * params.framerate // 1000 - first))
            with wave.open(str(snippet), 'wb') as handle:
                handle.setnchannels(params.nchannels)
                handle.setsampwidth(2)
                handle.setframerate(params.framerate)
                handle.writeframes(piece)
            language = ('auto' if item.reason == 'language mismatch' or chosen == 'auto' and code == 'und'
                        else chosen if chosen != 'auto' else speech.whisper_code(code))
            original = [segment for segment in segments if segment.end > item.start and segment.start < item.end]
            try:
                again = self.engine.transcribe(snippet, retry_model, work=folder, language=language,
                                               quality='best', vad=False, prompt=options.prompt,
                                               gpu=options.gpu, cancelled=cancelled)
            except InterruptedError:
                raise
            except (OSError, RuntimeError, ValueError) as exc:
                decisions.append(asr_review.Decision(item, ' '.join(s.text for s in original), '', False,
                                                     'retry failed: ' + str(exc)[:120]))
                continue
            finally:
                shutil.rmtree(folder, ignore_errors=True)
            _, candidate = speech.parse_result(again.data, spaced=rules.spaced)
            candidate = asr_review.shift(candidate, item.start)
            decision = asr_review.choose(item, original, candidate, spaced=rules.spaced)
            decisions.append(decision)
            if decision.accepted:
                segments = asr_review.replace_range(segments, item, candidate)
        report('review', 1.0, '')
        note = ('re-recognized with ' + retry_model) if ranges else ''
        cache.write_text(json.dumps({'segments': [_segment_dict(item) for item in segments],
                                     'decisions': [_decision_dict(item) for item in decisions],
                                     'note': note}, ensure_ascii=False), encoding='utf-8')
        return segments, tuple(decisions), names, note

    # ── 만들기 ──
    def make(self, path, options: Options, *, translate: Translate | None = None,
             progress: Callable[[str, float, str], None] | None = None,
             cancelled: Callable[[], bool] | None = None,
             on_text: Callable[[str], None] | None = None) -> Result:
        """progress(단계, 0~1, 설명): 단계는 'audio'·'speech'·'review'·'write'·'translate'."""
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
                media, options, work, segments, code, rules, duration, report, cancelled)
        finally:
            for name in ('audio.wav',) + tuple('input' + suffix for suffix in sorted(speech.NATIVE_AUDIO)):
                (work / name).unlink(missing_ok=True)       # 큰 임시 오디오는 끝나면 지운다
        report('write', 0.0, '')
        cleaned = speech.clean(segments, keep_sounds=options.keep_sounds, spaced=rules.spaced)
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
        outputs = tuple(_write_new(output_path(media, code, fmt), subtitles.render(cues, fmt))
                        for fmt in formats)
        result = Result(media, outputs, code, label, tuple(cues), subtitles.render(cues, formats[0]),
                        review, tuple(cleaned.removed), build, seconds, duration, reused,
                        decisions=decisions, names=names, review_note=review_note)
        if translate is None:
            return result
        return self._translate(result, translate, formats, work, report, cancelled)

    def _translate(self, result, options, formats, work, report, cancelled):
        target = language_code(options.target)
        same_base = target.split('-')[0] == result.language.split('-')[0]
        # 같은 언어면 번역하지 않는다(간체 ↔ 번체 중국어는 다른 자막으로 본다).
        if target == result.language or (same_base and target.split('-')[0] != 'zh'):
            return replace(result, translation_skipped='same language')
        rules = subtitles.rules_for(target)
        # 큐마다 한 줄: 번역 도구는 줄 단위로 번역하므로 두 줄로 나뉜 문장을 이어 준다.
        source_rules = subtitles.rules_for(result.language)
        single = [subtitles.Cue(cue.start, cue.end,
                                ((' ' if source_rules.spaced else '').join(cue.lines),), cue.confidence)
                  for cue in result.cues]
        source = work / 'translate-source.srt'
        source.write_text(subtitles.to_srt(single), encoding='utf-8', newline='')
        translated = work / ('translate-%s.srt' % target)
        translated.unlink(missing_ok=True)
        report('translate', 0.0, '')
        source_language = result.language_label if any(
            item.label == result.language_label for item in LANGUAGES) else 'auto'
        answer = self.translator.translate_file(
            source, model=options.model, target=options.target, kind='subtitle', style=options.style,
            output_path=translated, resume=True, keep_failed=options.keep_failed,
            glossary=options.glossary, precise=options.precise, source_language=source_language,
            progress=lambda done, total: report('translate', done / total if total else 0.0,
                                                '%d/%d' % (done, total)),
            cancelled=cancelled)
        cues = subtitles.reflow(subtitles.parse(translated.read_text(encoding='utf-8-sig')), rules)
        outputs = tuple(_write_new(output_path(result.source, target, fmt), subtitles.render(cues, fmt))
                        for fmt in formats)
        for item in (source, translated):
            item.unlink(missing_ok=True)
        return replace(result, translated=answer, translated_outputs=outputs,
                       translated_text=subtitles.render(cues, formats[0]))

    def make_many(self, paths, options: Options, *, translate: Translate | None = None,
                  progress=None, on_file=None, cancelled=None, on_text=None) -> Batch:
        """여러 파일을 차례로 만든다. 한 파일이 실패해도 나머지는 계속한다(취소는 즉시 멈춤)."""
        results, failed = [], []
        paths = [Path(path) for path in paths]
        for index, path in enumerate(paths, 1):
            if cancelled and cancelled():
                break
            if on_file:
                on_file(index, len(paths), path)
            try:
                results.append((path, self.make(path, options, translate=translate, progress=progress,
                                                cancelled=cancelled, on_text=on_text)))
            except InterruptedError:
                raise
            except (OSError, ValueError, RuntimeError) as exc:
                failed.append((path, exc))
        return Batch(tuple(results), tuple(failed))
