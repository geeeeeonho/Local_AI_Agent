import json
import queue
import subprocess
from pathlib import Path

from launcher.agent.app_server_client import AppServerClient


class Sink:
    def __init__(self):
        self.lines = []
        self.closed = False

    def write(self, value):
        self.lines.append(value)
        return len(value)

    def flush(self):
        return None

    def close(self):
        self.closed = True


class FakeProc:
    def __init__(self):
        self.stdin = Sink()
        self.stdout = None
        self.stderr = None
        self.returncode = None
        self.pid = 1234
        self.terminated = 0
        self.killed = 0

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated += 1
        self.returncode = 0

    def kill(self):
        self.killed += 1
        self.returncode = -9

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class KillRequiredProc(FakeProc):
    def __init__(self):
        super().__init__()
        self.wait_calls = 0

    def terminate(self):
        self.terminated += 1

    def wait(self, timeout=None):
        self.wait_calls += 1
        if self.returncode is None and self.killed == 0:
            raise subprocess.TimeoutExpired("interpreter", timeout)
        return self.returncode


class StubbornProc(KillRequiredProc):
    def kill(self):
        self.killed += 1

    def wait(self, timeout=None):
        self.wait_calls += 1
        raise subprocess.TimeoutExpired("interpreter", timeout)


def _client(proc=None):
    client = AppServerClient(["interpreter", "app-server"], {}, Path("."))
    client._proc = proc or FakeProc()
    return client


def test_write_request_uses_monotonic_jsonl_ids():
    client = _client()
    first_id, first_waiter = client._begin_request("initialize", {"x": 1})
    second_id, _ = client._begin_request("thread/start", {"y": 2})

    assert first_id == 1
    assert second_id == 2
    assert isinstance(first_waiter, queue.Queue)
    payloads = [json.loads(line) for line in client._proc.stdin.lines]
    assert payloads == [
        {"id": 1, "method": "initialize", "params": {"x": 1}},
        {"id": 2, "method": "thread/start", "params": {"y": 2}},
    ]


def test_response_is_correlated_and_notification_is_queued():
    client = _client()
    request_id, waiter = client._begin_request("initialize", {})

    client._handle_message({"id": request_id, "result": {"ok": True}})
    assert waiter.get_nowait() == {"id": request_id, "result": {"ok": True}}

    client._handle_message({"method": "thread/started", "params": {"thread": {"id": "t1"}}})
    assert client.drain_messages() == [
        {"method": "thread/started", "params": {"thread": {"id": "t1"}}}
    ]


def test_server_request_response_uses_result_payload():
    client = _client()
    assert client.respond(77, {"decision": "accept"}) is True
    assert json.loads(client._proc.stdin.lines[-1]) == {
        "id": 77,
        "result": {"decision": "accept"},
    }


def test_malformed_json_becomes_protocol_error_event():
    client = _client()
    client._handle_stdout_line("not-json")
    [message] = client.drain_messages()
    assert message["method"] == "local/protocolError"
    assert "not-json" in message["params"]["text"]


def test_pid_and_running_follow_process_state():
    client = _client()
    assert client.pid() == 1234
    assert client.is_running() is True
    client._proc.returncode = 5
    assert client.is_running() is False


def test_stop_returns_true_only_after_process_is_gone():
    proc = FakeProc()
    client = _client(proc)

    assert client.stop(timeout=0.1) is True
    assert proc.terminated == 1
    assert proc.killed == 0
    assert proc.poll() is not None


def test_stop_kills_then_waits_again_when_terminate_times_out():
    proc = KillRequiredProc()
    client = _client(proc)

    assert client.stop(timeout=0.1) is True
    assert proc.terminated == 1
    assert proc.killed == 1
    assert proc.wait_calls == 2
    assert proc.poll() == -9


def test_stop_returns_false_if_process_survives_kill():
    proc = StubbornProc()
    client = _client(proc)

    assert client.stop(timeout=0.1) is False
    assert proc.terminated == 1
    assert proc.killed == 1
    assert proc.wait_calls == 2
    assert proc.poll() is None
