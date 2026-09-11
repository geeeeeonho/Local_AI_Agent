"""Tracked Interpreter session; no detached startup after the UI has closed.

The existing coordinator/controller remain the execution and approval owners.
Call operations from workers. UI consumes immutable events on its own thread.
"""
import threading
import uuid


class AgentSession:
    def __init__(self, binding, events):
        self.binding, self.events = binding, events
        self.coordinator = binding.coordinator
        self.engine = self.coordinator.service
        self.metadata = dict(binding.metadata)
        self.id = uuid.uuid4().hex
        self.closing = threading.Event()
        self.lock = threading.RLock()
        self.controller = binding.controller_factory(
            self.engine, post=self.post, dispatch=lambda name, fn: self.call(fn),
            restart_model=self.restart_model, reload_policy=self.coordinator.reload_policy,
            restart_service=lambda: self.ready(self.coordinator.restart_service()),
            new_session=lambda: self.ready(self.coordinator.new_session()),
            stop_service=self.stop_turn, approval_decider=self.approve,
            on_terminated=lambda: self.ready(False))

    def post(self, level, message):
        self.events.emit('agent.event', {'session': self.id, 'level': level, 'message': str(message)})

    def ready(self, value):
        self.events.emit('agent.ready', {'session': self.id, 'ready': bool(value),
                         'model': self.coordinator.model_tag})
        return bool(value)

    def call(self, fn):
        with self.lock:
            if not self.closing.is_set():
                return fn()
        return False

    def start(self):
        with self.lock:
            if self.closing.is_set():
                return False
            ok = bool(self.coordinator.start_current())
            if self.closing.is_set():
                self.engine.stop(timeout=3.0)
                return False
            return self.ready(ok)

    def approve(self, event):
        if self.closing.is_set():
            return False
        accepted = bool(self.binding.approval_decider(event))
        return accepted and not self.closing.is_set()

    def restart_model(self, tag):
        return self.ready(self.coordinator.restart_model(tag))

    def stop_turn(self):
        result = self.coordinator.stop_service()
        self.ready(result == 'cancelled')
        return result

    def handle_input(self, text):
        return self.call(lambda: self.controller.handle_input(text))

    def stop(self):
        return self.call(self.controller.stop)

    def restart(self):
        return self.call(self.controller.restart)

    def poll_once(self):
        # A slow approval or startup must not accumulate queued poll operations.
        if not self.lock.acquire(blocking=False):
            return 0
        try:
            return 0 if self.closing.is_set() else self.controller.poll_once(max_n=100)
        finally:
            self.lock.release()

    def close(self):
        self.closing.set()
        with self.lock:
            self.engine.stop(timeout=3.0)
            stopped = not self.engine.is_running()
            if stopped:
                self.ready(False)
            return stopped
