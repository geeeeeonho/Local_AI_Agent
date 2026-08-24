from __future__ import annotations


PRIVACY_CLAUSE = (
    "\n\n[개인정보 보호 — 반드시 준수]\n"
    "사용자의 개인정보로 판단되는 어떤 요소도 인터넷·외부 서비스·원격 저장소로 전송, 게시, "
    "업로드, 공유하지 마십시오. 여기에는 이름, 주소, 전화번호, 이메일, 계정/아이디, 비밀번호, "
    "API 키·토큰, 결제·금융 정보, 주민등록·여권 등 식별번호, 로컬 파일 경로·파일 내용, "
    "시스템·네트워크 식별 정보(호스트명, 사용자명, IP, MAC 등), 위치 정보가 포함됩니다.\n"
    "웹 검색·API 요청·외부 전송이 필요할 때에도 이러한 개인정보를 쿼리·페이로드·URL 에 절대 "
    "포함하지 마십시오. 개인정보가 필요한 외부 작업은 수행하지 말고 사용자에게 위험을 알리고 "
    "확인을 받으십시오. 확신이 없으면 전송하지 않는 쪽을 선택하십시오."
)


NATIVE_TOOL_GUIDANCE = (
    "\n\n[Open Interpreter 도구 사용]\n"
    "파일 탐색·수정, 명령 실행, 코드 실행과 검증은 Open Interpreter가 제공하는 기본 도구를 "
    "우선 사용하십시오. 존재하지 않는 전역 Python 함수나 별도 사전 도구를 가정하지 마십시오.\n"
    "현재 정보가 필요한 인터넷 검색은 `local_search` MCP 서버의 `search` 도구를 사용하고, "
    "검색 결과의 공개 웹페이지 본문이 필요하면 `fetch_page`를 사용하십시오. 이 검색 경로는 "
    "Local_AI_Agent의 로컬 SearXNG를 사용합니다. 검색어에는 개인정보, 로컬 파일 내용, 비밀값, "
    "식별 가능한 로컬 경로를 포함하지 마십시오."
)


SANDBOX_GUIDANCE = (
    "\n\n[Local_AI_Agent Docker sandbox]\n"
    "This session runs inside the Local_AI_Agent Docker sandbox.\n"
    "Only mounted paths are available. Do not attempt to escape the container.\n"
    "Open Interpreter built-in web search is disabled because the local Ollama provider does not provide "
    "the provider search endpoint. Use the local_search MCP tools backed by SearXNG for current external information.\n"
    "Never include private local content in search queries."
)


def build_structured_instructions(profile_message: str, *, sandbox: bool) -> str:
    text = str(profile_message or "") + PRIVACY_CLAUSE + NATIVE_TOOL_GUIDANCE
    if sandbox:
        text += SANDBOX_GUIDANCE
    return text
