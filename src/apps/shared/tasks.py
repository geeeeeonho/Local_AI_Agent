"""Worker ownership for Tk. Completion callbacks run only in drain(), on Tk."""
from concurrent.futures import ThreadPoolExecutor
import threading


class TaskRunner:
    def __init__(self):
        self._mutations = ThreadPoolExecutor(max_workers=1, thread_name_prefix='localai-write')
        self._reads = ThreadPoolExecutor(max_workers=2, thread_name_prefix='localai-read')
        # 몇 시간씩 걸릴 수 있는 작업(파일 번역)은 별도 스레드를 써서 화면 조회를 막지 않는다.
        self._long = ThreadPoolExecutor(max_workers=1, thread_name_prefix='localai-long')
        self._tasks = {}
        self._mutating = {}
        self.cancel = threading.Event()
        self.stopped = False

    def submit(self, key, fn, done, error, *, mutate=True, long=False):
        if self.stopped or key in self._tasks:
            return False
        pool = self._long if long else (self._mutations if mutate else self._reads)
        self._tasks[key] = (pool.submit(fn), done, error)
        self._mutating[key] = bool(mutate) and not long
        return True

    def busy(self, key=None):
        return bool(self._tasks) if key is None else key in self._tasks

    def pending(self):
        """Keys of submitted tasks that have not finished yet, in order."""
        return [key for key, (future, _done, _error) in self._tasks.items()
                if not future.done()]

    def mutations_ahead(self, key):
        """Unfinished changes submitted before ``key``, which it waits behind.

        Changes run one at a time on purpose. A change queued behind another
        one that is waiting on the user looks frozen unless this is said.
        """
        ahead = []
        for name, (future, _done, _error) in self._tasks.items():
            if name == key:
                break
            if self._mutating.get(name) and not future.done():
                ahead.append(name)
        return ahead

    def drain(self):
        for key, (future, done, error) in list(self._tasks.items()):
            if not future.done():
                continue
            del self._tasks[key]
            self._mutating.pop(key, None)
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
        self._long.shutdown(wait=True, cancel_futures=True)
        # Release unconsumed UI callbacks on the calling GUI thread. Keeping
        # these cycles could finalize Tk variables later on a worker thread.
        self._tasks.clear()
        self._mutating.clear()
