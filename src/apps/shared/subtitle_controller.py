"""Tk 화면에서 자막 만들기 도구를 쓰기 위한 콜백. 실제 작업은 worker thread.

번역 화면도 영상·음성 파일을 받으면 여기의 공통 함수(options_from, overall, report_text)로
같은 자막 서비스를 부른다. 두 화면이 서로 다른 규칙을 갖지 않게 하기 위해서다.
"""
import time
from dataclasses import replace
from pathlib import Path
from threading import Event
from tkinter import filedialog

from core.tools import speech
from services.tools.subtitles import Options, Translate
from .subtitle_view import FORMATS, LINES, MEDIA_PATTERN, MODEL_LABELS, QUALITIES
from .translation_view import STYLES
from .widgets import set_status, set_text, finished_level

KEY_LABELS = {key: label for label, key in MODEL_LABELS.items()}
# 저장값('srt'·'vtt'·'both') ↔ 화면 이름
FORMAT_KEYS = {(value[0] if len(value) == 1 else 'both'): value for value in FORMATS.values()}
FORMAT_NAMES = {(value[0] if len(value) == 1 else 'both'): label for label, value in FORMATS.items()}
QUALITY_NAMES = {value: label for label, value in QUALITIES.items()}
LINE_NAMES = {value: label for label, value in LINES.items()}
STAGES = {'audio': '오디오 추출', 'speech': '음성 인식', 'review': '의심 구간 재확인', 'write': '자막 쓰기',
          'translate': '번역'}
# (시작, 폭): 단계별 진행률을 전체 진행률로. 번역이 있으면 인식 몫을 줄인다.
_WEIGHTS = {False: {'audio': (0.0, 0.06), 'speech': (0.06, 0.72), 'review': (0.78, 0.18),
                    'write': (0.96, 0.04)},
            True: {'audio': (0.0, 0.04), 'speech': (0.04, 0.46), 'review': (0.50, 0.12),
                   'write': (0.62, 0.02), 'translate': (0.64, 0.36)}}


def overall(stage, fraction, translating):
    start, width = _WEIGHTS[bool(translating)].get(stage, (0.0, 0.0))
    return min(1.0, start + width * max(0.0, min(1.0, fraction)))


def options_from(prefs, *, language='자동 감지', model=''):
    """저장된 자막 기본값 → 서비스 옵션. 번역 화면은 원문 언어를 음성 언어로 넘긴다."""
    lines = prefs.get('max_lines')
    chars = prefs.get('max_chars')
    return Options(model=model or prefs.get('model') or '', language=language,
                   formats=FORMAT_KEYS.get(prefs.get('format'), ('srt',)),
                   quality=prefs.get('quality') if prefs.get('quality') in QUALITY_NAMES else 'best',
                   vad=prefs.get('vad', True), keep_sounds=prefs.get('keep_sounds', False),
                   prompt=prefs.get('prompt', ''), gpu=prefs.get('gpu', True),
                   sensitive_vad=prefs.get('sensitive_vad', False),
                   max_chars=chars if isinstance(chars, int) and chars > 0 else None,
                   max_lines=lines if lines in (1, 2) else None)


_REASONS = {'low confidence': '인식 확신도 낮음', 'fast reading speed': '읽기 속도 빠름(글이 많음)',
            'line too long': '줄이 규칙보다 김', 'typical hallucination': '무음에서 자주 지어내는 문구',
            'repetition loop shortened': '반복 루프를 줄임', 'long segment with little text': '긴 구간에 글이 거의 없음',
            'sound description': '소리 표기', 'repeated': '같은 문장 반복(다른 근거와 겹침)',
            'repetition kept': '반복이 있으나 실제 발화일 수 있어 유지', 'high compression ratio': '같은 말이 과하게 반복됨',
            'implausible speech rate': '사람이 낼 수 없는 발화 속도', 'repetition loop': '반복 루프',
            'language mismatch': '다른 언어로 인식된 듯함', 'possible missing speech': '말소리가 있는데 자막 없음',
            'script line not heard': '대본 줄을 음성에서 찾지 못해 시각을 추정함',
            'kept in source language': '번역 자막에 원문이 남음(번역 실패)'}
_WHY = {'recovered missing speech': '누락된 발언을 찾아 넣음', 'clearly higher confidence': '확신도가 명확히 높아 교체',
        'same text': '다시 인식해도 같음', 'not clearly better; kept original': '명확히 낫지 않아 원래 결과 유지',
        'no candidate text': '다시 인식해도 말소리 없음', 'candidate confidence too low': '확신도가 낮아 넣지 않음'}


def _clock(ms):
    seconds = int(ms // 1000)
    return '%02d:%02d:%02d' % (seconds // 3600, seconds // 60 % 60, seconds % 60)


def report_text(result):
    lines = ['언어: %s · 자막 %d개 · 엔진 %s%s' % (
        result.language_label, len(result.cues), (result.build or '?').upper(),
        ' · 보관한 인식 결과 재사용' if result.reused else
        (' · 인식 %.0f초' % result.seconds if result.seconds else ''))]
    lines += ['저장: ' + str(path) for path in result.outputs + tuple(result.translated_outputs)]
    if getattr(result, 'script', ''):
        missed = result.script_missed
        lines.append('대본: %s · 글은 대본 그대로, 시각은 음성에서%s' % (
            Path(result.script).name, (' · 음성에서 찾지 못한 대본 줄 %d개(시각 추정): %s' % (
                len(missed), ', '.join(map(str, missed[:30])) + (' …' if len(missed) > 30 else '')))
            if missed else ' · 모든 줄을 음성에서 찾음'))
    if getattr(result, 'renamed_from', None):
        lines.append('파일 이름 번역: %s → %s' % (result.renamed_from.name, result.source.name))
    for kept in getattr(result, 'set_aside', ()):
        lines.append('기존 자막은 이름을 바꿔 보관: ' + str(kept))
    if result.translation_skipped:
        lines.append('번역 생략: 음성 언어와 번역 언어가 같습니다.')
    if getattr(result, 'translation_error', ''):
        lines.append('번역 실패(원어 자막은 저장됨, 다시 시작하면 인식 없이 번역만 합니다): '
                     + friendly(result.translation_error))
    lines += ['', '확인하면 좋은 자막 (%d)' % len(result.review)]
    lines += ['  %d번: %s' % (number, _REASONS.get(reason, reason)) for number, reason in result.review[:80]]
    if not result.review:
        lines.append('  (없음)')
    lines += ['', '자동으로 지운 문장 (%d)' % len(result.removed)]
    lines += ['  %s  %s — %s' % (_clock(start), text[:60], _REASONS.get(reason, reason))
              for start, text, reason in result.removed[:80]]
    if not result.removed:
        lines.append('  (없음)')
    decisions = getattr(result, 'decisions', ())
    if decisions:
        changed = sum(1 for item in decisions if item.accepted)
        lines += ['', '의심 구간 재확인 %d곳 · 반영 %d곳 · 원래 결과 유지 %d곳' % (
            len(decisions), changed, len(decisions) - changed)]
        for item in decisions[:60]:
            why = _WHY.get(item.why, item.why)
            if why.startswith('original had '):
                why = '원래 결과에 문제가 있어 교체(' + ', '.join(
                    _REASONS.get(part.strip(), part.strip()) for part in item.why[13:].split(',')) + ')'
            elif why.startswith('candidate also suspicious'):
                why = '다시 인식한 결과도 의심스러워 원래 결과 유지'
            lines.append('  %s  [%s] %s%s' % (_clock(item.range.start), _REASONS.get(item.range.reason, item.range.reason),
                                              why, (' → ' + item.candidate[:50]) if item.accepted else ''))
    elif getattr(result, 'review_note', ''):
        lines += ['', '재확인: ' + result.review_note]
    names = getattr(result, 'names', ())
    if names:
        lines += ['', '철자가 비슷한 이름(통일하지 않았습니다. 같은 인물인지 확인하세요)']
        lines += ['  %s(%d회) / %s(%d회)' % pair for pair in names[:20]]
    answer = result.translated
    if answer is not None:
        kept = getattr(answer, 'kept_lines', ())
        audit = getattr(answer, 'audit', ())
        lines += ['', '번역 검수: 원문 유지 %d줄 · 확인 필요 %d줄' % (len(kept), len(audit))]
        untranslated = getattr(result, 'untranslated', ())
        if untranslated:
            lines.append('  원문으로 남은 자막(번역 검증을 끝내 통과하지 못함 — 번역 자막에도 원문이 보입니다):')
            lines += ['    %d번 %s  %s' % (number, _clock(start), text[:60]) for number, start, text in untranslated[:30]]
        elif kept:
            lines.append('  원문으로 남은 줄(번역 검증을 끝내 통과하지 못함): ' + ', '.join(map(str, kept[:30])))
    return '\n'.join(lines)


def skipped_text(batch):
    parts = []
    if batch.skipped:
        parts.append('이미 자막이 있어 건너뛴 파일 (%d)\n' % len(batch.skipped) + '\n'.join(
            '  %s  (있는 자막: %s)' % (path.name, existing.name) for path, existing in batch.skipped[:200]))
    unmatched = getattr(batch, 'unmatched', ())
    if unmatched:
        parts.append('대본 폴더에 같은 이름의 대본이 없어 건너뛴 파일 (%d)\n' % len(unmatched) + '\n'.join(
            '  ' + path.name for path in unmatched[:200]))
    return '\n\n'.join(parts)


_FRIENDLY = (
    ('whisper.cpp is not installed', '음성 인식 엔진이 없습니다. 관리자 계정에서 [엔진 설치 / 복구]를 누르세요.'),
    ('speech model is not installed', '선택한 음성 인식 모델이 없습니다. 아래 표에서 받으세요(관리자).'),
    ('ffmpeg is not installed', '영상을 읽을 ffmpeg가 없습니다. [엔진 설치 / 복구]를 다시 실행하세요(WAV·MP3·FLAC은 됩니다).'),
    ('could not read audio', '파일에서 소리를 읽지 못했습니다. 오디오 트랙이 있는 파일인지 확인하세요.'),
    ('no speech was recognized', '말소리를 찾지 못했습니다. 음성 언어를 직접 고르거나 VAD를 꺼 보세요.'),
    ('speech recognition failed', '음성 인식이 실패했습니다. GPU 사용을 끄거나 더 작은 모델로 다시 시도하세요.'),
    ('checksum mismatch', '받은 파일의 검증값이 맞지 않아 지웠습니다. 다시 시도하세요.'),
    ('unsupported media', '지원하지 않는 형식입니다.'),
    ('too many media', '폴더의 영상·음성 파일이 너무 많습니다(최대 500개).'),
    ('script does not match', '대본이 이 파일의 음성과 맞지 않습니다. 음성 언어와 대본 파일을 확인하세요.'),
    ('script has no lines', '대본에 자막으로 쓸 줄이 없습니다(빈 줄·[지문]만 있음).'),
    ('one media file at a time', '대본은 영상·음성 파일 하나에만 쓸 수 있습니다.'),
    ('urlopen error', '내려받기 서버에 연결하지 못했습니다. 인터넷 연결을 확인하세요.'),
)


def friendly(exc):
    text = str(exc)
    lower = text.lower()
    for key, message in _FRIENDLY:
        if key in lower:
            return message + ' (' + text[:160] + ')'
    return text


class SubtitleController:
    def subtitle_say(self, state, text, *, log=False, level='info', action=None):
        set_status(self.subtitle_status_label, state, text, action)
        if log:
            self.log('[자막] ' + text, level=finished_level(state, level))

    # ── 기본값 ──
    def _subtitle_fields(self):
        return {'language': self.subtitle_language, 'format': self.subtitle_format,
                'model': self.subtitle_model, 'translate': self.subtitle_translate,
                'target': self.subtitle_target, 'llm': self.subtitle_llm, 'style': self.subtitle_style,
                'main_name': self.subtitle_main_name, 'translate_name': self.subtitle_translate_name,
                'quality': self.subtitle_quality, 'vad': self.subtitle_vad,
                'keep_sounds': self.subtitle_keep_sounds, 'gpu': self.subtitle_gpu,
                'sensitive_vad': self.subtitle_sensitive}

    def subtitles_opened(self):
        if getattr(self, '_subtitle_prefs_loaded', False):
            self.refresh_subtitle_status()
            return
        self._subtitle_prefs_loaded = True
        self._subtitle_last = {}

        def apply(prefs):
            self._subtitle_loading = True
            self._subtitle_last = dict(prefs)
            fields = self._subtitle_fields()
            names = {'format': FORMAT_NAMES, 'quality': QUALITY_NAMES, 'model': KEY_LABELS,
                     'style': {v: k for k, v in STYLES.items()}}
            for key, variable in fields.items():
                if key in prefs and key not in ('llm',):
                    value = prefs[key]
                    variable.set(names[key].get(value, variable.get()) if key in names else value)
            if prefs.get('max_lines') in LINE_NAMES:
                self.subtitle_lines.set(LINE_NAMES[prefs['max_lines']])
            if isinstance(prefs.get('max_chars'), int) and prefs['max_chars'] > 0:
                self.subtitle_chars.set(str(prefs['max_chars']))
            if prefs.get('prompt'):
                self.subtitle_prompt_text.delete('1.0', 'end')
                self.subtitle_prompt_text.insert('1.0', prefs['prompt'])
            self.toggle_subtitle_advanced(prefs.get('advanced', False), save=False)
            if 'folded' in prefs:
                self.subtitle_folds.apply(prefs['folded'])
                self._subtitle_rebind()
            self._subtitle_loading = False
            for variable in list(fields.values()) + [self.subtitle_lines, self.subtitle_chars]:
                variable.trace_add('write', lambda *_: self.schedule_subtitle_save())
            self.subtitle_prompt_text.bind('<KeyRelease>', lambda _e: self.schedule_subtitle_save(), add='+')
            self.refresh_subtitle_status()
            if self.subtitle_translate.get():
                self.refresh_subtitle_llms()
        self.run_task('tools.subtitles.prefs', self.services.settings.subtitle_preferences, apply,
                      mutate=False, announce=False, error=lambda _e: self.refresh_subtitle_status())

    def subtitle_preferences_now(self):
        values = {key: variable.get() for key, variable in self._subtitle_fields().items()}
        chosen = FORMATS.get(values['format'], ('srt',))
        values['format'] = chosen[0] if len(chosen) == 1 else 'both'
        values['quality'] = QUALITIES[values['quality']]
        values['model'] = MODEL_LABELS.get(values['model'], self._subtitle_last.get('model', ''))
        values['style'] = STYLES.get(values['style'], 'natural')
        values['llm'] = values['llm'] or self._subtitle_last.get('llm', '')
        values['max_lines'] = LINES.get(self.subtitle_lines.get(), 2)
        chars = self.subtitle_chars.get().strip()
        values['max_chars'] = int(chars) if chars.isdigit() else 0
        values['prompt'] = self.subtitle_prompt_text.get('1.0', 'end').strip()[:2000]
        values['advanced'] = bool(getattr(self, '_subtitle_advanced_open', False))
        values['folded'] = self.subtitle_folds.folded_text()
        values['last_dir'] = self._subtitle_last.get('last_dir', '')
        return values

    def _subtitle_rebind(self):
        scroller = self.page_scrolls.get('tools.subtitles')
        if scroller is not None:
            scroller.bind_content()

    def subtitle_folds_changed(self):
        """구획을 접거나 펼쳤다: 스크롤 영역을 다시 맞추고, 접은 상태를 기억한다."""
        self._subtitle_rebind()
        if getattr(self, '_subtitle_prefs_loaded', False):
            self.schedule_subtitle_save()

    def choose_subtitle_script_home(self):
        """① 대본과 영상이 한 폴더에: 대본 폴더 안에 영상·음성이 있으면 그것들로 바로 준비한다.
        없으면 짝이 되는 영상·음성이 있는 폴더를 따로 묻는다(②)."""
        value = filedialog.askdirectory(parent=self.root, title='대본과 영상·음성이 함께 있는 폴더',
                                        mustexist=True, initialdir=self._subtitle_start_dir())
        if not value:
            return
        self._remember_subtitle_dir(Path(value).parent)
        self.subtitle_script.set(value)
        from services.tools.subtitles import scan

        def found(media):
            if media:
                self.subtitle_path.set(value)
                self._subtitle_files = list(media)
                self.analyze_subtitle_input(keep=True)
                return
            self.subtitle_say('Working', '대본 폴더에 영상·음성 파일이 없습니다. 짝이 되는 영상·음성이 있는 폴더를 고르세요.')
            self.choose_subtitle_folder()

        self.run_task('tools.subtitles.inspect', lambda: scan(Path(value)), found, mutate=False, announce=False,
                      error=lambda exc: self.subtitle_say('Failed', friendly(exc)))

    def update_subtitle_script_summary(self):
        """대본 폴더와 고른 영상·음성이 몇 개 짝지어지는지 미리 보여 준다(시작 전에 확인)."""
        label = getattr(self, 'subtitle_script_summary', None)
        if label is None:
            return
        script = self.subtitle_script.get().strip()
        files = list(getattr(self, '_subtitle_files', []))
        text, warn = '', False
        if script and Path(script).is_dir():
            if not files:
                text = '대본 폴더를 골랐습니다. 짝이 되는 영상·음성(파일이나 폴더)을 고르세요.'
            else:
                key = (script, tuple(files))
                if getattr(self, '_subtitle_pairs_key', None) != key:
                    from services.tools.subtitles import match_scripts
                    root = Path(self.subtitle_path.get().strip())
                    try:
                        pairs = match_scripts(files, script, root if root.is_dir() else None)
                    except OSError:
                        pairs = {}
                    self._subtitle_pairs_key, self._subtitle_pairs = key, pairs
                matched = sum(1 for value in self._subtitle_pairs.values() if value)
                warn = not matched
                text = ('대본과 짝지은 영상·음성 %d개 / %d개' % (matched, len(files))
                        + (' · 대본이 없는 %d개는 건너뜁니다' % (len(files) - matched) if matched < len(files) else '')
                        + ('' if matched else ' · 이름이 같은 대본이 없습니다. 대본 폴더나 영상·음성 폴더를 확인하세요.'))
        elif script and Path(script).is_file():
            warn = len(files) > 1
            text = ('대본 파일 하나는 영상·음성 하나에만 씁니다. 여러 파일은 대본 폴더를 고르세요.' if warn else
                    '대본 파일 하나: 영상·음성 하나에만 씁니다.')
        elif script:
            text, warn = '대본 파일이나 폴더를 찾지 못했습니다.', True
        label.configure(text=text, style='Alert.TLabel' if warn else 'TLabel')
        self._show_subtitle_script_mode(script)

    def subtitle_script_mode(self, script=None):
        """지금 쓰는 대본 맞추기 방식: 'home'(① 대본과 영상이 한 폴더), 'split'(② 대본 폴더와 영상·음성 폴더를
        따로), 'file'(대본 파일 하나), ''(대본 없음). 고른 단추가 아니라 실제 경로로 정한다(직접 입력해도 맞다)."""
        script = (self.subtitle_script.get() if script is None else script).strip()
        if not script:
            return ''
        path = Path(script)
        if path.is_file():
            return 'file'
        if not path.is_dir():
            return ''
        media = self.subtitle_path.get().strip()
        try:
            same = bool(media) and Path(media).resolve() == path.resolve()
        except OSError:
            same = False
        return 'home' if same else 'split'

    _SCRIPT_MODES = {'home': '선택한 방식: ① 한 폴더 — 대본과 영상이 함께',
                     'split': '선택한 방식: ② 따로 — 대본 폴더 + 왼쪽의 영상·음성',
                     'file': '선택한 방식: 대본 파일 하나 — 영상·음성 하나에'}

    def _show_subtitle_script_mode(self, script):
        buttons = getattr(self, 'subtitle_mode_buttons', None)
        if not buttons:
            return
        mode = self.subtitle_script_mode(script)
        for key, button in buttons.items():
            if key == 'file':
                button.configure(style='Accent.TButton' if mode == 'file' else 'TButton')
            else:
                button.configure(style='Mode.Selected.TButton' if mode == key else 'Mode.TButton')
        self.subtitle_mode_label.configure(
            text=self._SCRIPT_MODES.get(mode, '대본을 쓰지 않습니다(음성 인식 글로 자막을 만듭니다).'),
            style='Mode.TLabel' if mode else 'Muted.TLabel')

    def choose_subtitle_script_folder(self):
        value = filedialog.askdirectory(parent=self.root, title='대본 폴더(영상·음성과 같은 이름의 대본)',
                                        mustexist=True, initialdir=self._subtitle_start_dir())
        if value:
            self.subtitle_script.set(value)

    def choose_subtitle_script(self):
        value = filedialog.askopenfilename(parent=self.root, title='시간을 맞출 대본',
                                           initialdir=self._subtitle_start_dir(),
                                           filetypes=[('대본', '*.txt *.srt *.vtt *.md'), ('모든 파일', '*.*')])
        if value:
            self.subtitle_script.set(value)

    def schedule_subtitle_save(self):
        if getattr(self, '_subtitle_loading', False) or self.closing:
            return
        pending = getattr(self, '_subtitle_save_job', None)
        if pending is not None:
            self.root.after_cancel(pending)
        self._subtitle_save_job = self.root.after(800, self.save_subtitle_preferences)

    def save_subtitle_preferences(self):
        self._subtitle_save_job = None
        values = self.subtitle_preferences_now()
        self._subtitle_last.update(values)
        self.runner.submit('tools.subtitles.prefs.save',
                           lambda: self.services.settings.set_subtitle_preferences(values), lambda _: None,
                           lambda exc: self.log('자막 기본값 저장 실패: ' + str(exc), level='error'),
                           mutate=False)

    def toggle_subtitle_advanced(self, show=None, *, save=True):
        visible = bool(getattr(self, '_subtitle_advanced_open', False))
        show = not visible if show is None else bool(show)
        self._subtitle_advanced_open = show
        if show and not visible:
            self.subtitle_advanced.pack(fill='x', after=self.subtitle_advanced_button)
        elif not show and visible:
            self.subtitle_advanced.pack_forget()
        self.subtitle_advanced_button.configure(text='고급 설정 ▾' if show else '고급 설정 ▸')
        scroller = self.page_scrolls.get('tools.subtitles')
        if scroller is not None:
            scroller.bind_content()
        if save:
            self.schedule_subtitle_save()

    def toggle_subtitle_translation(self):
        if self.subtitle_translate.get():
            if not self.subtitle_translate_options.winfo_manager():
                self.subtitle_translate_options.pack(fill='x')
            if not self.subtitle_llm_box.cget('values') and getattr(self, '_subtitle_prefs_loaded', False):
                self.refresh_subtitle_llms()
        else:
            self.subtitle_translate_options.pack_forget()

    # ── 상태 (모델 관리는 Models → 음성 인식 (자막) 탭) ──
    def refresh_subtitle_status(self, *, preserve_message=False):
        self.refresh_speech_status(preserve_message=preserve_message)

    def subtitle_status_changed(self, status, summary, preserve_message=False):
        """공용 상태 조회(refresh_speech_status) 결과를 자막 화면에 반영한다."""
        installed = [KEY_LABELS[key] for key in status.models]
        self.subtitle_model_box.configure(values=installed)
        if self.subtitle_model.get() not in installed:
            key = self.services.subtitles.recommend_model(status.models, self._subtitle_last.get('model', ''))
            self.subtitle_model.set(KEY_LABELS.get(key, ''))
        self.subtitle_engine_text.set(summary)
        if preserve_message or self._subtitle_management_busy() or self.runner.busy('tools.subtitles'):
            self.update_subtitle_destination()
            return
        shortcut = ('Models에서 받기 →', self.open_speech_models) if 'models' in self.spec.pages else None
        if not status.builds:
            self.subtitle_say('Failed', '음성 인식 엔진이 없습니다. Models → 음성 인식 (자막)에서 '
                                        '[엔진 설치 / 복구]를 누르세요(관리자).', action=shortcut)
        elif not status.models:
            self.subtitle_say('Failed', '음성 인식 모델이 없습니다. Models → 음성 인식 (자막)에서 모델을 받으세요'
                                        '(관리자, 권장: large-v3-turbo).', action=shortcut)
        else:
            self.subtitle_say('Waiting' if not self._subtitle_files else 'Ready',
                              '자막을 만들 영상이나 음성 파일을 선택하세요.' if not self._subtitle_files else
                              '준비됨 · [자막 만들기]를 누르세요.')
        self.update_subtitle_destination()

    def refresh_subtitle_llms(self):
        def done(names):
            self.subtitle_llm_box.configure(values=names)
            if self.subtitle_llm.get() not in names:
                self.subtitle_llm.set(self.services.translator.recommend_model(
                    names, self._subtitle_last.get('llm', '')))
        self.run_task('tools.subtitles.llms', self.services.translator.local_models, done, mutate=False,
                      announce=False, error=lambda e: self.subtitle_say('Failed', '번역 모델 조회 실패: ' + str(e)))

    def _subtitle_management_busy(self):
        return self._speech_management_busy()

    # ── 파일 ──
    def _subtitle_start_dir(self):
        folder = self._subtitle_last.get('last_dir', '') if hasattr(self, '_subtitle_last') else ''
        return folder if folder and Path(folder).is_dir() else ''

    def _remember_subtitle_dir(self, folder):
        if not hasattr(self, '_subtitle_last'):
            self._subtitle_last = {}
        self._subtitle_last['last_dir'] = str(folder)
        self.schedule_subtitle_save()

    def choose_subtitle_files(self):
        values = filedialog.askopenfilenames(parent=self.root, title='자막을 만들 영상·음성 파일',
                                             initialdir=self._subtitle_start_dir(),
                                             filetypes=[('영상·음성', MEDIA_PATTERN), ('모든 파일', '*.*')])
        if values:
            self._remember_subtitle_dir(Path(values[0]).parent)
            self._subtitle_files = [Path(value) for value in values]
            self.subtitle_path.set(values[0] if len(values) == 1 else '%s 외 %d개' % (values[0], len(values) - 1))
            self.analyze_subtitle_input(keep=True)

    def choose_subtitle_folder(self):
        value = filedialog.askdirectory(parent=self.root, title='영상·음성 파일이 있는 폴더', mustexist=True,
                                        initialdir=self._subtitle_start_dir())
        if value:
            self._remember_subtitle_dir(Path(value).parent)
            self.subtitle_path.set(value)
            self.analyze_subtitle_input()

    def analyze_subtitle_input(self, keep=False):
        raw = self.subtitle_path.get().strip()
        if not keep:
            path = Path(raw)
            if path.is_dir():
                from services.tools.subtitles import scan
                try:
                    self._subtitle_files = scan(path)
                except ValueError as exc:
                    self._subtitle_files = []
                    self.subtitle_say('Failed', friendly(exc))
                    return
            elif path.is_file():
                self._subtitle_files = [path]
            else:
                self._subtitle_files = []
        files = self._subtitle_files
        if not files:
            self.subtitle_say('Failed', '영상·음성 파일을 찾지 못했습니다.' if raw else '파일을 먼저 선택하세요.')
            self.update_subtitle_destination()
            return
        unsupported = [path.name for path in files if path.suffix.lower() not in speech.MEDIA]
        if unsupported:
            self.subtitle_say('Failed', '지원하지 않는 형식: ' + ', '.join(unsupported[:3]))
            self._subtitle_files = [path for path in files if path.suffix.lower() in speech.MEDIA]
        if len(files) == 1:
            def done(info):
                duration, audio = info
                if audio is False:
                    self.subtitle_say('Failed', '이 파일에는 오디오 트랙이 없습니다.')
                    return
                self.subtitle_say('Ready', '준비됨 · %s%s · [자막 만들기]를 누르세요.' % (
                    files[0].name, ' · 길이 ' + _clock(duration) if duration else ''))
            self.run_task('tools.subtitles.inspect', lambda: self.services.subtitles.media_info(files[0]), done,
                          mutate=False, announce=False, error=lambda e: None)
        else:
            self.subtitle_say('Ready', '준비됨 · 파일 %d개 · [자막 만들기]를 누르세요.' % len(files))
        set_text(self.subtitle_preview_text, '\n'.join(str(path) for path in files[:200]))
        self.update_subtitle_destination()

    def update_subtitle_destination(self):
        files = getattr(self, '_subtitle_files', [])
        suffixes = ' · '.join(FORMATS.get(self.subtitle_format.get(), ('srt',)))
        translate = self.subtitle_translate.get()
        if not files:
            text = ('자막은 원본 옆에 원본과 같은 이름으로 만듭니다(예: 영상.mp4 → 영상.srt). 원본은 바꾸지 않고, '
                    '옆에 자막이 이미 있는 파일은 건너뜁니다.')
        else:
            first = files[0]
            if translate and self.subtitle_main_name.get():
                names = '번역 "%s.%s" + 원어 "%s.<원어>.%s"' % (first.stem, suffixes, first.stem, suffixes)
            elif translate:
                names = '"%s.%s" + 번역 "%s.<번역 언어>.%s"' % (first.stem, suffixes, first.stem, suffixes)
            else:
                names = '"%s.%s"' % (first.stem, suffixes)
            script = self.subtitle_script.get().strip()
            text = '→ 결과: %s%s · %s%s' % (
                names, (' (파일 %d개 모두 각 원본 옆)' % len(files)) if len(files) > 1 else '',
                '대본 사용: 같은 이름의 기존 자막은 "이름.<언어>"로 보관' if script else '이미 자막이 있는 파일은 건너뜀',
                ' · 영상·음성 이름도 번역(이미 번역 언어면 그대로)' if translate and self.subtitle_translate_name.get()
                else '')
        self.subtitle_destination.configure(text=text)
        self.update_subtitle_script_summary()
        if not self.runner.busy('tools.subtitles'):
            ready = bool(files and self.subtitle_model.get() and getattr(self, '_speech_engine', None)
                         and self._speech_engine.builds and not self._subtitle_management_busy()
                         and (not translate or self.subtitle_llm.get()))
            self.subtitle_start_button.configure(state='normal' if ready else 'disabled')

    def open_subtitle_folder(self):
        target = getattr(self, '_subtitle_last_output', None)
        if target:
            try:
                self.services.translator.reveal(target)
            except OSError as exc:
                self.subtitle_say('Failed', '폴더를 열 수 없습니다: ' + str(exc))

    # ── 실행 ──
    def set_subtitle_progress(self, fraction, note=''):
        if not self.subtitle_progress_row.winfo_manager():
            self.subtitle_progress_row.pack(fill='x')
        self.subtitle_progress.set(100.0 * fraction)
        self.subtitle_progress_label.configure(text='%d%%%s' % (100 * fraction, ' · ' + note if note else ''))

    def subtitle_progress_event(self, data):
        """작업 스레드가 보낸 진행 이벤트(Tk 스레드에서 처리)."""
        if 'line' in data:
            self.subtitle_preview_text.configure(state='normal')
            self.subtitle_preview_text.insert('end', data['line'] + '\n')
            self.subtitle_preview_text.see('end')
            self.subtitle_preview_text.configure(state='disabled')
            return
        if data.get('message'):
            self.subtitle_say('Working', data['message'])
            self.log('[자막] ' + data['message'])
        if isinstance(data.get('fraction'), (int, float)):
            self.set_subtitle_progress(data['fraction'], data.get('eta', ''))

    def cancel_subtitles(self):
        if not self.runner.busy('tools.subtitles'):
            return
        self._subtitle_cancel.set()
        self.services.subtitles.abort()
        self.subtitle_say('Working', '중단 중 · 인식을 마친 파일의 결과는 저장되어 있습니다.')

    def start_subtitles(self):
        if self.runner.busy('tools.subtitles') or self._subtitle_management_busy():
            return
        files = list(getattr(self, '_subtitle_files', []))
        if not files or not self.subtitle_model.get():
            self.subtitle_say('Failed', '파일과 인식 모델을 먼저 선택하세요.')
            return
        prefs = self.subtitle_preferences_now()
        options = options_from(prefs, language=self.subtitle_language.get(), model=prefs['model'])
        script = self.subtitle_script.get().strip()
        if script:
            if Path(script).is_dir():
                pass                    # 대본 폴더: 영상·음성마다 같은 이름의 대본을 쓴다
            elif not Path(script).is_file():
                self.subtitle_say('Failed', '대본 파일이나 폴더를 찾지 못했습니다: ' + script)
                return
            elif len(files) > 1:
                self.subtitle_say('Failed', '대본 파일은 영상·음성 파일 하나에만 쓸 수 있습니다. '
                                            '여러 파일은 [대본 폴더…]를 고르세요(같은 이름의 대본을 찾아 씁니다).')
                return
            options = replace(options, script=script)
        translate = None
        if self.subtitle_translate.get():
            if not self.subtitle_llm.get():
                self.subtitle_say('Failed', '번역 모델을 먼저 고르세요.')
                return
            translate = Translate(target=self.subtitle_target.get(), model=self.subtitle_llm.get(),
                                  style=prefs['style'], main_name=self.subtitle_main_name.get(),
                                  translate_name=self.subtitle_translate_name.get())
        self.save_subtitle_preferences()
        self._subtitle_cancel = Event()
        self.subtitle_start_button.configure(state='disabled')
        self.subtitle_cancel_button.configure(state='normal')
        self.subtitle_open_button.configure(state='disabled')
        set_text(self.subtitle_preview_text, '')
        self.subtitle_tabs.select(0)
        self.set_subtitle_progress(0.0, '준비 중')
        self.subtitle_say('Working', '자막 만들기 시작…', log=True)
        events = self.services.events
        current = {'file': '', 'started': time.monotonic()}

        def progress(stage, fraction, note):
            value = overall(stage, fraction, translate is not None)
            elapsed = time.monotonic() - current['started']
            eta = ''
            if 0.05 < value < 1.0 and elapsed > 10:
                eta = '약 %d분 남음' % max(1, int(elapsed / value * (1 - value) / 60))
            events.emit('runtime.progress', {'service': 'subtitles', 'fraction': value, 'eta': eta,
                                             'message': '%s%s%s' % (current['file'], STAGES.get(stage, stage),
                                                                    ' ' + note if note else '')})

        def on_file(index, count, path):
            current['file'] = ('파일 %d/%d · %s · ' % (index, count, path.name)) if count > 1 else ''
            current['started'] = time.monotonic()

        def on_text(line):
            events.emit('runtime.progress', {'service': 'subtitles', 'line': line})

        stop = lambda: self._subtitle_cancel.is_set() or self.runner.cancel.is_set()

        def work():
            job = translate
            if job is not None:            # [파일 번역]의 고정 용어집을 자막 번역에도 쓴다
                glossary = self.services.settings.translation_preferences().get('glossary', '')
                job = replace(job, glossary=glossary)
            return self.services.subtitles.make_many(files, options, translate=job, progress=progress,
                                                     on_file=on_file, cancelled=stop, on_text=on_text)

        def unlock():
            self.subtitle_cancel_button.configure(state='disabled')
            self.root.after_idle(self.update_subtitle_destination)

        def done(batch):
            unlock()
            self.set_subtitle_progress(1.0, '파일 %d개' % len(batch.results) if len(files) > 1 else '')
            if batch.results:
                last = batch.results[-1][1]
                self._subtitle_last_output = (last.translated_outputs or last.outputs)[0]
                self.subtitle_open_button.configure(state='normal')
                set_text(self.subtitle_preview_text, last.text[:20000])
                set_text(self.subtitle_translated_text, last.translated_text[:20000] or
                         ('번역하지 않았습니다(음성 언어와 번역 언어가 같음).' if last.translation_skipped else
                          '[번역 자막도 함께 만들기]를 켜면 번역 자막이 표시됩니다.'))
                reports = [report_text(result) if len(batch.results) == 1 else
                           '■ %s\n%s' % (path.name, report_text(result)) for path, result in batch.results]
                if batch.failed:
                    reports.append('실패한 파일\n' + '\n'.join('  %s — %s' % (path.name, friendly(exc))
                                                           for path, exc in batch.failed))
                if batch.skipped or batch.unmatched:
                    reports.append(skipped_text(batch))
                set_text(self.subtitle_report_text, '\n\n'.join(reports))
                review = sum(len(result.review) for _, result in batch.results)
                untranslated = sum(1 for _, result in batch.results if result.translation_error)
                # 검증을 끝내 통과하지 못해 원문으로 남은 줄(예전 숫자 검사 문제)도 상태 줄에서 바로 보이게 한다.
                source_left = sum(len(getattr(result.translated, 'kept_lines', ()) or ())
                                  for _, result in batch.results)
                self.subtitle_say('Ready' if not batch.failed and not untranslated else 'Failed',
                                  '완료: 자막 %d개 파일%s%s%s%s%s · %s' % (
                                      len(batch.results), (' · 실패 %d개' % len(batch.failed)) if batch.failed else '',
                                      (' · 번역 실패 %d개(다시 시작하면 번역만)' % untranslated) if untranslated else '',
                                      (' · 원문으로 남은 줄 %d개(검토 탭)' % source_left) if source_left else '',
                                      ((' · 이미 자막 있음 %d개 건너뜀' % len(batch.skipped)) if batch.skipped else '')
                                      + ((' · 대본 없음 %d개 건너뜀' % len(batch.unmatched)) if batch.unmatched else ''),
                                      (' · 확인하면 좋은 자막 %d개' % review) if review else '',
                                      self._subtitle_last_output), log=True)
                self.subtitle_tabs.select(1 if last.translated_text else 0)
                self._subtitle_results = [result for _path, result in batch.results]
                terms = {}
                for result in self._subtitle_results:
                    terms.update(getattr(result.translated, 'glossary', None) or {})
                self.subtitle_terms_editor.load(terms, note='' if terms else
                                                '번역 자막을 만들면 번역에 쓴 용어가 여기에 표시됩니다.')
            elif batch.skipped and not batch.failed and not batch.unmatched:
                set_text(self.subtitle_report_text, skipped_text(batch))
                self.subtitle_say('Ready', '새로 만들 파일이 없습니다: %d개 모두 옆에 자막이 이미 있어 건너뛰었습니다.'
                                  % len(batch.skipped), log=True)
                self.subtitle_tabs.select(2)
            else:
                set_text(self.subtitle_report_text, '\n'.join('%s — %s' % (path.name, friendly(exc))
                                                              for path, exc in batch.failed)
                         + ('\n\n' + skipped_text(batch) if batch.skipped or batch.unmatched else ''))
                self.subtitle_say('Failed', '자막을 만들지 못했습니다: ' +
                                  (friendly(batch.failed[0][1]) if batch.failed else '처리한 파일 없음'),
                                  log=True, level='error')
                self.subtitle_tabs.select(2)
            self.root.bell()

        def failed(exc):
            unlock()
            if isinstance(exc, InterruptedError):
                self.subtitle_say('Waiting', '중단했습니다. 같은 파일·설정으로 다시 시작하면 인식 결과를 재사용합니다.', log=True)
            else:
                self.subtitle_say('Failed', '자막 만들기 실패: ' + friendly(exc), log=True, level='error')
                self.root.bell()
        if not self.run_task('tools.subtitles', work, done, mutate=False, long=True, announce=False, error=failed):
            unlock()

    def apply_subtitle_terms(self, changes, remember):
        """번역 자막에서 고친 용어를 적용한다(그 용어가 든 자막만 다시 번역해 번역 자막을 고쳐 씀)."""
        results = [item for item in getattr(self, '_subtitle_results', []) if item.translated is not None]
        if not results or self.runner.busy('tools.subtitles'):
            return
        if remember:
            self._remember_shared_terms(changes)
        editor = self.subtitle_terms_editor
        editor.busy(True)
        self._subtitle_cancel = Event()
        self.subtitle_cancel_button.configure(state='normal')
        self.subtitle_say('Working', '바꾼 용어 %d개 적용 중…' % len(changes), log=True)
        stop = lambda: self._subtitle_cancel.is_set() or self.runner.cancel.is_set()
        translator = self.services.translator

        def work():
            out = []
            for item in results:
                if translator.affected_by(item.translated, changes):
                    item = self.services.subtitles.revise_terms(item, changes, cancelled=stop)
                out.append(item)
            return out

        def done(items):
            self.subtitle_cancel_button.configure(state='disabled')
            self._subtitle_results = items
            count = sum(item.translated.revised for item in items)
            terms = {key: value for item in items for key, value in item.translated.glossary.items()}
            set_text(self.subtitle_translated_text, items[-1].translated_text[:20000])
            editor.load(terms, note='적용 완료: 자막 %d개 구간을 다시 번역해 번역 자막을 고쳐 썼습니다.' % count)
            self.subtitle_say('Ready', '용어 적용 완료: %d개 구간 다시 번역' % count, log=True)
            self.subtitle_tabs.select(1)

        def failed(exc):
            self.subtitle_cancel_button.configure(state='disabled')
            editor.busy(False)
            if isinstance(exc, InterruptedError):
                self.subtitle_say('Waiting', '용어 적용을 중단했습니다. 번역 자막은 바뀌지 않았습니다.', log=True)
            else:
                self.subtitle_say('Failed', '용어 적용 실패: ' + friendly(exc), log=True, level='error')
        self.run_task('tools.subtitles', work, done, mutate=False, long=True, announce=False, error=failed)

    def _remember_shared_terms(self, changes):
        """고정 용어집([파일 번역] 기본값)에 고친 용어를 넣는다. 번역 화면이 열려 있으면 그 칸도 고친다."""
        if hasattr(self, 'translation_glossary_text'):
            self._remember_terms(changes)
            return
        def update():
            prefs = self.services.settings.translation_preferences()
            lines = [line for line in prefs.get('glossary', '').splitlines()
                     if line.strip() and line.split('=', 1)[0].strip() not in changes]
            lines += ['%s = %s' % pair for pair in changes.items()]
            prefs['glossary'] = '\n'.join(lines)[:20000]
            self.services.settings.set_translation_preferences(prefs)
        self.runner.submit('tools.prefs.terms', update, lambda _: None,
                           lambda exc: self.log('용어집 저장 실패: ' + str(exc), level='error'), mutate=False)
