"""선택형 로컬 캘린더 MCP(stdio) 어댑터.

기본 캘린더/알림 서비스에는 MCP가 필요하지 않습니다. 이 모듈을 직접 실행할 때만
외부 mcp 패키지를 로드합니다. 수정 도구는 환경변수로 별도 허용해야 합니다.
"""
from __future__ import annotations

import os


def create_server(service):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError('로컬 MCP 서버를 사용하려면 mcp Python 패키지를 별도로 설치하세요.') from exc

    server = FastMCP('LocalAI Calendar')

    @server.tool()
    def list_calendar_items() -> list[dict]:
        """이 Windows 계정의 로컬 일정과 할 일을 조회합니다."""
        return service.list_items()

    def require_write():
        if os.environ.get('LOCALAI_CALENDAR_MCP_WRITE', '').strip() != '1':
            raise PermissionError('MCP 일정 변경은 기본 차단입니다. LOCALAI_CALENDAR_MCP_WRITE=1을 명시하세요.')

    @server.tool()
    def add_calendar_item(title: str, start_at: str, kind: str = 'event',
                          repeat: str = 'none', remind_minutes: int | None = None,
                          note: str = '') -> dict:
        """새 로컬 일정이나 할 일을 추가합니다. 시각은 YYYY-MM-DD HH:MM (PC 로컬)."""
        require_write()
        return service.add(title=title, start_at=start_at, kind=kind,
                           repeat=repeat, remind_minutes=remind_minutes, note=note)

    @server.tool()
    def complete_calendar_task(item_id: str, done: bool = True) -> str:
        """로컬 할 일의 완료 상태를 변경합니다."""
        require_write()
        service.set_done(item_id, done)
        return 'updated'

    @server.tool()
    def delete_calendar_item(item_id: str) -> str:
        """선택한 로컬 일정이나 할 일을 삭제합니다."""
        require_write()
        service.delete(item_id)
        return 'deleted'

    return server


def main():
    from project_paths import USER_DATA_DIR
    from services.tools.calendar import CalendarService
    service = CalendarService(USER_DATA_DIR / 'tools' / 'calendar' / 'items.json')
    create_server(service).run(transport='stdio')


if __name__ == '__main__':
    main()