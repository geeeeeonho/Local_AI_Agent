"""services.ollama — Ollama 포터블 서비스 제어.

이 모듈은 단순히 11434 응답만 확인하지 않는다. 같은 포트에 사용자가 별도로
설치한 Ollama가 떠 있으면 그 프로세스의 환경변수/모델 저장소를 알 수 없기
때문에, 관리형 ``ollama.exe`` 인지 확인한 뒤에만 재사용한다.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol

import project_paths
from core import ollama_paths
from project_paths import MODEL_STORAGE_DIR
from .. import config


class _Logger(Protocol):
    def info(self, msg: str) -> None: ...
    def ok(self, msg: str) -> None: ...
    def warn(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...


def _same_path(left: Path, right: Path) -> bool:
    """Windows 경로의 대소문자/구분자 차이를 무시해 같은 파일인지 비교."""
    return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(
        os.path.abspath(str(right))
    )


class OllamaService:
    """프로젝트가 설치한 Ollama 포터블 서비스 제어."""

    #: 종료 정리는 프로세스당 한 번만 등록한다. 등록된 콜백은 매번 runtime state
    #: 파일을 다시 읽으므로, 그 사이에 재시작된 서버도 같은 콜백이 처리한다.
    _cleanup_registered = False

    def __init__(
        self,
        env: Path,
        logger: Optional[_Logger] = None,
        model_dir: Optional[Path] = None,
        state_dir: Optional[Path] = None,
    ):
        self.env = Path(env)
        # The broker is machine-shared under <runtime root>\ollama. Keep the
        # old attribute name because lifecycle code treats it as "ours".
        self.portable_exe = project_paths.OLLAMA_INSTALL_DIR / ollama_paths.PORTABLE_EXECUTABLE
        # The shared LocalAI broker is the canonical executable. A separately
        # installed per-user/system Ollama is never silently substituted,
        # because then another Windows account can see a different broker/store.
        self.exe = self.portable_exe
        # Which server *this account* started, and its output. The managed
        # environment beside it is shared by every account on the machine, so
        # recording a pid there let a second signed-in user read the first
        # user's pid as their own and stop a server they had not started.
        state = Path(state_dir) if state_dir is not None else project_paths.LOGS_DIR
        self.log_file = state / "ollama_run.log"
        self.runtime_state_file = state / "ollama_server.json"
        self.model_dir = Path(model_dir) if model_dir is not None else MODEL_STORAGE_DIR
        self._log = logger
        self.last_error = ""

    # ── 상태 확인 ──
    @staticmethod
    def is_running() -> bool:
        try:
            # Close it: this runs on the status poll, and a discarded response
            # holds its socket open until the garbage collector gets to it.
            with urllib.request.urlopen(
                config.OLLAMA_API_TAGS, timeout=config.OLLAMA_PROBE_TIMEOUT,
            ):
                return True
        except (urllib.error.URLError, OSError):
            return False

    def is_installed(self) -> bool:
        return self.exe.exists()

    def is_managed_running(self) -> bool:
        """부작용 없이 지금 쓸 수 있는 Ollama가 떠 있는지 확인한다.

        우리가 띄운 서버면 런타임 상태 파일로 확인하고, 공식 Ollama 처럼 우리가
        띄우지 않은 서버면 알려진 위치에서 실행 중이고 같은 저장소를 보고 있는지로
        확인한다. 후자를 제외하면 이 프로그램은 자기 서버 외에는 아무것도 못 쓴다.
        """
        if not self.is_running():
            return False
        pid = self._listener_pid()
        if pid is None:
            # PowerShell 이 없거나 느려서(또는 Windows 가 아니라서) 포트 주인을
            # 못 읽은 것이지, 서버가 죽은 것이 아니다. 응답 중인 서버를 "정지"로
            # 보고하면 상태 화면이 거짓말을 한다.
            return True
        if self._listener_is_managed(pid) and self._state_matches(pid):
            return self._managed_store_usable()
        executable = self._process_executable(pid)
        if executable is None:
            # Identity/store inspection can be unavailable across Windows
            # accounts. Do not call a responsive broker stopped unless a
            # mismatch is actually proven.
            return self._managed_store_usable()
        # A shared broker can have been started by another Windows account,
        # whose private runtime-state file is intentionally invisible here.
        return _same_path(executable, self.exe) and self._managed_store_usable()

    def known_executables(self) -> tuple:
        """Executable paths LocalAI is allowed to manage."""
        return (self.exe,)

    def _is_known(self, executable: Optional[Path]) -> bool:
        return executable is not None and any(
            _same_path(executable, known) for known in self.known_executables())

    def _state_pid(self) -> Optional[int]:
        try:
            data = json.loads(self.runtime_state_file.read_text(encoding="utf-8"))
            return int(data["pid"])
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def _launched_by_us(self, pid: Optional[int]) -> bool:
        """Did this process start that server?

        The binary path cannot answer it: now that an official Ollama is
        preferred, ``self.exe`` is what we *would* launch, and a server Windows
        started runs the very same file. The runtime state file is the only
        record of a pid we actually started.
        """
        recorded = self._state_pid()
        return pid is not None and recorded is not None and recorded == int(pid)

    def store_agrees(self, timeout: float = 5) -> Optional[bool]:
        """Is the running server using the store we resolved? None = unknown.

        There is no API for the model directory, so this compares what the
        router lists against what is actually on disk where we think it is. A
        router holding models we cannot see is pointed somewhere else.

        Both sides come from the one model-check pipeline, so this can no
        longer disagree with the model screen about what either side holds.
        """
        try:
            from integrations.ollama import inventory
            return inventory.read(self.model_dir, timeout=timeout).agreement
        except Exception:
            return None

    def locate_store(self, timeout: float = 5) -> Optional[Path]:
        """Where the running Ollama is actually keeping its models.

        There is no API for it, so this compares what the router serves against
        each store it could plausibly be using and returns the one that
        accounts for them. ``None`` means no candidate does, or the router is
        not answering.

        The point is that our resolved store is a guess about where models
        *would* go, not a fact about where this server keeps them. An Ollama
        installed the official way, with OLLAMA_MODELS never set, serves from
        ``<home>/.ollama/models`` - and reading that difference as "the server
        is pointed somewhere else, refuse" made an ordinary machine unusable.
        """
        try:
            from core import ollama_paths
            from integrations.ollama import inventory
        except Exception:
            return None
        for candidate in (self.model_dir,) + tuple(ollama_paths.store_candidates()):
            try:
                if inventory.read(Path(candidate), timeout=timeout).agreement:
                    return Path(candidate)
            except Exception:
                continue
        return None

    def local_models(self, timeout: float = 5):
        """Tags the running server can serve from this machine. None = unknown.

        Cloud tags are excluded: Ollama proxies those to its own servers, so a
        library made only of them cannot answer a prompt under Block, and a
        Chat start that counts them finds nothing to use at the last step.
        """
        try:
            from integrations.ollama import inventory
            read = inventory.read(self.model_dir, timeout=timeout, store=False)
        except Exception:
            return None
        return None if not read.router_reachable else sorted(read.local_tags)

    #: The reading, as one of a small set of situations the user can act on.
    #: "Nothing installed" and "installed but the server is not reading them"
    #: are opposite instructions, and telling a user with three models on disk
    #: to go and download one is worse than saying nothing.
    READY = 'ready'                 # the server serves what the store holds
    NOTHING_INSTALLED = 'empty'     # store and server are both empty
    STORE_NOT_READ = 'unread'       # the store holds models; the server serves none of them
    OTHER_STORE = 'elsewhere'       # the server serves from a different directory
    UNKNOWN = 'unknown'             # the question could not be answered

    def inspect_store(self, timeout: float = 5):
        """(situation, detail) for the running server and the resolved store."""
        try:
            from integrations.ollama import inventory
            read = inventory.read(self.model_dir, timeout=timeout)
        except Exception:
            return self.UNKNOWN, {}
        if not read.router_reachable:
            return self.UNKNOWN, {}
        served = sorted(read.local_tags)
        detail = {'served': served, 'store': str(self.model_dir),
                  'on_disk': sorted(read.on_disk or ()),
                  'unreachable': sorted(read.unreachable)}
        if read.agreement:
            # Agreement between two empty sides is not readiness.
            return (self.READY if served else self.NOTHING_INSTALLED), detail
        if read.agreement is None:
            return self.UNKNOWN, detail
        if not served:
            # Models are here and the server lists none of them. It is reading
            # somewhere else - the usual cause is Windows restarting Ollama from
            # its own startup entry, with no OLLAMA_MODELS in that environment.
            return self.STORE_NOT_READ, detail
        found = self.locate_store(timeout=timeout)
        if found is not None:
            detail['found'] = str(found)
        return self.OTHER_STORE, detail

    def store_fix_command(self) -> str:
        """What the user has to run so the server reads the resolved store."""
        return 'setx OLLAMA_MODELS "%s"' % self.model_dir

    def describe_store(self, timeout: float = 5) -> str:
        """One line about which store the running server is serving from."""
        situation, detail = self.inspect_store(timeout=timeout)
        if situation == self.READY:
            return "모델 저장소 일치: %s (로컬 모델 %d개)" % (
                self.model_dir, len(detail.get('served') or ()))
        if situation == self.STORE_NOT_READ:
            return ("%s 에 모델 %d개가 있는데 실행 중인 Ollama 가 그 경로를 읽고 있지 "
                    "않습니다 · Ollama 를 이 경로로 다시 시작해야 합니다"
                    % (self.model_dir, len(detail.get('on_disk') or ())))
        if situation == self.OTHER_STORE:
            found = detail.get('found')
            if found:
                return ("실행 중인 Ollama 는 %s 를 씁니다 (이 프로그램의 기준 경로는 %s)"
                        % (found, self.model_dir))
            return ("실행 중인 Ollama 의 모델이 %s 에 없습니다 — 다른 경로를 쓰고 있습니다"
                    % self.model_dir)
        if situation == self.NOTHING_INSTALLED:
            return "실행 중이지만 설치된 로컬 모델이 없습니다 · 모델 화면에서 먼저 받으세요"
        return "모델 저장소를 확인하지 못했습니다: %s" % self.model_dir

    def _managed_store_usable(self) -> bool:
        """Whether the responding broker is safe for the LocalAI single store.

        Unknown is allowed because process/store inspection can be blocked by
        Windows permissions. A proven mismatch is not: model downloads would
        otherwise land in one account's old store while the UI indexes another.
        """
        situation, _detail = self.inspect_store()
        if situation in (self.STORE_NOT_READ, self.OTHER_STORE):
            self._report_store()
            self._err("공용 Ollama가 C:\\LocalAI\\models 기준 저장소를 사용하지 않습니다.")
            self._info("Setup의 Ollama 관리에서 저장소를 맞춘 뒤 다시 실행하세요.")
            return False
        return True
    def _report_store(self) -> None:
        """Say where the models are. A mismatch is news, not a failure.

        Refusing here stopped Chat and Agent over something that does not stop
        either of them: Ollama is the router, and whatever directory it reads,
        what it lists is what a prompt reaches. Where the files live matters
        when downloading and when counting disk usage, so it is reported - and
        the model screen says it again where it is actually actionable.
        """
        situation, detail = self.inspect_store()
        if situation == self.READY:
            self._ok("실행 중인 Ollama 를 사용합니다 (로컬 모델 %d개, 저장소 일치)."
                     % len(detail.get('served') or ()))
        elif situation == self.NOTHING_INSTALLED:
            self._warn("설치된 로컬 모델이 없습니다. 모델 화면에서 먼저 받으세요.")
        elif situation == self.STORE_NOT_READ:
            held = detail.get('on_disk') or ()
            self._err("%s 에 모델 %d개가 있는데 실행 중인 Ollama 가 그 경로를 읽지 "
                      "않습니다." % (self.model_dir, len(held)))
            self._err("보이지 않는 모델: " + ', '.join(list(held)[:6]))
            self._info("모델 화면의 [Ollama 다시 시작] 을 누르면 이 경로로 다시 시작합니다. "
                       "직접 고치려면 %s 실행 후 Ollama 를 재시작하세요."
                       % self.store_fix_command())
        elif situation == self.OTHER_STORE:
            found = detail.get('found')
            if found:
                self._warn("실행 중인 Ollama 는 %s 를 씁니다." % found)
                self._info("LocalAI 공용 저장소 %s 로 맞춘 뒤 Ollama 를 재시작해야 합니다."
                           % self.model_dir)
            else:
                self._warn("실행 중인 Ollama 의 모델이 %s 에서 보이지 않습니다. "
                           "LocalAI 공용 저장소와 일치하지 않습니다." % self.model_dir)
        else:
            self._warn("실행 중인 Ollama 의 모델 저장소를 확인하지 못했습니다.")

    def _accept_unidentified_server(self) -> bool:
        """Use an unidentified listener only when no store mismatch is proven."""
        self._warn("포트 %s 소유 프로세스를 확인하지 못했습니다 — 저장소 일치 여부를 "
                   "추가 확인합니다." % config.OLLAMA_PORT)
        if not self._managed_store_usable():
            return False
        self._report_store()
        self._warn_if_cloud_enabled()
        return True

    def cloud_status(self, timeout: float = 5) -> Optional[bool]:
        """Is remote inference disabled on the running server? None = unknown.

        A server this process did not launch carries whatever policy its owner
        gave it, so ask rather than assume. /api/status answers with the
        decision and where it came from (env, Ollama's own server.json, or both).
        """
        try:
            request = urllib.request.Request(
                f"http://{config.OLLAMA_HOST}:{config.OLLAMA_PORT}/api/status")
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read(64 * 1024).decode("utf-8"))
        except Exception:
            return None
        cloud = payload.get("cloud")
        if not isinstance(cloud, dict) or not isinstance(cloud.get("disabled"), bool):
            return None
        return bool(cloud["disabled"])

    def _powershell(self, script: str) -> Optional[str]:
        """Windows 프로세스 소유권 확인용 PowerShell 한 줄 실행."""
        if os.name != "nt":
            return None
        kwargs = {
            "capture_output": True,
            "text": True,
            # 5초는 백신이 붙은 Windows 에서 PowerShell 이 처음 뜨는 시간보다
            # 짧다. 시간 초과가 곧 "포트 주인을 모른다" 가 되어 멀쩡한 Ollama 를
            # 낯선 서버로 오인하게 만들었다.
            "timeout": 15,
            "check": False,
        }
        kwargs["creationflags"] = config.WIN_CREATE_NO_WINDOW
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                **kwargs,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        value = (result.stdout or "").strip()
        return value or None

    def _listener_pid(self) -> Optional[int]:
        script = (
            "$c=Get-NetTCPConnection -LocalPort "
            f"{int(config.OLLAMA_PORT)} -State Listen -ErrorAction SilentlyContinue | "
            "Select-Object -First 1; if($c){[Console]::Out.Write($c.OwningProcess)}"
        )
        value = self._powershell(script)
        try:
            return int(value) if value else None
        except (TypeError, ValueError):
            return None

    def _process_executable(self, pid: int) -> Optional[Path]:
        value = self._powershell(
            f"$p=Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue; "
            "if($p){[Console]::Out.Write($p.Path)}"
        )
        return Path(value) if value else None

    def supervisor_pids(self) -> list:
        """Running Ollama tray applications we can place, newest listing order.

        On Windows the tray application - not the CLI - owns the server. It is
        what the Startup entry launches at login, it spawns ``ollama serve``
        with its own environment, and it replaces that child within
        milliseconds of it being killed. Stopping only the listener therefore
        changes nothing: the replacement comes back reading the same directory
        as before, which is exactly what "다시 시작 완료 · 로컬 모델 0개" was.
        """
        script = (
            "Get-Process -Name '" + ollama_paths.SUPERVISOR_PROCESS + "' "
            "-ErrorAction SilentlyContinue | ForEach-Object "
            "{ [Console]::Out.WriteLine(\"$($_.Id)|$($_.Path)\") }"
        )
        value = self._powershell(script)
        # Only a tray application sitting beside an Ollama we recognise.
        # Anything else answering to that process name is not ours to end.
        known = {os.path.normcase(os.path.abspath(str(
            ollama_paths.supervisor_beside(candidate))))
            for candidate in self.known_executables()}
        found = []
        for line in (value or "").splitlines():
            pid, _, path = line.strip().partition("|")
            if not pid.isdigit():
                continue
            if path and os.path.normcase(os.path.abspath(path)) not in known:
                continue
            found.append(int(pid))
        return found

    def stop_supervisor(self) -> bool:
        """Stop the tray applications so a restarted server stays restarted."""
        pids = self.supervisor_pids()
        if not pids:
            return True
        ok = True
        for pid in pids:
            self._info("Ollama 트레이 앱 종료: pid %d" % pid)
            if not self._kill(pid):
                ok = False
        return ok

    def _listener_is_managed(self, pid: Optional[int] = None) -> bool:
        pid = pid if pid is not None else self._listener_pid()
        if pid is None:
            return False
        executable = self._process_executable(pid)
        return executable is not None and _same_path(executable, self.exe)

    def _state_matches(self, pid: int) -> bool:
        try:
            data = json.loads(self.runtime_state_file.read_text(encoding="utf-8"))
            return (
                int(data.get("pid", -1)) == int(pid)
                and _same_path(Path(data["executable"]), self.exe)
                and _same_path(Path(data["model_storage"]), self.model_dir)
                and int(data.get("port", -1)) == int(config.OLLAMA_PORT)
            )
        except (OSError, ValueError, TypeError, KeyError):
            return False

    def _write_runtime_state(self, pid: int) -> None:
        self.runtime_state_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "pid": int(pid),
            "executable": str(self.exe.resolve()),
            "model_storage": str(self.model_dir.resolve()),
            "host": config.OLLAMA_HOST,
            "port": int(config.OLLAMA_PORT),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        temp = self.runtime_state_file.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(self.runtime_state_file)

    def _remove_runtime_state(self) -> None:
        try:
            self.runtime_state_file.unlink(missing_ok=True)
        except OSError:
            pass

    # ── 환경변수 ──
    def env_vars(self, base: Optional[dict] = None) -> dict:
        e = (base or os.environ).copy()
        # Say where the store is, because Ollama's own default is per-user and
        # would send a second Windows account to an empty library. The one thing
        # never overwritten is an OLLAMA_MODELS the user already set to this
        # same place - overriding a user's own choice was the old store's fault.
        configured = ollama_paths.configured_models_dir(e)
        if configured is None or not _same_path(configured, self.model_dir):
            e["OLLAMA_MODELS"] = str(self.model_dir)
        e["OLLAMA_HOST"] = f"{config.OLLAMA_HOST}:{config.OLLAMA_PORT}"
        # Turn the relay local-only at the source. Ollama's cloud tags are not
        # downloaded: the daemon proxies the prompt to Ollama's servers with the
        # user's credentials, which Direct/WARP/Tor/Block cannot see because the
        # daemon makes that call on its own behalf. Refusing such names at our
        # own boundary only covers requests we originate; this refuses them in
        # the server, with 403, including on the OpenAI-compatible endpoint.
        e["OLLAMA_NO_CLOUD"] = "1"
        e.setdefault("OLLAMA_MAX_LOADED_MODELS", "1")
        e.setdefault("OLLAMA_KEEP_ALIVE", "5m")
        return e

    # ── 설치 전 정리 ──
    def prepare_install(self, stop_timeout: int = 5) -> bool:
        """Validate that setup will not collide with an unrelated Ollama.

        Fresh installs no longer migrate model files, so there is no reason to
        stop the shared broker merely to run setup again. If the listener is
        the LocalAI-managed executable, another Windows account may be using it;
        reuse it and leave it running. Only an unrelated listener blocks setup.
        """
        del stop_timeout
        if not self.is_running():
            self._remove_runtime_state()
            return True

        pid = self._listener_pid()
        executable = self._process_executable(pid) if pid is not None else None
        if pid is None or executable is None:
            self._warn("포트 소유 프로세스를 확인하지 못했습니다. 응답 중인 Ollama 를 그대로 둡니다.")
            return True
        if _same_path(executable, self.exe):
            self._info("공용 LocalAI Ollama 가 이미 실행 중입니다. 종료하지 않고 재사용합니다.")
            return True

        self._err(
            "포트 %s에서 다른 Ollama가 실행 중입니다: %s"
            % (config.OLLAMA_PORT, executable)
        )
        self._err("해당 Ollama를 종료한 뒤 RUN.bat --install을 다시 실행하세요.")
        return False

    def _terminate_listener(self, pid: int) -> bool:
        """프로젝트가 설치한 exe인 경우에만 listener 프로세스를 강제 종료."""
        executable = self._process_executable(pid)
        if executable is None or not _same_path(executable, self.exe):
            self._err("Ollama 프로세스 소유권이 달라 종료하지 않았습니다.")
            return False
        return self._kill(pid)

    def _kill(self, pid: int) -> bool:
        """소유권 확인이 끝난 pid 를 실제로 종료한다."""
        try:
            if os.name == "nt":
                result = subprocess.run(
                    ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                    creationflags=config.WIN_CREATE_NO_WINDOW,
                )
                if result.returncode != 0:
                    self._err("관리형 Ollama 종료 실패: " + (result.stderr or "").strip())
                    return False
            else:
                os.kill(int(pid), 15)
        except (OSError, subprocess.SubprocessError) as exc:
            self._err(f"관리형 Ollama 종료 실패: {exc}")
            return False
        self._remove_runtime_state()
        return True

    # ── 종료 ──
    def _pid_alive(self, pid: int) -> Optional[bool]:
        """POSIX 에서 기록된 pid 가 아직 살아 있는지. None = 알 수 없음."""
        if os.name == "nt":
            return None
        try:
            os.kill(int(pid), 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except (OSError, ValueError, TypeError):
            return None
        return True

    def stop_managed(self, stop_timeout: int = 5) -> bool:
        """이 프로그램이 띄운 Ollama 만 종료한다.

        창을 닫으면 같이 꺼져야 하는 것은 우리가 켠 서버뿐이다. 사용자가 원래
        쓰던 공식 Ollama 나 Windows 가 관리하는 서비스는 여기서 절대 건드리지
        않는다. 판단 근거는 우리가 직접 남긴 runtime state 파일의 pid 이며,
        포트를 실제로 그 pid 가 잡고 있는지 한 번 더 확인한다.
        """
        recorded = self._state_pid()
        if recorded is None:
            return True
        if not self.is_running():
            self._remove_runtime_state()
            return True

        pid = self._listener_pid()
        if pid is None:
            # 포트 주인을 못 읽었다. 기록한 pid 가 확실히 살아 있을 때만 종료한다.
            # 죽어 있으면 기록만 지우고, 확인조차 못 하면 pid 재사용 위험을 감수하지
            # 않고 그대로 둔다 — 남의 프로세스를 죽이는 쪽이 훨씬 나쁘다.
            alive = self._pid_alive(recorded)
            if alive is False:
                self._remove_runtime_state()
                return True
            if alive is not True:
                self._warn("포트 소유 프로세스를 확인하지 못해 Ollama 를 그대로 둡니다.")
                return False
        elif int(pid) != int(recorded):
            # 포트 주인이 바뀌었다. 우리 서버는 이미 사라졌고 지금 응답하는
            # 것은 남의 서버다. 기록만 지우고 끝낸다.
            self._remove_runtime_state()
            return True

        self._info("이 창이 시작한 Ollama 를 종료합니다.")
        # The tray application first. Kill the server while its supervisor is
        # alive and the supervisor simply starts another one, so the program
        # would exit leaving an Ollama running that it had itself started.
        self.stop_supervisor()
        if not self._kill(int(recorded)):
            return False
        deadline = time.monotonic() + max(1, stop_timeout)
        while time.monotonic() < deadline:
            if not self.is_running():
                return True
            time.sleep(0.1)
        # 포트가 아직 응답한다면 우리가 아닌 다른 서버일 수도 있다. 실패로 보고만
        # 하고 추가로 무언가를 더 죽이지는 않는다.
        self._warn("Ollama 종료를 확인하지 못했습니다.")
        return False

    def persist_store_setting(self) -> str:
        """Best-effort machine-scope compatibility for Ollama outside LocalAI.

        The managed broker always receives OLLAMA_MODELS in its child
        environment, so LocalAI itself does not need a registry value. Never
        overwrite a user's personal OLLAMA_MODELS as a fallback; that setting
        may intentionally belong to a separately launched Ollama.
        """
        try:
            from integrations.ollama import sharing
        except Exception:
            return ''
        try:
            written = sharing.publish_machine_variable(self.model_dir)
        except Exception:
            return ''
        if written:
            self._ok("외부 Ollama 호환용 모델 경로를 시스템 설정에 저장했습니다: %s"
                     % self.model_dir)
            return 'machine'
        self._warn("시스템 범위 OLLAMA_MODELS 를 저장하지 못했습니다. "
                   "LocalAI 공용 broker는 실행 시 경로를 직접 받아 계속 동작합니다.")
        return ''

    def restart_for_store(self, stop_timeout: int = 8) -> bool:
        """Restart the running Ollama so it reads the store we resolved.

        Explicit maintenance may repair either proven mismatch: the broker is
        not reading our populated store, or it is serving models from another
        directory. Ollama takes
        OLLAMA_MODELS from its environment at startup and there is no way to
        change it in a running process, so the models stay invisible until it
        is restarted - which is what happens when Windows relaunches Ollama
        from its own startup entry, outside the environment the installer set.

        A server with models loaded is somebody's working server and is never
        touched. This one is serving nothing, and the caller asked for it.
        """
        situation, detail = self.inspect_store()
        if situation not in (self.STORE_NOT_READ, self.OTHER_STORE):
            self._info("지금은 다시 시작할 이유가 없습니다: " + self.describe_store())
            return situation in (self.READY, self.NOTHING_INSTALLED)

        pid = self._listener_pid()
        executable = self._process_executable(pid) if pid is not None else None
        if pid is None or executable is None:
            self._err("포트 소유 프로세스를 확인하지 못해 다시 시작하지 않았습니다.")
            self._info("직접 고치려면 %s 실행 후 Ollama 를 재시작하세요."
                       % self.store_fix_command())
            return False
        if not self._is_known(executable):
            self._err("알 수 없는 위치의 Ollama 라서 다시 시작하지 않았습니다: %s" % executable)
            return False

        self._info("Ollama 를 %s 경로로 다시 시작합니다." % self.model_dir)
        # The value first: whatever ends up running next has to read it, and if
        # anything below fails the setting still fixes the next login.
        self.persist_store_setting()
        supervised = not self.stop_supervisor()
        if not self._kill(pid):
            return False
        deadline = time.monotonic() + max(1, stop_timeout)
        while time.monotonic() < deadline:
            if not self.is_running():
                break
            time.sleep(0.2)
        else:
            self._err("기존 Ollama 가 종료되지 않았습니다.")
            return False
        if supervised:
            self._warn("Ollama 트레이 앱을 종료하지 못했습니다. 다시 살아날 수 있습니다.")
        if not self.ensure_running():
            return False
        situation, detail = self.inspect_store()
        if situation == self.READY:
            count = len(detail.get("served") or ())
            self._ok("다시 시작 완료 · 로컬 모델 %d개" % count)
            return True
        if situation == self.NOTHING_INSTALLED:
            # Fresh setup is allowed to repair the broker before the first
            # model pull. Empty shared storage is correct here, not a failure.
            self._ok("다시 시작 완료 · 공용 모델 저장소가 비어 있습니다.")
            return True
        self._err("다시 시작했지만 공용 모델 저장소를 정상적으로 읽지 못합니다.")
        self._info(self.describe_store())
        return False

    def register_exit_cleanup(self) -> bool:
        """Compatibility hook; the machine-shared broker survives window exit.

        Older launchers called this after starting Ollama. Keeping the method
        avoids a transition break, but registering a per-window teardown would
        let one Windows account terminate the broker while another account is
        using it.
        """
        return True

    # ── 시작 ──
    def _launch(self) -> int:
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        f = open(self.log_file, "ab")
        try:
            kwargs = {
                "stdout": f,
                "stderr": f,
                "env": self.env_vars(),
            }
            if os.name == "nt":
                kwargs["creationflags"] = config.WIN_CREATE_NO_WINDOW
            process = subprocess.Popen([str(self.exe), "serve"], **kwargs)
            return int(process.pid)
        finally:
            f.close()

    def ensure_running(self, boot_timeout: Optional[int] = None) -> bool:
        """공용 모델 경로를 쓰는 관리형 Ollama만 재사용/기동한다."""
        self.last_error = ""
        if self.is_running():
            pid = self._listener_pid()
            executable = self._process_executable(pid) if pid is not None else None
            if pid is None or executable is None:
                # 여기서 실패하는 이유는 대부분 "낯선 Ollama" 가 아니다:
                # PowerShell 이 느리거나(시간 초과), 권한이 없어 다른 계정의
                # 프로세스 경로를 못 읽거나, 애초에 Windows 가 아니다. 그때마다
                # Chat 과 Agent 를 통째로 막아 버렸다. 신원을 못 밝히면 신원 대신
                # 증거를 본다 — 저장소가 일치하는지 서버에 직접 묻는다.
                return self._accept_unidentified_server()
            if not _same_path(executable, self.exe):
                self._err(
                    "포트 %s가 LocalAI 공용 Ollama가 아닌 프로세스에 의해 사용 중입니다: %s"
                    % (config.OLLAMA_PORT, executable)
                )
                self._err("해당 Ollama를 종료한 뒤 다시 실행하세요.")
                return False

            if self._state_matches(pid):
                return True

            # 우리가 띄우지 않은 공식 Ollama 는 Windows 가 관리한다. 같은 저장소를
            # 보고 있으면 그대로 쓴다 — 중간 매개체로 쓰는 것이 목적이고, 남의
            # 서비스를 죽이는 것은 목적이 아니다.
            # The portable copy lives in this project's own folder, so nothing
            # else on the machine runs it: restarting it is restarting ours.
            # An official install may be the user's Windows service.
            ours = self._launched_by_us(pid)
            if not ours:
                # Another Windows account may have started the same canonical
                # broker. Reuse it only if it is not provably reading a
                # different model library.
                if not self._managed_store_usable():
                    return False
                self._ok("이미 실행 중인 공용 Ollama 를 사용합니다: " + str(executable))
                self._report_store()
                self._warn_if_cloud_enabled()
                return True

            # 이전 버전이 같은 포터블 exe를 다른 OLLAMA_MODELS 값으로 실행했을 수
            # 있다. 환경변수는 실행 중 프로세스에 소급 적용되지 않으므로 한 번
            # 재시작해 현재 저장소를 확실히 적용한다.
            self._warn("관리형 Ollama의 모델 저장소 설정을 갱신하기 위해 재시작합니다.")
            if not self._terminate_listener(pid):
                return False
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if not self.is_running():
                    break
                time.sleep(0.1)
            else:
                self._err("기존 관리형 Ollama가 종료되지 않았습니다.")
                return False

        if not self.is_installed():
            self._err(f"Ollama 미설치: {self.exe}")
            self._err("RUN.bat --install --install 을 다시 실행하세요.")
            return False

        self._info("Ollama 가 응답 없음 — 관리형 서비스 시작 시도…")
        try:
            launched_pid = self._launch()
        except (OSError, PermissionError) as exc:
            self._err(f"Ollama 시작 실패: {exc}")
            return False

        timeout = boot_timeout or config.OLLAMA_BOOT_TIMEOUT
        for i in range(timeout):
            if self.is_running():
                listener_pid = self._listener_pid() or launched_pid
                listener_exe = self._process_executable(listener_pid)
                if listener_exe is not None and not _same_path(listener_exe, self.exe):
                    self._err("시작 도중 다른 Ollama가 포트를 선점했습니다.")
                    return False
                self._write_runtime_state(listener_pid)
                # The broker is machine-shared. Do not tie its lifetime to the
                # account/window that happened to start it; another signed-in
                # account may already be using the same service.
                # Our child got OLLAMA_MODELS through its environment. Writing
                # it where Windows keeps it is what makes the next start - by
                # the Startup entry, the tray app or the user - read it too.
                self.persist_store_setting()
                self._ok(f"Ollama 가동 확인 ({i + 1}초)")
                return True
            time.sleep(1)

        self._err(f"Ollama 시작 실패 — 로그: {self.log_file}")
        return False

    # ── 로그 헬퍼 ──
    def _warn_if_cloud_enabled(self) -> None:
        """A relay we do not control may still route prompts off the machine."""
        if self.cloud_status() is False:
            self._warn("이 Ollama 는 클라우드 모델을 허용합니다. cloud 태그로 보낸 "
                       "요청은 Ollama 서버로 나가며 Direct/WARP/Tor/Block 이 보지 "
                       "못합니다.")
            self._warn("끄려면 OLLAMA_NO_CLOUD=1 을 설정하거나 "
                       "~/.ollama/server.json 에 disable_ollama_cloud 를 넣고 "
                       "Ollama 를 재시작하세요.")

    def _info(self, m: str):
        if self._log:
            self._log.info(m)

    def _ok(self, m: str):
        if self._log:
            self._log.ok(m)

    def _warn(self, m: str):
        if self._log:
            self._log.warn(m)

    def _err(self, m: str):
        message = str(m)
        self.last_error = (self.last_error + "\n" + message).strip()
        if self._log:
            self._log.error(message)
