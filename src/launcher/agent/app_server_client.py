from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
from pathlib import Path
from typing import Mapping


class AppServerClient:
    """Minimal newline-delimited JSON RPC client for Open Interpreter App Server."""

    def __init__(
        self,
        command: list[str],
        env: Mapping[str, str],
        cwd: Path,
        max_queue: int = 10000,
        popen_factory=None,
    ):
        self._command = list(command)
        self._env = dict(env)
        self._cwd = Path(cwd)
        self._popen_factory = popen_factory or subprocess.Popen
        self._proc = None
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._next_id = 1
        self._pending: dict[int | str, queue.Queue] = {}
        self._messages: queue.Queue = queue.Queue(maxsize=max_queue)
        self._stopping = threading.Event()

    def start(self) -> bool:
        with self._state_lock:
            if self._proc is not None and self._proc.poll() is None:
                return False
            kwargs = {
                "stdin": subprocess.PIPE,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "bufsize": 1,
                "env": self._env,
                "cwd": str(self._cwd),
            }
            if os.name == "nt":
                kwargs["creationflags"] = 0x08000000
            try:
                self._proc = self._popen_factory(self._command, **kwargs)
            except (OSError, ValueError) as exc:
                self._proc = None
                self._emit({"method": "local/protocolError", "params": {"text": f"App Server start failed: {exc}"}})
                return False
            self._stopping.clear()
            proc = self._proc

        threading.Thread(target=self._stdout_loop, args=(proc,), daemon=True, name="oi-appserver-stdout").start()
        threading.Thread(target=self._stderr_loop, args=(proc,), daemon=True, name="oi-appserver-stderr").start()
        threading.Thread(target=self._wait_loop, args=(proc,), daemon=True, name="oi-appserver-wait").start()
        return True

    def _allocate_request(self) -> tuple[int, queue.Queue]:
        with self._state_lock:
            request_id = self._next_id
            self._next_id += 1
            waiter: queue.Queue = queue.Queue(maxsize=1)
            self._pending[request_id] = waiter
            return request_id, waiter

    def _begin_request(self, method: str, params: dict) -> tuple[int, queue.Queue]:
        request_id, waiter = self._allocate_request()
        if not self._write_json({"id": request_id, "method": method, "params": params}):
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise RuntimeError("App Server stdin is not available")
        return request_id, waiter

    def request(self, method: str, params: dict, timeout: float = 10.0) -> dict:
        request_id, waiter = self._begin_request(method, params)
        try:
            message = waiter.get(timeout=timeout)
        except queue.Empty as exc:
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise TimeoutError(f"App Server request timed out: {method}") from exc
        if "error" in message:
            raise RuntimeError(f"App Server {method} failed: {message['error']}")
        result = message.get("result")
        if not isinstance(result, dict):
            return {} if result is None else {"value": result}
        return result

    def notify(self, method: str, params: dict | None = None) -> bool:
        payload = {"method": method}
        if params is not None:
            payload["params"] = params
        return self._write_json(payload)

    def respond(self, request_id: int | str, result: dict) -> bool:
        return self._write_json({"id": request_id, "result": result})

    def _write_json(self, payload: dict) -> bool:
        proc = self._proc
        if proc is None or proc.poll() is not None or proc.stdin is None:
            return False
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        try:
            with self._write_lock:
                proc.stdin.write(line)
                proc.stdin.flush()
            return True
        except (BrokenPipeError, OSError, ValueError):
            return False

    def _handle_stdout_line(self, line: str) -> None:
        text = line.rstrip("\r\n")
        if not text:
            return
        try:
            message = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            self._emit({"method": "local/protocolError", "params": {"text": text}})
            return
        if not isinstance(message, dict):
            self._emit({"method": "local/protocolError", "params": {"text": text}})
            return
        self._handle_message(message)

    def _handle_message(self, message: dict) -> None:
        if "id" in message and ("result" in message or "error" in message) and "method" not in message:
            request_id = message.get("id")
            with self._state_lock:
                waiter = self._pending.pop(request_id, None)
            if waiter is not None:
                try:
                    waiter.put_nowait(message)
                except queue.Full:
                    pass
                return
        self._emit(message)

    def _stdout_loop(self, proc) -> None:
        stream = getattr(proc, "stdout", None)
        if stream is None:
            return
        try:
            for line in stream:
                self._handle_stdout_line(line)
        except (OSError, ValueError):
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _stderr_loop(self, proc) -> None:
        stream = getattr(proc, "stderr", None)
        if stream is None:
            return
        try:
            for line in stream:
                text = line.rstrip("\r\n")
                if text:
                    self._emit({"method": "local/stderr", "params": {"text": text}})
        except (OSError, ValueError):
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _wait_loop(self, proc) -> None:
        try:
            returncode = proc.wait()
        except Exception:
            returncode = -1
        if not self._stopping.is_set():
            self._emit({"method": "local/terminated", "params": {"returncode": returncode}})
        with self._state_lock:
            waiters = list(self._pending.values())
            self._pending.clear()
        for waiter in waiters:
            try:
                waiter.put_nowait({"error": {"message": "App Server terminated"}})
            except queue.Full:
                pass

    def _emit(self, message: dict) -> None:
        try:
            self._messages.put_nowait(message)
        except queue.Full:
            try:
                self._messages.get_nowait()
            except queue.Empty:
                pass
            try:
                self._messages.put_nowait(message)
            except queue.Full:
                pass

    def drain_messages(self, max_n: int = 200) -> list[dict]:
        out = []
        for _ in range(max_n):
            try:
                out.append(self._messages.get_nowait())
            except queue.Empty:
                break
        return out

    def stop(self, timeout: float = 3.0) -> bool:
        """Stop the child and report success only after it is observably gone."""
        self._stopping.set()
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return True
        try:
            if proc.stdin is not None and not getattr(proc.stdin, "closed", False):
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                return False
            try:
                proc.wait(timeout=timeout)
            except (subprocess.TimeoutExpired, OSError, ValueError):
                return False
        except (OSError, ValueError):
            return False
        return proc.poll() is not None

    def is_running(self) -> bool:
        proc = self._proc
        return proc is not None and proc.poll() is None

    def pid(self) -> int | None:
        proc = self._proc
        return getattr(proc, "pid", None) if proc is not None else None
