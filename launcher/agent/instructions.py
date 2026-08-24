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


SANDBOX_GUIDANCE = (
    "\n\n[Local_AI_Agent Sandbox]\n"
    "This session runs inside the Local_AI_Agent Docker sandbox.\n"
    "Only mounted paths are available. Do not attempt to escape the container.\n"
    "Open Interpreter built-in web search is disabled.\n"
    "For current external information use PreTool.search.web_search, search_summary, or research.\n"
    "Prefer the local SearXNG path and never include private local content in search queries."
)


def build_structured_instructions(profile_message: str, *, sandbox: bool) -> str:
    text = str(profile_message or "") + PRIVACY_CLAUSE
    if sandbox:
        text += SANDBOX_GUIDANCE
    return text
