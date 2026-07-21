# -*- coding: utf-8 -*-
"""파일 이동/정리 도구 — 안전한 이동·복사·확장자별 정리.

move(src, dst) / copy(src, dst) / organize_by_ext(folder) / list_files(folder)
"""
from __future__ import annotations
import os
import shutil


def move(src, dst):
    os.makedirs(os.path.dirname(os.path.abspath(dst)) or ".", exist_ok=True)
    return shutil.move(src, dst)


def copy(src, dst):
    os.makedirs(os.path.dirname(os.path.abspath(dst)) or ".", exist_ok=True)
    if os.path.isdir(src):
        return shutil.copytree(src, dst)
    return shutil.copy2(src, dst)


def list_files(folder="."):
    out = []
    for name in sorted(os.listdir(folder)):
        p = os.path.join(folder, name)
        out.append({"name": name, "is_dir": os.path.isdir(p),
                    "size": os.path.getsize(p) if os.path.isfile(p) else 0})
    return out


def organize_by_ext(folder="."):
    """폴더 안 파일들을 확장자 이름의 하위 폴더로 이동. 이동 목록 반환."""
    moved = []
    for name in list(os.listdir(folder)):
        p = os.path.join(folder, name)
        if not os.path.isfile(p):
            continue
        ext = (os.path.splitext(name)[1].lstrip(".") or "no_ext").lower()
        sub = os.path.join(folder, ext)
        os.makedirs(sub, exist_ok=True)
        shutil.move(p, os.path.join(sub, name))
        moved.append((name, ext))
    return moved
