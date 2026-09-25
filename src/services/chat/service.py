"""Shared Chat startup. AnythingLLM remains the real Chat/Knowledge UI."""
from core.network.policy import NetworkMode


class ChatService:
    def __init__(self, backend, inference, network, search, events):
        self.backend, self.inference = backend, inference
        self.network, self.search, self.events = network, search, events
        self.started = False
        self.attempted = False
        self.url = None
        self.model = ''

    def start(self, mode, *, model='', search=True, cancel=None):
        log = lambda message: self.events.emit(
            'runtime.progress', {'service': 'chat', 'message': str(message)}
        )
        network_was_prepared = self.network.mode is not None
        search_was_attempted = self.search.attempted
        try:
            # Before any of it. If Ollama is already answering and has nothing
            # local to serve, none of the five steps can end in a usable Chat -
            # and the first of them brings WARP up, which is most of the wait.
            # The check is skipped when Ollama is not answering yet, because
            # then starting it is step 2's job and the answer is not knowable.
            self._require_a_local_model(log)

            log('[1/5] Network preparation: ' + str(mode))
            selected = self.network.prepare(mode, cancel=cancel)
            log('[1/5] Network ready: ' + selected.value)

            if cancel is not None and cancel():
                raise RuntimeError('Chat startup cancelled.')

            log('[2/5] Ollama service and shared model store check')
            self.inference.ensure_ready(log=log)
            # Whether a local model exists is knowable here, and it decides
            # whether the rest is worth doing. Asking at the last step meant
            # WARP, Docker, SearXNG and AnythingLLM all came up first, twice
            # over, before saying there was nothing to run.
            local = self._require_a_local_model(log)
            log('[2/5] Ollama ready' + (' · 로컬 모델 %d개' % len(local) if local else ''))

            log('[3/5] Docker / AnythingLLM image check')
            prepare = getattr(self.backend, 'chat_prepare', None)
            if callable(prepare):
                prepare(log, cancel)
            if not self.backend.chat_image_exists():
                raise RuntimeError('AnythingLLM is not installed. Run RUN.bat --install or Setup / Repair.')
            log('[3/5] Docker ready / AnythingLLM image ready')

            if cancel is not None and cancel():
                raise RuntimeError('Chat startup cancelled.')

            log('[4/5] Search preparation')
            if search and selected is not NetworkMode.BLOCK:
                try:
                    if not self.search.start(selected.value):
                        log('[4/5] Search unavailable; local Chat/RAG remains available.')
                    else:
                        log('[4/5] Search ready')
                except Exception as exc:
                    log('[4/5] Search unavailable: ' + str(exc))
            else:
                log('[4/5] Search skipped for Block/local-only mode')

            log('[5/5] Starting AnythingLLM and verifying container -> Ollama -> selected model')
            self.attempted = True
            self.url = self.backend.chat_start(model, log, cancel)
            if not self.url:
                raise RuntimeError('AnythingLLM startup failed.')
            self.model = str(getattr(self.backend, 'chat_active_model', lambda: model)() or model or '')
            self.started = True
            log('[5/5] Chat connection verified' + ((': ' + self.model) if self.model else ''))
            self.events.emit('chat.ready', {
                'url': self.url, 'mode': selected.value, 'model': self.model,
            })
            return self.url
        except Exception as exc:
            # If this attempt was the only owner of the runtime, clean up enough
            # state to make the next click a genuinely fresh retry. Never tear
            # down a network that was already serving another active session.
            if not network_was_prepared:
                cleanup_ok = True
                if self.attempted:
                    try:
                        cleanup_ok = bool(self.backend.chat_stop())
                    except Exception:
                        cleanup_ok = False
                    if cleanup_ok:
                        self.started = False
                        self.attempted = False
                        self.url = None
                        self.model = ''
                if cleanup_ok and not search_was_attempted and self.search.attempted:
                    try:
                        cleanup_ok = bool(self.search.stop())
                    except Exception:
                        cleanup_ok = False
                if cleanup_ok:
                    self.network.reset()
            log('Chat preparation failed: ' + str(exc))
            raise

    NO_LOCAL_MODEL = ('Chat에 사용할 로컬 Ollama 모델이 없습니다. '
                      '모델 화면에서 모델을 먼저 받으세요. '
                      '(Ollama 클라우드 모델은 선택한 네트워크 정책 밖으로 나가므로 쓰지 않습니다.)')

    def _require_a_local_model(self, log):
        """Stop early when there is nothing this machine could answer with.

        ``None`` from the inference service means the question could not be
        asked - Ollama may simply not be running yet - and that is not the same
        as "none installed", so it is not treated as one.

        "Installed but invisible" is not the same either, and it is the case
        that matters most: telling someone with three models on disk to go and
        download one sends them to the wrong screen to do the wrong thing. The
        runtime knows the difference, so its words are used when it has them.
        """
        local = self.inference.local_models()
        if local is not None and not local:
            raise RuntimeError(self._no_model_reason())
        return local

    def _no_model_reason(self) -> str:
        explain = getattr(self.inference, 'describe_models', None)
        if callable(explain):
            try:
                detail = explain()
            except Exception:
                detail = None
            if detail:
                return str(detail)
        return self.NO_LOCAL_MODEL

    def stop(self):
        if not self.attempted:
            return True
        if not self.backend.chat_stop():
            return False
        self.started = False
        self.attempted = False
        self.url = None
        self.model = ''
        return True
