"""Live session control for the GUI automation agent.

The controller owns serialized AgentService calls, slash commands, session
resume, controlled model/policy restarts, stop/restart actions and event
routing. UI construction stays in ``launcher.actions.agent_chat``.
"""
from __future__ import annotations

from typing import Callable

from .events import AgentEvent, AgentEventType

PostFn = Callable[[str, str], None]
DispatchFn = Callable[[str, Callable[[], None]], None]
BoolCallback = Callable[[], bool | None]
ModelCallback = Callable[[str], bool | None]
ApprovalCallback = Callable[[AgentEvent], bool]


class ChatSessionController:
    def __init__(
        self,
        service,
        *,
        post: PostFn,
        dispatch: DispatchFn,
        restart_model: ModelCallback | None = None,
        reload_policy: BoolCallback | None = None,
        restart_service: BoolCallback | None = None,
        new_session: BoolCallback | None = None,
        stop_service: Callable[[], None] | None = None,
        approval_decider: ApprovalCallback | None = None,
        on_terminated: Callable[[], None] | None = None,
    ) -> None:
        self.service = service
        self._post = post
        self._dispatch = dispatch
        self._restart_model = restart_model
        self._reload_policy = reload_policy
        self._restart_service = restart_service
        self._new_session = new_session
        self._stop_service = stop_service
        self._approval_decider = approval_decider
        self._on_terminated = on_terminated

    def _run(self, name: str, fn: Callable[[], None]) -> None:
        self._dispatch(name, fn)

    def _policy_summary(self) -> str:
        try:
            from . import folder_policy

            allowed = folder_policy.list_allowed()
            denied = folder_policy.list_denied()
            lines = ["[허용]"] + (["  " + item for item in allowed] if allowed else ["  (없음)"])
            lines += ["[금지]"] + (["  " + item for item in denied] if denied else ["  (없음)"])
            lines += ["마운트 예정 " + str(len(folder_policy.mounts_for())) + "개 · 변경 반영: /reload"]
            return "\n".join(lines)
        except Exception as exc:
            return "정책 조회 실패: " + str(exc)

    def handle_slash(self, text: str) -> bool:
        raw = (text or "").strip()
        if not raw.startswith("/"):
            return False

        parts = raw.split(None, 1)
        command = parts[0].lower()
        arg = parts[1].strip().strip('"').strip("'") if len(parts) > 1 else ""

        if command in ("/help", "/?", "/명령"):
            self._post(
                "system",
                "폴더 명령: /folders 목록 · /allow <경로> · /deny <경로> · "
                "/unallow <경로> · /undeny <경로> · /reload 변경반영 · "
                "/model <태그> 모델변경 · /session 세션ID · /resume <세션ID> · /new 새대화",
            )
            return True

        if command == "/session":
            session_id = self.service.session_id()
            if session_id:
                self._post("system", "현재 세션: " + str(session_id))
            else:
                self._post("system", "현재 backend는 구조화 세션 ID를 제공하지 않습니다.")
            return True

        if command == "/resume":
            if not arg:
                self._post("system", "사용법: /resume <thread-id>")
                return True
            if self.service.resume(arg):
                self._post("system", "세션 이어가기 완료: " + str(self.service.session_id() or arg))
            else:
                self._post("warn", "세션 이어가기 실패: " + arg)
            return True

        if command in ("/new", "/새대화"):
            if self._new_session is None:
                self._post("warn", "새 대화 시작 기능을 사용할 수 없습니다.")
                return True

            def new_session() -> None:
                result = self._new_session()
                self._post("system" if result else "error", "새 대화를 시작했습니다." if result else "새 대화 시작 실패")

            self._run("new", new_session)
            return True

        if command in ("/model", "/모델"):
            if not arg:
                self._post("system", "사용법: /model <태그>  예: /model qwen2.5-coder:7b")
                return True
            if self._restart_model is None:
                self._post("error", "모델 변경 기능을 사용할 수 없습니다.")
                return True

            def restart_model() -> None:
                result = self._restart_model(arg)
                if result:
                    self._post("system", "모델 변경 완료: " + arg)
                else:
                    self._post("error", "모델 변경 실패: " + arg)

            self._run("model", restart_model)
            return True

        if command in ("/reload", "/적용", "/remount"):
            if self._reload_policy is None:
                self._post("error", "폴더 정책 재적용 기능을 사용할 수 없습니다.")
                return True

            def reload_policy() -> None:
                result = self._reload_policy()
                if result is True:
                    self._post("system", "폴더 정책 반영 완료")
                elif result is False:
                    self._post("system", "폴더 정책 변경 없음 — 재기동하지 않습니다.")
                else:
                    self._post("error", "폴더 정책 반영 실패")

            self._run("reload", reload_policy)
            return True

        try:
            from . import folder_policy
        except Exception:
            self._post("error", "folder_policy 를 불러올 수 없습니다")
            return True

        if command in ("/folders", "/폴더", "/list"):
            self._post("system", self._policy_summary())
            return True

        if command in ("/allow", "/허용"):
            if not arg:
                self._post("warn", "사용법: /allow <폴더경로>")
                return True
            result = folder_policy.add_allowed(arg)
            self._post(
                "system",
                {
                    "ok": "허용 추가됨: " + arg + "  (반영: /reload)",
                    "exists": "이미 허용에 있음",
                    "denied": "금지 목록과 충돌 - 추가 불가",
                    "fail": "저장 실패",
                }.get(result, str(result)),
            )
            return True

        if command in ("/deny", "/금지"):
            if not arg:
                self._post("warn", "사용법: /deny <폴더경로>")
                return True
            result = folder_policy.add_denied(arg)
            self._post(
                "system",
                {
                    "ok": "금지 추가됨: " + arg + "  (반영: /reload)",
                    "exists": "이미 금지에 있음",
                    "fail": "저장 실패",
                }.get(result, str(result)),
            )
            return True

        if command in ("/unallow", "/허용해제"):
            if not arg:
                self._post("warn", "사용법: /unallow <폴더경로>")
                return True
            self._post(
                "system",
                "허용 제거됨: " + arg + "  (반영: /reload)"
                if folder_policy.remove_allowed(arg)
                else "저장 실패",
            )
            return True

        if command in ("/undeny", "/금지해제"):
            if not arg:
                self._post("warn", "사용법: /undeny <폴더경로>")
                return True
            self._post(
                "system",
                "금지 제거됨: " + arg + "  (반영: /reload)"
                if folder_policy.remove_denied(arg)
                else "저장 실패",
            )
            return True

        self._post("warn", "알 수 없는 명령: " + command + "  (/help)")
        return True

    def handle_input(self, text: str) -> None:
        if self.handle_slash(text):
            return

        def send() -> None:
            if not self.service.send(text):
                self._post("warn", "에이전트가 실행 중이 아니거나 현재 turn이 처리 중입니다")

        self._run("send", send)

    def stop(self) -> None:
        def stop_service() -> None:
            if self._stop_service is not None:
                self._stop_service()
                return
            if self.service.cancel():
                self._post("system", "현재 turn 중단 요청 완료")
                return
            self.service.stop(timeout=2.0)

        self._run("stop", stop_service)

    def restart(self) -> None:
        if self._restart_service is None:
            self._post("error", "재시작 기능을 사용할 수 없습니다.")
            return

        def restart_service() -> None:
            ok = self._restart_service()
            self._post("system" if ok else "error", "에이전트 재시작 완료" if ok else "재시작 실패 — Docker/Ollama 상태를 확인하세요.")

        self._run("restart", restart_service)

    def _handle_approval(self, event: AgentEvent) -> None:
        if event.request_id is None:
            return
        accepted = False
        if self._approval_decider is not None:
            try:
                accepted = bool(self._approval_decider(event))
            except Exception:
                accepted = False
        decision = "accept" if accepted else "decline"
        if self.service.approve(event.request_id, decision):
            self._post("system", "작업 승인" if accepted else "작업 거절")
        else:
            self._post("error", "승인 응답 전송 실패")

    def handle_event(self, event: AgentEvent) -> None:
        if event.type is AgentEventType.APPROVAL_REQUIRED:
            self._handle_approval(event)
        elif event.type is AgentEventType.TERMINATED:
            self._post("terminated", event.content)
            if self._on_terminated is not None:
                self._on_terminated()
        elif event.type is AgentEventType.TEXT_DELTA:
            self._post("stdout", event.content)
        elif event.type is AgentEventType.REASONING:
            self._post("info", event.content)
        elif event.type in (
            AgentEventType.TOOL_STARTED,
            AgentEventType.TOOL_PROGRESS,
            AgentEventType.TOOL_COMPLETED,
            AgentEventType.FILE_CHANGED,
            AgentEventType.SESSION_STARTED,
            AgentEventType.STARTED,
            AgentEventType.STATUS,
        ):
            self._post("system", event.content)
        elif event.type is AgentEventType.ERROR:
            self._post("error", event.content)
        elif event.type is AgentEventType.WARNING:
            self._post("warn", event.content)
        else:
            self._post(event.source_level or event.type.value, event.content)

    def poll_once(self, max_n: int = 100) -> int:
        try:
            events = self.service.poll_events(max_n=max_n)
        except Exception:
            return 0
        count = 0
        for event in events:
            try:
                self.handle_event(event)
            except Exception as exc:
                self._post("error", "이벤트 처리 실패 (%s): %s" % (event.type.value, exc))
            count += 1
        return count


__all__ = ["ChatSessionController"]
