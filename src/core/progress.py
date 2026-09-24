"""Adapt one progress callback to the logger protocol services expect.

Long waits in this product are reported two different ways. Runtimes take a
single ``log(message)`` callable; the Docker and Ollama services take an object
with ``info``/``ok``/``warn``/``error``. Where those meet, the logger argument
was simply left out, and a ninety-second Docker Desktop boot or a thirty-second
Ollama start ran with nothing on screen at all.
"""


class LogAdapter:
    """Wrap a ``log(message)`` callable as an info/ok/warn/error logger."""

    __slots__ = ('_log',)

    def __init__(self, log):
        self._log = log if callable(log) else (lambda message: None)

    def _say(self, prefix, message):
        try:
            self._log(prefix + str(message))
        except Exception:
            pass

    def info(self, message):
        self._say('', message)

    def ok(self, message):
        self._say('', message)

    def warn(self, message):
        self._say('주의: ', message)

    def error(self, message):
        self._say('오류: ', message)


__all__ = ['LogAdapter']
