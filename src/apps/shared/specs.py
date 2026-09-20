"""One navigation model for the integrated and standalone applications."""
from dataclasses import dataclass


@dataclass(frozen=True)
class AppSpec:
    title: str
    primary: str
    pages: tuple[str, ...]


SPECS = {
    'studio': AppSpec('LocalAI Studio', 'home', ('home','chat','agent','models','network','system','settings','setup')),
    'chat': AppSpec('LocalAI Chat', 'chat', ('chat','models','network','settings','setup')),
    'interpreter': AppSpec('LocalAI Interpreter', 'agent', ('agent','models','network','settings','setup')),
    'setup': AppSpec('LocalAI Setup', 'setup', ('setup','models','network','system','settings')),
}
LABELS = {
    'home': 'Home', 'chat': 'Chat', 'projects': 'Projects', 'agent': 'Agent',
    'models': 'Models', 'network': 'Network', 'system': 'System',
    'settings': 'Settings', 'setup': 'Setup / Repair',
}
DESCRIPTIONS = {
    'home': '하나의 LocalAI, 함께 쓰는 모델과 서비스',
    'chat': 'AnythingLLM 채팅 · 문서 · Workspace · RAG',
    'projects': '문서 Workspace와 코드 작업 폴더를 연결합니다.',
    'agent': 'Open Interpreter · 명령 · 승인 · 파일 변경',
    'models': '모델 → manifest → blob · 공유 / 전용 용량',
    'network': 'Direct / WARP / Tor / Block · 실행 중인 정책은 임의로 바뀌지 않습니다.',
    'system': '실제 서비스 상태와 현재 저장 경로',
    'settings': 'Session > Project > App > Global',
    'setup': '설치 · 모델 관리 · 진단 · 복구',
}


# Purpose, position and typography all carry hierarchy; not color alone.
NAV_GROUPS = (
    ('WORK', ('chat', 'agent')),
    ('MANAGE', ('models', 'setup')),
    ('GENERAL', ('home', 'network', 'system', 'settings')),
)


def navigation_groups(app):
    pages = SPECS[app].pages
    return tuple((title, tuple(key for key in keys if key in pages))
                 for title, keys in NAV_GROUPS if any(key in pages for key in keys))


def nav_style(key, selected=False):
    kind = {'chat': 'Chat.', 'agent': 'Agent.', 'models': 'Manage.', 'setup': 'Manage.'}.get(key, '')
    return ('Selected.' if selected else '') + kind + 'Nav.TButton'
