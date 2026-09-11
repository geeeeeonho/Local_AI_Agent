"""In-process events. UI subscribers should enqueue into their own UI thread."""
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import threading
from types import MappingProxyType
from typing import Mapping


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError('event payload must contain JSON-like values')


@dataclass(frozen=True)
class Event:
    topic: str
    payload: Mapping
    created_at: str


class EventBus:
    def __init__(self):
        self._lock = threading.RLock()
        self._subscribers = {}
        self._next = 0

    def subscribe(self, topic, callback):
        if not isinstance(topic, str) or not topic or not callable(callback):
            raise ValueError('a topic and callback are required')
        with self._lock:
            self._next += 1
            token = self._next
            self._subscribers[token] = (topic, callback)
        def unsubscribe():
            with self._lock:
                self._subscribers.pop(token, None)
        return unsubscribe

    def emit(self, topic: str, payload: Mapping | None = None) -> Event:
        if not isinstance(topic, str) or not topic:
            raise ValueError('event topic must not be empty')
        event = Event(topic, _freeze(payload or {}), datetime.now(timezone.utc).isoformat())
        with self._lock:
            callbacks = [callback for key, callback in self._subscribers.values() if key == topic or key == '*']
        for callback in callbacks:
            try:
                callback(event)
            except Exception:
                logging.getLogger(__name__).exception('LocalAI event subscriber failed: %s', topic)
        return event
