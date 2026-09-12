# -*- coding: utf-8 -*-
"""user_data — persistent data root management (USER_DATA_v1).

The repository-root ``user_data/`` directory remains the single product-owned
location for settings, logs, chat data, and interpreter runtime state. Open
Interpreter thread IDs are the Agent session source of truth; this module does
not create or scan any product-owned per-session state file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from project_paths import PROJECT_ROOT

__all__ = [
    "project_root", "root",
    "settings_dir", "logs_dir", "chat_dir", "interpreter_dir",
    "ensure_all",
    "save_json", "load_json",
]

INTERPRETER_KINDS = ("sandbox", "host")

_LAYOUT = (
    "settings",
    "logs",
    "chat",
    "interpreter/sandbox",
    "interpreter/host",
)


def project_root() -> Path:
    """Project root; keep LLM_PROJECT_ROOT override for tests/portable runs."""
    ov = os.environ.get("LLM_PROJECT_ROOT")
    if ov:
        return Path(ov).resolve()
    return PROJECT_ROOT


def root() -> Path:
    """Return the user_data root without creating it."""
    return project_root() / "user_data"


def _sub(*parts: str) -> Path:
    """Return a child directory and create it lazily."""
    d = root().joinpath(*parts)
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def settings_dir() -> Path:
    return _sub("settings")


def logs_dir() -> Path:
    return _sub("logs")


def chat_dir() -> Path:
    return _sub("chat")


def interpreter_dir(kind: str = "sandbox") -> Path:
    """Runtime state directory for sandbox/host interpreter assets."""
    k = kind if kind in INTERPRETER_KINDS else "sandbox"
    return _sub("interpreter", k)


_README = (
    "This user_data directory is preserved when the program exits.\n"
    "\n"
    "  settings/            product settings\n"
    "  logs/                execution/session logs\n"
    "  chat/                chat-related persistent data\n"
    "  interpreter/sandbox/ Open Interpreter sandbox runtime state/assets\n"
    "  interpreter/host/    Open Interpreter host runtime state/assets\n"
    "\n"
    "Agent session identity and resume are owned by Open Interpreter thread IDs.\n"
    "Per-session JSON files left by older versions are not treated as active\n"
    "sessions and are not deleted automatically.\n"
)


def ensure_all() -> Path:
    """Create the user_data skeleton idempotently and return its root."""
    r = root()
    r.mkdir(parents=True, exist_ok=True)
    for rel in _LAYOUT:
        (r / rel).mkdir(parents=True, exist_ok=True)
    readme = r / "README.txt"
    if not readme.exists():
        try:
            readme.write_text(_README, encoding="utf-8")
        except OSError:
            pass
    return r


def save_json(path: Any, obj: Any) -> bool:
    """Atomically store JSON using a temporary file and os.replace."""
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(
            json.dumps(obj, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, p)
        return True
    except Exception:
        try:
            if tmp.exists():  # type: ignore[name-defined]
                tmp.unlink()
        except Exception:
            pass
        return False


def load_json(path: Any, default: Any = None) -> Any:
    """Load JSON and return default on failure."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default
