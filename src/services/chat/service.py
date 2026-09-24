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
            log('[1/5] Network preparation: ' + str(mode))
            selected = self.network.prepare(mode, cancel=cancel)
            log('[1/5] Network ready: ' + selected.value)

            if cancel is not None and cancel():
                raise RuntimeError('Chat startup cancelled.')

            log('[2/5] Ollama service and shared model store check')
            self.inference.ensure_ready(log=log)
            log('[2/5] Ollama ready')

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
