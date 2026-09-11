"""One navigation model for the integrated and standalone applications."""
from dataclasses import dataclass


@dataclass(frozen=True)
class AppSpec:
    title: str
    primary: str
    pages: tuple[str, ...]


SPECS = {
    'studio': AppSpec('LocalAI Studio', 'home', ('home','chat','projects','agent','models','network','system','settings','setup')),
    'chat': AppSpec('LocalAI Chat', 'chat', ('chat','projects','models','network','settings','setup')),
    'interpreter': AppSpec('LocalAI Interpreter', 'agent', ('agent','projects','models','network','settings','setup')),
    'setup': AppSpec('LocalAI Setup', 'setup', ('setup','models','network','system','settings')),
}
LABELS = {
    'home': 'Home', 'chat': 'Chat', 'projects': 'Projects', 'agent': 'Agent',
    'models': 'Models', 'network': 'Network', 'system': 'System',
    'settings': 'Settings', 'setup': 'Setup / Repair',
}
DESCRIPTIONS = {
    'home': '\ud558\ub098\uc758 LocalAI, \ud568\uaed8 \uc4f0\ub294 \ubaa8\ub378\uacfc \uc11c\ube44\uc2a4',
    'chat': 'AnythingLLM \ucc44\ud305 \u00b7 \ubb38\uc11c \u00b7 Workspace \u00b7 RAG',
    'projects': '\ubb38\uc11c Workspace\uc640 \ucf54\ub4dc \uc791\uc5c5 \ud3f4\ub354\ub97c \uc5f0\uacb0\ud569\ub2c8\ub2e4.',
    'agent': 'Open Interpreter \u00b7 \uba85\ub839 \u00b7 \uc2b9\uc778 \u00b7 \ud30c\uc77c \ubcc0\uacbd',
    'models': '\ubaa8\ub378 \u2192 manifest \u2192 blob \u00b7 \uacf5\uc720 / \uc804\uc6a9 \uc6a9\ub7c9',
    'network': 'Direct / WARP / Tor / Block \u00b7 \uc2e4\ud589 \uc911\uc778 \uc815\ucc45\ub294 \uc784\uc758\ub85c \ubc14\ub00c\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4.',
    'system': '\uc2e4\uc81c \uc11c\ube44\uc2a4 \uc0c1\ud0dc\uc640 \ud604\uc7ac \uc800\uc7a5 \uacbd\ub85c',
    'settings': 'Session > Project > App > Global',
    'setup': '\uc124\uce58 \u00b7 \ubaa8\ub378 \uad00\ub9ac \u00b7 \uc9c4\ub2e8 \u00b7 \ubcf5\uad6c',
}
