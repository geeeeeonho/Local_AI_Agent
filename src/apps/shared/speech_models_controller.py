"""Models → 음성 인식 (자막) 탭의 콜백: 자막 엔진·음성 인식 모델 상태, 설치·복구·삭제.

상태 조회는 한 곳(refresh_speech_status)에서 하고, 결과를 Models 탭과 Tools → 자막 만들기 화면에
함께 반영한다(각 화면이 만들어져 있을 때만). 엔진·모델 작업 중에는 자막 만들기를 시작할 수 없고,
자막을 만드는 중에는 엔진·모델을 바꿀 수 없다(작업 키 tools.subtitles*). 실제 작업은 worker thread.
"""
from threading import Event
from tkinter import messagebox

from core.tools import speech
from .subtitle_controller import friendly
from .widgets import set_status

ENGINE_KEY, MODEL_KEY = 'tools.subtitles.engine', 'tools.subtitles.model'


def engine_summary(status, access, supported, reason):
    if not status.builds:
        text = '음성 인식 엔진이 설치되지 않았습니다.'
    else:
        text = 'whisper.cpp %s · %s · 영상 읽기(ffmpeg) %s · 음성 구간 감지 %s' % (
            status.version or '?', ' + '.join('GPU(CUDA)' if b == 'cuda' else 'CPU' for b in status.builds),
            '준비됨' if status.ffmpeg else '없음(WAV·MP3·FLAC만)', '준비됨' if status.vad else '없음')
    if not supported:
        text += ' ' + reason
    elif not access.get('allowed'):
        text += ' 엔진·모델 설치와 삭제는 LocalAI 관리자만 할 수 있습니다. 설치된 모델은 사용할 수 있습니다.'
    if status.issues:
        text += ' · ' + ' / '.join(status.issues)
    return text


class SpeechModelsController:
    def speech_say(self, state, text, *, log=False, level='info'):
        if hasattr(self, 'speech_status_label'):
            set_status(self.speech_status_label, state, text)
        if log:
            self.log('[음성 인식 모델] ' + text, level=level)

    def open_speech_models(self):
        """자막 화면의 바로가기: Models → 음성 인식 (자막) 탭을 연다."""
        if 'models' not in self.spec.pages:
            self.log('음성 인식 모델은 LocalAI Studio의 Models 화면에서 관리합니다.', level='error')
            return
        self.navigate('models')
        self.model_tabs.select(self.model_pages['speech'])
        self.refresh_speech_status()

    def _speech_buttons(self):
        if not hasattr(self, 'speech_engine_button'):
            return ()
        return self.speech_engine_button, self.speech_get_button, self.speech_remove_button

    def _speech_management_busy(self):
        return any(self.runner.busy(key) for key in (ENGINE_KEY, MODEL_KEY))

    # ── 상태 ──
    def refresh_speech_status(self, *, preserve_message=False):
        if self.runner.busy('tools.subtitles.status'):
            # 진행 중인 조회는 이 요청 전의 상태일 수 있다(예: 모델을 막 받음). 끝난 뒤 한 번 더 조회한다.
            # 상태 줄 안내는 요청 중 하나라도 새 안내를 원하면 새로 쓴다.
            pending = getattr(self, '_speech_status_refresh_pending', None)
            self._speech_status_refresh_pending = preserve_message if pending is None else (pending and preserve_message)
            return

        def rerun_pending():
            pending = getattr(self, '_speech_status_refresh_pending', None)
            if pending is not None:
                self._speech_status_refresh_pending = None
                self.root.after_idle(lambda: self.refresh_speech_status(preserve_message=pending))
                return True
            return False

        def fetch():
            return (self.services.subtitles.status(), self.services.subtitles.management(),
                    self.services.subtitles.supported())

        def done(found):
            if rerun_pending():
                return
            status, access, (supported, reason) = found
            self._speech_engine = status
            self._speech_access = access
            self._speech_supported = supported
            summary = engine_summary(status, access, supported, reason)
            self._render_speech_models(status, access, supported, summary, preserve_message)
            if hasattr(self, 'subtitle_model_box'):
                self.subtitle_status_changed(status, summary, preserve_message)

        def failed(exc):
            if rerun_pending():
                return
            if not preserve_message:
                self.speech_say('Failed', '엔진 상태 확인 실패: ' + friendly(exc))
                if hasattr(self, 'subtitle_model_box'):
                    self.subtitle_say('Failed', '엔진 상태 확인 실패: ' + friendly(exc))
            else:
                self.log('[음성 인식 모델] 엔진 상태 확인 실패: ' + friendly(exc), level='error')
            if (getattr(self, '_speech_supported', False) and getattr(self, '_speech_access', {}).get('allowed')
                    and not self._speech_management_busy()):
                for button in self._speech_buttons():
                    button.configure(state='normal')
            if hasattr(self, 'subtitle_model_box'):
                self.update_subtitle_destination()
        self.run_task('tools.subtitles.status', fetch, done, mutate=False, announce=False, error=failed)

    def _render_speech_models(self, status, access, supported, summary, preserve_message):
        if not hasattr(self, 'speech_model_table'):
            return
        self.speech_engine_text.set(summary)
        manage = 'normal' if supported and access.get('allowed') and not self._speech_management_busy() else 'disabled'
        for button in self._speech_buttons():
            button.configure(state=manage)
        table = self.speech_model_table
        selected = table.selection()
        table.delete(*table.get_children())
        for item in speech.MODELS:
            table.insert('', 'end', iid=item.key, values=(
                item.label, '%.1f GB' % (item.size_mib / 1024) if item.size_mib >= 1000 else '%d MB' % item.size_mib,
                '약 %.0f GB' % item.vram_gib if item.vram_gib >= 1 else '1 GB 미만',
                '설치됨' if item.key in status.models else ('복구 필요' if item.key in status.damaged_models else '-')))
        if selected and table.exists(selected[0]):
            table.selection_set(selected[0])
        if preserve_message or self._speech_management_busy():
            return
        if not status.builds:
            self.speech_say('Failed', '음성 인식 엔진이 없습니다. [엔진 설치 / 복구]를 누르세요(관리자).')
        elif not status.models:
            self.speech_say('Failed', '음성 인식 모델이 없습니다. 아래 표에서 모델을 골라 [선택 모델 받기 / 복구]를 '
                                      '누르세요(권장: large-v3-turbo, 최고 정확도: large-v3).')
        else:
            self.speech_say('Ready', '준비됨 · 설치된 모델 %d개. Tools → 자막 만들기에서 사용할 수 있습니다.'
                            % len(status.models))

    def describe_speech_model(self):
        selected = self.speech_model_table.selection()
        if selected:
            item = speech.model(selected[0])
            self.speech_model_note.configure(text=item.label + ': ' + item.note)

    # ── 설치 · 복구 · 삭제 ──
    def speech_progress_event(self, data):
        """작업 스레드가 보낸 진행 이벤트(Tk 스레드에서 처리)."""
        if data.get('message'):
            self.speech_say('Working', data['message'])
            self.log('[음성 인식 모델] ' + data['message'])
        if isinstance(data.get('fraction'), (int, float)) and hasattr(self, 'speech_progress_row'):
            if not self.speech_progress_row.winfo_manager():
                self.speech_progress_row.pack(fill='x')
            self.speech_progress.set(100.0 * data['fraction'])
            self.speech_progress_label.configure(text='%d%%' % (100 * data['fraction']))

    def _manage_speech(self, key, work, message):
        if self.runner.busy('tools.subtitles') or self._speech_management_busy():
            self.speech_say('Working', '진행 중인 자막 작업 또는 설치/복구가 끝난 뒤 다시 시도하세요.')
            return
        self._speech_cancel = Event()
        self.speech_cancel_button.configure(state='normal')
        self.speech_say('Working', message, log=True)
        for button in self._speech_buttons():
            button.configure(state='disabled')
        if hasattr(self, 'subtitle_start_button'):
            self.subtitle_start_button.configure(state='disabled')

        def finish():
            self.speech_cancel_button.configure(state='disabled')
            if self.speech_progress_row.winfo_manager():
                self.speech_progress_row.pack_forget()

        def done(value):
            finish()
            self.speech_say('Ready', '완료했습니다.', log=True)
            self.refresh_speech_status(preserve_message=True)

        def failed(exc):
            finish()
            if isinstance(exc, InterruptedError):
                self.speech_say('Waiting', '중단했습니다. 다시 시작하면 받던 곳부터 이어서 받습니다.', log=True)
            else:
                self.speech_say('Failed', friendly(exc), log=True, level='error')
            self.refresh_speech_status(preserve_message=True)
        if not self.run_task(key, work, done, mutate=False, long=True, announce=False, error=failed):
            failed(RuntimeError('설치 작업을 시작하지 못했습니다. 다시 시도하세요.'))

    def _speech_cancelled(self):
        flag = getattr(self, '_speech_cancel', None)
        return bool(flag is not None and flag.is_set()) or self.runner.cancel.is_set()

    def cancel_speech_job(self):
        flag = getattr(self, '_speech_cancel', None)
        if flag is not None and self._speech_management_busy():
            flag.set()
            self.speech_say('Working', '중단 중…')

    def install_speech_engine(self):
        def log(text):
            self.services.events.emit('runtime.progress', {'service': 'speech-models', 'message': text})
        self._manage_speech(ENGINE_KEY,
                            lambda: self._engine_result(self.services.subtitles.install_engine(
                                log=log, cancelled=self._speech_cancelled)),
                            '음성 인식 엔진(whisper.cpp · ffmpeg · VAD) 설치 중… GPU 빌드는 1GB 안팎입니다.')

    @staticmethod
    def _engine_result(ok):
        if not ok:
            raise RuntimeError('엔진 설치가 완료되지 않았습니다. 활동 기록에서 원인을 확인하세요.')
        return ok

    def _selected_speech_model(self):
        selected = self.speech_model_table.selection()
        if not selected:
            self.speech_say('Failed', '아래 표에서 모델을 먼저 고르세요.')
            return None
        return selected[0]

    def download_speech_model(self):
        key = self._selected_speech_model()
        if key is None:
            return
        item = speech.model(key)

        def progress(done, total):
            if total:
                self.services.events.emit('runtime.progress', {
                    'service': 'speech-models', 'fraction': done / total,
                    'message': '%s 받는 중: %.0f / %.0f MB' % (item.key, done / 1048576, total / 1048576)})
        self._manage_speech(MODEL_KEY,
                            lambda: self.services.subtitles.install_model(key, progress=progress,
                                                                         cancelled=self._speech_cancelled),
                            '%s 받는 중(약 %d MB, 검증 후 저장)…' % (item.key, item.size_mib))

    def remove_speech_model(self):
        key = self._selected_speech_model()
        if key is None:
            return
        if not messagebox.askyesno('음성 인식 모델 삭제', speech.model(key).label +
                                   ' 모델을 이 PC에서 삭제할까요? 모든 계정에서 사용할 수 없게 됩니다.',
                                   parent=self.root):
            return
        self._manage_speech(MODEL_KEY, lambda: self.services.subtitles.remove_model(key), key + ' 삭제 중…')
