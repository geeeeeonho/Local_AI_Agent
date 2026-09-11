"""Worker ownership for Tk. Completion callbacks run only in drain(), on Tk."""
from concurrent.futures import ThreadPoolExecutor
import threading


class TaskRunner:
    def __init__(self):
        self._mutations = ThreadPoolExecutor(max_workers=1, thread_name_prefix='localai-write')
        self._reads = ThreadPoolExecutor(max_workers=2, thread_name_prefix='localai-read')
        self._tasks = {}
        self.cancel = threading.Event()
        self.stopped = False

    def submit(self, key, fn, done, error, *, mutate=True):
        if self.stopped or key in self._tasks:
            return False
        pool = self._mutations if mutate else self._reads
        self._tasks[key] = (pool.submit(fn), done, error)
        return True

    def busy(self, key=None):
        return bool(self._tasks) if key is None else key in self._tasks

    def drain(self):
        for key, (future, done, error) in list(self._tasks.items()):
            if not future.done():
                continue
            del self._tasks[key]
            try:
                value = future.result()
            except Exception as exc:
                error(exc)
            else:
                try:
                    done(value)
                except Exception as exc:
                    error(exc)

    def shutdown(self):
        self.cancel.set()
        self.stopped = True
        self._mutations.shutdown(wait=True, cancel_futures=True)
        self._reads.shutdown(wait=True, cancel_futures=True)
