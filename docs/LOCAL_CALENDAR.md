# 로컬 일정·할 일·알림

Studio → Tools에서 **일정·할 일**과 **알림·리마인더**를 서로 독립된 도구로 사용합니다.

- 일정·할 일: 날짜·시간·메모·알림 설정, 반복 일정(일간/주간/월간), 완료 처리, 삭제
- 알림·리마인더: Windows 계정별 백그라운드 실행기 수동 시작 및 로그인 자동 시작(HKCU Run) 등록/해제
- 로컬 저장: `C:\LocalAI\users\<계정>\user_data\tools\calendar\items.json`
- 알림 상태: 위 일정 파일의 `last_alert`; 중복 실행 방지는 동일 폴더의 잠금 파일
- 개인 알림 진단: `C:\LocalAI\users\<계정>\logs\reminder_worker.log`
- Windows 기록 보호: 개인 계정의 ACL과 DPAPI를 사용하는 `JsonStore` / `core.vault`. DPAPI를 쓸 수 없는 Windows 환경에는 평문으로 저장하지 않습니다.

외부 캘린더 MCP는 **기본 기능이 아닙니다**. `services/tools/calendar_mcp.py`는 로컬 일정에 접근하는 선택적 stdio MCP 어댑터이며, 설치 시 `mcp` 패키지가 별도로 필요합니다. Google Calendar나 Outlook 동기화 및 OAuth는 구현하지 않았습니다. MCP 쓰기는 `LOCALAI_CALENDAR_MCP_WRITE=1` 환경변수를 사용자가 명시했을 때만 허용합니다.

Windows에서 사용자 계정으로 Studio를 실행한 뒤 ‘지금 알림 실행’을 클릭해야 알림 프로세스가 실행됩니다. 자동 시작을 등록하면 다음 로그인 때 실행합니다. GUI 알림은 해당 계정의 대화형 세션이 있어야 합니다. 절전·종료·화면 잠금에는 즉각적인 알림이 보장되지 않으며, 놓친 알림은 최대 12시간까지 재검사합니다.

일정 데이터는 이 PC의 로컬 시간으로 저장하며 시간대 자동 변환 및 반복 할 일은 지원하지 않습니다. 월말 반복은 해당 월 마지막 날로 조정합니다.

테스트: `PYTHONPATH=src python -m pytest -q src/tests/test_calendar_tools.py src/tests/test_private_record_security.py`. 보안 정책의 완전한 검증에는 **Windows 두 계정으로 실제 경로 접근 거부 및 암호화 검사**가 별도로 필요합니다.
