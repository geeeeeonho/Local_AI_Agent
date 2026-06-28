# -*- coding: utf-8 -*-
"""folder_policy — 인터프리터/에이전트의 상시 허용·금지 폴더 정책 (영구 저장).

FOLDER_POLICY_v1. user_data/settings/folder_policy.json 에 보관.
샌드박스 모드에서는 '허용' 폴더만 컨테이너에 마운트되고, 마운트되지 않은
호스트 경로는 물리적으로 보이지 않으므로 '그 외 경로 금지'가 강제된다.
'금지' 목록은 (a) 실수로 허용에 추가하는 것을 막고 (b) 호스트 직접 모드의
시스템 메시지 가드로 쓰인다. stdlib 전용 · 기존 코드 의존 없음.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Tuple

_FILENAME = "folder_policy.json"


def _root() -> Path:
    # launcher/folder_policy.py → 부모의 부모가 프로젝트 루트
    return Path(__file__).resolve().parent.parent


def _store_path() -> Path:
    return _root() / "user_data" / "settings" / _FILENAME


def load() -> dict:
    p = _store_path()
    try:
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                d.setdefault("allowed", [])
                d.setdefault("denied", [])
                return d
    except Exception:
        pass
    return {"allowed": [], "denied": []}


def save(data: dict) -> bool:
    p = _store_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
        return True
    except Exception:
        return False


def _cmpkey(path: str) -> str:
    # FOLDER_POLICY_CASE_v1: 비교 전용 정규화 (Windows 대소문자 무시)
    return os.path.normcase(_norm(path))


def _norm(path: str) -> str:
    try:
        return str(Path(path).resolve())
    except Exception:
        return str(path).strip().rstrip("\\/")


def list_allowed() -> List[str]:
    return list(load().get("allowed", []))


def list_denied() -> List[str]:
    return list(load().get("denied", []))


def is_denied(path: str) -> bool:
    n = _cmpkey(path)
    for d in list_denied():
        dn = _cmpkey(d)
        if n == dn or n.startswith(dn.rstrip("\\/") + os.sep):
            return True
    return False


def add_allowed(path: str) -> str:
    n = _norm(path)
    if is_denied(n):
        return "denied"
    d = load()
    al = d.get("allowed", [])
    if any(_cmpkey(x) == _cmpkey(n) for x in al):
        return "exists"
    al.append(n)
    d["allowed"] = al
    return "ok" if save(d) else "fail"


def remove_allowed(path: str) -> bool:
    n = _norm(path)
    d = load()
    d["allowed"] = [x for x in d.get("allowed", []) if _cmpkey(x) != _cmpkey(n)]
    return save(d)


def add_denied(path: str) -> str:
    n = _norm(path)
    d = load()
    dl = d.get("denied", [])
    if any(_cmpkey(x) == _cmpkey(n) for x in dl):
        return "exists"
    dl.append(n)
    d["denied"] = dl
    d["allowed"] = [x for x in d.get("allowed", []) if _cmpkey(x) != _cmpkey(n)]  # 금지 시 허용에서 제거
    return "ok" if save(d) else "fail"


def remove_denied(path: str) -> bool:
    n = _norm(path)
    d = load()
    d["denied"] = [x for x in d.get("denied", []) if _cmpkey(x) != _cmpkey(n)]
    return save(d)


def _container_name(host: str, used: set) -> str:
    base = Path(host).name or "folder"
    safe = "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in base)
    name = safe or "folder"
    i = 2
    while name in used:
        name = (safe or "folder") + "_" + str(i)
        i += 1
    used.add(name)
    return name


def _plan():
    # FOLDER_POLICY_OVERLAY_v1: 마운트와 tmpfs 마스크를 동일 루프에서 산출(이름 정합 보장).
    mounts = []
    masks = []
    used = set()
    denied_keys = [_cmpkey(d) for d in list_denied()]
    denied_raw = list_denied()
    for h in list_allowed():
        try:
            hp = Path(h)
            if not hp.exists() or not hp.is_dir():
                continue
            if is_denied(str(hp)):
                continue
            real = hp.resolve()
            cname = _container_name(str(hp), used)
            cmount = "/home/agent/allowed/" + cname
            mounts.append((str(real), cmount))
            base = _cmpkey(str(real))
            for dk, draw in zip(denied_keys, denied_raw):
                if dk == base:
                    continue
                if dk.startswith(base + os.sep):
                    try:
                        rel = os.path.relpath(_norm(draw), str(real))
                    except Exception:
                        continue
                    rel_posix = rel.replace("\\", "/").strip("/")
                    if rel_posix and not rel_posix.startswith(".."):
                        masks.append(cmount + "/" + rel_posix)
        except Exception:
            continue
    return mounts, masks


def mounts_for():
    """허용 폴더 -> (호스트경로, 컨테이너경로). 그 외 경로는 물리 차단."""
    return _plan()[0]


def tmpfs_masks_for():
    """허용 상위 안의 '금지' 하위를 빈 tmpfs 로 가릴 컨테이너 경로 목록."""
    return _plan()[1]


def summary() -> str:
    return "허용 " + str(len(list_allowed())) + "개 · 금지 " + str(len(list_denied())) + "개"


# ─────────────────────────────────────────────
#  관리 UI (presenter 기반)
# ─────────────────────────────────────────────
def _toast(p, msg: str) -> None:
    try:
        p.info(msg)
    except Exception:
        pass


def _remove_pick(p, items_list, remover, title: str) -> None:
    from .presenter.base import MenuItem
    if not items_list:
        _toast(p, "목록이 비어 있습니다")
        return
    mi = [MenuItem(key=str(i), title=x) for i, x in enumerate(items_list, 1)]
    mi.append(MenuItem(key="b", title="취소", separator_above=True))
    c = p.show_menu(title=title, subtitle="제거할 항목 선택", items=mi)
    if c in ("b", "q", None):
        return
    try:
        idx = int(c) - 1
        if 0 <= idx < len(items_list):
            _toast(p, "제거됨" if remover(items_list[idx]) else "저장 실패")
    except Exception:
        pass


def manage(p, env=None) -> None:
    """허용/금지 폴더 관리 UI."""
    from .presenter.base import MenuItem
    home = Path.home()
    while True:
        al = list_allowed()
        dl = list_denied()
        lines = ["[상시 허용] (샌드박스에 항상 마운트 → /home/agent/allowed/)"]
        lines += (["  " + str(i) + ". " + x for i, x in enumerate(al, 1)] if al else ["  (없음)"])
        lines.append("")
        lines.append("[금지] (허용 추가 차단 / 호스트모드 가드)")
        lines += (["  - " + x for x in dl] if dl else ["  (없음)"])
        items = [
            MenuItem(key="1", title="허용 폴더 추가"),
            MenuItem(key="2", title="허용 폴더 제거"),
            MenuItem(key="3", title="금지 폴더 추가"),
            MenuItem(key="4", title="금지 폴더 제거"),
            MenuItem(key="b", title="뒤로", separator_above=True),
        ]
        choice = p.show_menu(title="허용/금지 폴더 설정",
                             subtitle="\n".join(lines), items=items)
        if choice in ("b", "q", None):
            return
        if choice == "1":
            sel = p.prompt_path(title="허용할 폴더 선택", default=home, must_exist=True)
            if sel:
                r = add_allowed(str(sel))
                _toast(p, {"ok": "추가됨", "exists": "이미 있음",
                           "denied": "금지 목록과 충돌 — 추가 불가",
                           "fail": "저장 실패"}.get(r, r))
        elif choice == "2":
            _remove_pick(p, al, remove_allowed, "허용에서 제거")
        elif choice == "3":
            sel = p.prompt_path(title="금지할 폴더 선택", default=home, must_exist=False)
            if sel:
                r = add_denied(str(sel))
                _toast(p, {"ok": "금지에 추가됨", "exists": "이미 있음",
                           "fail": "저장 실패"}.get(r, r))
        elif choice == "4":
            _remove_pick(p, dl, remove_denied, "금지에서 제거")


def maybe_manage(p, env=None) -> None:
    """에이전트 진입 시 호출: 정책 요약 + 설정 진입 선택. 진행을 누를 때까지 반복(여러 개 설정 후 진입)."""
    from .presenter.base import MenuItem
    while True:  # FOLDER_POLICY_LIVE_v1
        items = [
            MenuItem(key="1", title="이대로 진행"),
            MenuItem(key="2", title="허용/금지 폴더 설정"),
        ]
        extra = ""
        n = len(mounts_for())
        if n:
            extra = " · 이번 실행에 마운트될 허용 폴더 " + str(n) + "개"
        c = p.show_menu(title="허용 폴더 정책", subtitle=summary() + extra, items=items)
        if c == "2":
            manage(p, env)
            continue
        return


__all__ = [
    "load", "save", "list_allowed", "list_denied", "is_denied",
    "add_allowed", "remove_allowed", "add_denied", "remove_denied",
    "mounts_for", "tmpfs_masks_for", "summary", "manage", "maybe_manage",
]
