"""Chat and Agent stores, sealed for this account whenever no session uses them.

AnythingLLM and Open Interpreter write their own files - chat history, the
document store, agent sessions - and need them in plaintext while they run.
Between sessions there is no reason for them to be readable, so each store
is sealed with this account's key (``core.vault``) once its session has
stopped, and opened again just before the next one starts.

The order is the safety: open before anything reads or writes the store,
seal only after the runtime that used it is verifiably gone. A store whose
runtime could not be confirmed stopped is left as it is - plaintext is a
privacy gap; sealing under a running container is lost data.
"""
from __future__ import annotations

from pathlib import Path

from core import vault


class SessionStores:
    def __init__(self, data: Path, events=None):
        data = Path(data)
        self.events = events
        self.stores = {
            # AnythingLLM's own downloaded embedder weights are public and
            # large; everything else in its storage is the user's.
            'chat': (vault.Store('chat', data / 'anythingllm', exclude=('models',)),),
            # The host home also holds the installed interpreter packages.
            'agent': (vault.Store('agent-host', data / 'interpreter' / 'host',
                                  exclude=('packages',)),
                      vault.Store('agent-sandbox', data / 'interpreter' / 'sandbox')),
        }
        self._holds = {}

    def _log(self, kind, message):
        if self.events is not None:
            self.events.emit('runtime.progress', {
                'service': 'chat' if kind == 'chat' else 'agent',
                'message': str(message)})

    def open(self, kind: str) -> None:
        """Unseal ``kind``'s stores for a session. Raises if one cannot be opened."""
        if kind in self._holds:
            return
        say = lambda message: self._log(kind, message)
        opened = []
        try:
            for store in self.stores[kind]:
                if store.sealed():
                    say('암호화된 %s 저장소를 여는 중…' % store.name)
                try:
                    opened.append(store.open(log=say))
                except vault.Undecryptable as exc:
                    # Sealed with a key this account no longer has. Keep the
                    # archive (never delete what cannot be read) and start empty.
                    kept = vault.set_aside(store.archive)
                    say('이 계정의 현재 키로 풀 수 없는 %s 저장소를 %s 로 옮기고 빈 저장소로 '
                        '시작합니다 (%s).' % (store.name, kept.name, exc))
                    opened.append(store.open(log=say))
        except Exception:
            for hold in opened:
                if hold is not None:
                    hold.release()
            raise
        self._holds[kind] = opened

    def close(self, kind: str) -> bool:
        """Release and seal ``kind``'s stores after its runtime has stopped."""
        holds = self._holds.pop(kind, [])
        say = lambda message: self._log(kind, message)
        sealed = True
        for index, store in enumerate(self.stores[kind]):
            hold = holds[index] if index < len(holds) else None
            if hold is not None:
                hold.release()
            if not vault.enabled():
                continue
            if store.has_plaintext():
                say('%s 저장소를 이 계정 전용으로 잠그는 중…' % store.name)
            try:
                sealed = store.seal_if_idle(log=say) and sealed
            except Exception as exc:
                say('%s 저장소를 잠그지 못했습니다: %s' % (store.name, exc))
                sealed = False
        return sealed

    def recover(self, idle) -> list:
        """Seal stores a crashed session left open, where ``idle(kind)`` says safe.

        ``idle`` must answer True only when that kind's runtime is provably not
        running (Docker down, or its container absent).
        """
        sealed = []
        if not vault.enabled():
            return sealed
        for kind, stores in self.stores.items():
            if kind in self._holds:
                continue
            pending = [store for store in stores if store.has_plaintext()]
            if not pending:
                continue
            try:
                if not idle(kind):
                    continue
            except Exception:
                continue
            for store in pending:
                try:
                    if store.seal_if_idle(log=lambda m, k=kind: self._log(k, m)):
                        sealed.append(store.name)
                except Exception as exc:
                    self._log(kind, '%s 저장소를 잠그지 못했습니다: %s' % (store.name, exc))
        return sealed


__all__ = ['SessionStores']
