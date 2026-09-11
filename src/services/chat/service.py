"""Shared Chat startup. AnythingLLM remains the real Chat/Knowledge UI."""
from core.network.policy import NetworkMode


class ChatService:
    def __init__(self, backend, inference, network, search, events):
        self.backend, self.inference = backend, inference
        self.network, self.search, self.events = network, search, events
        self.started = False
        self.attempted = False
        self.url = None

    def start(self, mode, *, model='', search=True, cancel=None):
        selected = self.network.prepare(mode)
        self.inference.ensure_ready()
        if not self.backend.chat_image_exists():
            raise RuntimeError('AnythingLLM is not installed. Open Setup / Repair; '
                               'Chat does not download an image implicitly.')
        log = lambda message: self.events.emit('runtime.progress',
                                {'service': 'chat', 'message': str(message)})
        if cancel is not None and cancel():
            raise RuntimeError('Chat startup cancelled.')
        if search and selected is not NetworkMode.BLOCK:
            try:
                if not self.search.start(selected.value):
                    log('Search unavailable; local Chat/RAG remains available.')
            except Exception as exc:
                log('Search unavailable: ' + str(exc))
        self.attempted = True
        self.url = self.backend.chat_start(model, log, cancel)
        if not self.url:
            raise RuntimeError('AnythingLLM startup failed.')
        self.started = True
        self.events.emit('chat.ready', {'url': self.url, 'mode': selected.value})
        return self.url

    def stop(self):
        if not self.attempted:
            return True
        if not self.backend.chat_stop():
            return False
        self.started = False
        self.attempted = False
        self.url = None
        return True
