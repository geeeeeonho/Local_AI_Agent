"""installer.steps.app — the one copy of the program every account runs.

Each Windows account used to run LocalAI from its own checkout. Now Setup
copies the program to ``C:\\LocalAI\\app`` and every account starts it from
there through one shortcut: one version on the machine, updated in one place
by a LocalAI administrator, readable and executable - not writable - by
everyone else. The account folder ACLs stay as they are; the app inherits the
shared root's (administrators full control, every account read/execute).

**Only Git decides what is deployed.** The copy is written from the objects of
the checkout's ``HEAD`` commit - each blob hash-checked against the id the
commit names - never from the working tree. An edited file, an untracked or
git-ignored extra (a planted ``sitecustomize.py``), a symlink or submodule, a
commit that no remote branch contains, or a repository Git itself distrusts
(another account's checkout) stops the update instead. ``VERSION.json``
records the commit and every file's blob id and SHA-256
(``core.program_integrity``), and the result is checked against the commit
once more after the swap.

The copy is built beside the live one and swapped in, so an account running
the old version while an administrator updates never sees half of each.
"""
from __future__ import annotations

import compileall
import json
import os
import py_compile
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Dict, Optional

from core import program_integrity as integrity
from ..core.console import info, ok, warn

#: What the program is. Tests, caches and the user's own runtime state are not.
_TOP_LEVEL = ("src", "RUN.bat", "README.md", "STUDIO.md")
_SKIP_DIRS = {"__pycache__", "tests", ".pytest_cache", ".git", ".mypy_cache"}
_SKIP_SUFFIXES = (".pyc", ".pyo")

VERSION_FILE = integrity.VERSION_FILE

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
#: Settings a checkout's own .git/config could use to run a program when we
#: merely ask Git a question. Forced off for every call made here.
_GIT_SAFETY = (
    "-c", "core.fsmonitor=false",
    "-c", "core.hooksPath=" + os.devnull,
    "-c", "core.untrackedCache=false",
    "-c", "protocol.allow=never",
    "-c", "diff.external=",
    "-c", "core.pager=cat",
)
#: Environment that would point Git at another repository or object store.
_GIT_ENV_DROP = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                 "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CEILING_DIRECTORIES",
                 "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
                 "GIT_EXTERNAL_DIFF", "GIT_PAGER", "GIT_SSH", "GIT_SSH_COMMAND",
                 "GIT_ASKPASS", "GIT_EXEC_PATH", "GIT_NAMESPACE")


class DeploySourceError(RuntimeError):
    """The checkout cannot vouch for what would be deployed."""


def _git_env():
    env = {key: value for key, value in os.environ.items()
           if key not in _GIT_ENV_DROP and not key.startswith("GIT_CONFIG_")}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", GIT_NO_REPLACE_OBJECTS="1",
               LC_ALL="C")
    return env


def _git(source: Path, *args, input=None, timeout=60) -> bytes:
    """One hardened, non-interactive Git call; raises DeploySourceError."""
    command = ["git", "--no-pager", "--no-replace-objects", *_GIT_SAFETY,
               "-C", str(source), *args]
    try:
        result = subprocess.run(command, input=input, capture_output=True, timeout=timeout,
                                check=False, env=_git_env(), creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        raise DeploySourceError("Git을 실행할 수 없습니다: %s" % exc) from exc
    if result.returncode != 0:
        detail = (result.stderr or b"").decode("utf-8", "replace").strip()
        if "dubious ownership" in detail:
            detail = ("다른 Windows 계정이 소유한 체크아웃입니다. 관리자 계정이 소유한 "
                      "신뢰된 Git 체크아웃에서 Setup을 실행하세요. (" + detail.splitlines()[0] + ")")
        raise DeploySourceError("Git 확인 실패 (%s): %s" % (" ".join(args[:2]), detail))
    return result.stdout or b""


def _text(data: bytes) -> str:
    return data.decode("utf-8", "replace").strip()


def _deployable(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if not parts or parts[0] not in _TOP_LEVEL:
        return False
    if any(part in _SKIP_DIRS for part in parts):
        return False
    return not path.endswith(_SKIP_SUFFIXES)


def git_source(source: Path) -> dict:
    """What ``HEAD`` of the checkout at ``source`` would deploy, or why not.

    Returns ``commit``, ``tree``, ``remote``, ``branch`` and ``files``
    (``{path: blob id}``) for the deployable part of the commit.
    """
    source = Path(source)
    top = Path(_text(_git(source, "rev-parse", "--show-toplevel")))
    if not same_place(top, source):
        raise DeploySourceError("Setup 위치가 Git 저장소의 최상위가 아닙니다: %s (저장소: %s)"
                                % (source, top))
    alternates = Path(_text(_git(source, "rev-parse", "--git-path", "objects/info/alternates")))
    if not alternates.is_absolute():
        alternates = source / alternates
    try:
        borrowed = alternates.is_file() and alternates.read_text(encoding="utf-8").strip()
    except OSError:
        borrowed = True
    if borrowed:
        raise DeploySourceError("이 체크아웃은 다른 위치의 Git 객체(alternates)를 빌려 씁니다. "
                                "독립된 clone에서 Setup을 실행하세요.")
    commit = _text(_git(source, "rev-parse", "--verify", "HEAD^{commit}"))
    tree = _text(_git(source, "rev-parse", "--verify", "HEAD^{tree}"))
    pathspec = ["--", *_TOP_LEVEL, ":(exclude)src/tests"]
    dirty = _git(source, "status", "--porcelain=v1", "-z", "--untracked-files=all",
                 "--ignore-submodules=none", *pathspec)
    if dirty.strip(b"\0"):
        names = [entry[3:].decode("utf-8", "replace")
                 for entry in dirty.split(b"\0") if len(entry) > 3][:5]
        raise DeploySourceError("커밋되지 않은 변경/추가 파일이 있어 배포하지 않습니다: "
                                + ", ".join(names) + " - 커밋·푸시하거나 되돌린 뒤 다시 실행하세요.")
    remotes = _text(_git(source, "for-each-ref", "--contains", commit,
                         "--format=%(refname:short)", "refs/remotes"))
    if not remotes:
        raise DeploySourceError("HEAD 커밋(%s)이 어떤 원격 브랜치에도 없습니다. 원격 저장소에 "
                                "푸시된 커밋만 공용 프로그램으로 배포합니다." % commit[:12])
    listing = _git(source, "ls-tree", "-r", "-z", "--full-tree", commit)
    files: Dict[str, str] = {}
    for entry in listing.split(b"\0"):
        if not entry:
            continue
        meta, _, raw_path = entry.partition(b"	")
        mode, kind, blob = meta.decode("ascii").split()
        path = raw_path.decode("utf-8")
        if not _deployable(path):
            continue
        if kind != "blob" or mode not in ("100644", "100755"):
            raise DeploySourceError("배포 대상에 일반 파일이 아닌 항목(%s %s)이 있습니다: %s"
                                    % (mode, kind, path))
        files[path] = blob
    if "RUN.bat" not in files or not any(p.startswith("src/") for p in files):
        raise DeploySourceError("커밋에 프로그램(RUN.bat, src/)이 없습니다.")
    try:
        remote = _text(_git(source, "config", "--get", "remote.origin.url"))
    except DeploySourceError:
        remote = ""
    try:
        branch = _text(_git(source, "symbolic-ref", "--short", "-q", "HEAD"))
    except DeploySourceError:
        branch = ""
    return {"commit": commit, "tree": tree, "remote": remote, "branch": branch,
            "remotes": remotes.splitlines(), "files": files}


def _read_blobs(source: Path, files: Dict[str, str]) -> Dict[str, bytes]:
    """Raw blob bytes by path, each checked against the id the commit names."""
    ids = list(dict.fromkeys(files.values()))
    out = _git(source, "cat-file", "--batch", input=("\n".join(ids) + "\n").encode("ascii"),
               timeout=300)
    blobs: Dict[str, bytes] = {}
    position = 0
    for oid in ids:
        end = out.index(b"\n", position)
        header = out[position:end].decode("ascii").split()
        if len(header) != 3 or header[0] != oid or header[1] != "blob":
            raise DeploySourceError("Git 객체를 읽지 못했습니다: %s" % oid)
        size = int(header[2])
        data = out[end + 1:end + 1 + size]
        position = end + 1 + size + 1
        if len(data) != size or integrity.git_blob_id(data) != oid:
            raise DeploySourceError("Git 객체 내용이 커밋의 해시와 다릅니다 (손상/변조): %s" % oid)
        blobs[oid] = data
    return {path: blobs[oid] for path, oid in files.items()}


def _write_tree(staging: Path, files: Dict[str, str], blobs: Dict[str, bytes]) -> Dict[str, dict]:
    manifest = {}
    for rel, oid in sorted(files.items()):
        data = integrity.to_deployed(rel, blobs[rel])
        target = staging.joinpath(*PurePosixPath(rel).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        entry = {"git": oid, "sha256": integrity.sha256(data)}
        if data != blobs[rel]:
            entry["eol"] = "crlf"
        manifest[rel] = entry
    return manifest


def _record_bytecode(staging: Path, manifest: Dict[str, dict]) -> None:
    for path in sorted((staging / "src").rglob("*.pyc")):
        rel = path.relative_to(staging).as_posix()
        manifest[rel] = {"git": None, "sha256": integrity.sha256(path.read_bytes())}


def source_revision(source: Path) -> Optional[str]:
    try:
        result = subprocess.run(["git", *_GIT_SAFETY, "-C", str(source), "rev-parse",
                                 "--short", "HEAD"],
                                capture_output=True, text=True, timeout=10, check=False,
                                env=_git_env(), creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    value = (result.stdout or "").strip()
    return value if result.returncode == 0 and value else None


def same_place(left: Path, right: Path) -> bool:
    try:
        return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(str(Path(right).resolve()))
    except OSError:
        return False


def verify_deployed(target: Path, source: Optional[Path] = None) -> list:
    """Problems with the copy at ``target``: drift, and - given the checkout
    it came from - any difference from the commit its manifest names."""
    target = Path(target)
    manifest = integrity.load(target)
    problems = integrity.verify(target, manifest)
    if source is not None and not problems:
        try:
            snapshot = git_source(source)
        except DeploySourceError as exc:
            return [str(exc)]
        if manifest.get("commit") != snapshot["commit"]:
            return ["설치본 커밋(%s)이 체크아웃 HEAD(%s)와 다릅니다"
                    % (str(manifest.get("commit"))[:12], snapshot["commit"][:12])]
        problems = integrity.verify_against_tree(manifest, snapshot["files"])
    return problems


def deploy(source: Path, target: Path) -> bool:
    """Copy the program from ``source`` (a Git checkout) to ``target``.

    True when ``target`` now holds this commit, verified - including when
    Setup is already running from it and that copy still matches its
    manifest. Failure leaves the previous copy untouched.
    """
    source, target = Path(source), Path(target)
    if same_place(source, target):
        manifest = integrity.load(target)
        if manifest is None or integrity.is_legacy(manifest):
            # Deployed before manifests existed: keep it working; the next
            # Setup from a Git checkout records one.
            warn("공용 프로그램에 무결성 정보가 없습니다. Git 체크아웃에서 관리자 Setup을 "
                 "실행하면 기록됩니다: %s" % target)
            return True
        problems = integrity.verify(target, manifest)
        if problems:
            warn("공용 프로그램 무결성 확인 실패: " + "; ".join(problems[:4]))
            warn("신뢰된 Git 체크아웃에서 관리자 Setup을 실행해 다시 배포하세요.")
            return False
        info("공용 프로그램에서 실행 중입니다 (무결성 확인): %s" % target)
        return True
    if not (source / "src").is_dir() or not (source / "RUN.bat").is_file():
        warn("프로그램 원본을 찾지 못해 공용 프로그램을 갱신하지 않았습니다: %s" % source)
        return False
    try:
        snapshot = git_source(source)
        blobs = _read_blobs(source, snapshot["files"])
    except DeploySourceError as exc:
        warn("공용 프로그램을 배포하지 않았습니다: %s" % exc)
        return False
    staging = target.with_name(target.name + ".new")
    retired = target.with_name(target.name + ".old")
    try:
        for leftover in (staging, retired):
            if leftover.exists():
                shutil.rmtree(leftover, ignore_errors=True)
        staging.mkdir(parents=True)
        files = _write_tree(staging, snapshot["files"], blobs)
        # Every account runs this copy, and none of them may write into it, so
        # bytecode has to exist before the first start instead of each account
        # compiling its own in memory. Hash-checked pycs do not depend on the
        # file times Git does not keep.
        compileall.compile_dir(str(staging / "src"), quiet=1, workers=0,
                               invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH)
        _record_bytecode(staging, files)
        manifest = {
            "schema": integrity.SCHEMA,
            "revision": snapshot["commit"][:7],
            "commit": snapshot["commit"],
            "tree": snapshot["tree"],
            "branch": snapshot["branch"],
            "remote": snapshot["remote"],
            "remote_branches": snapshot["remotes"],
            "deployed_at": datetime.now(timezone.utc).isoformat(),
            "source": str(source),
            "files": files,
        }
        (staging / VERSION_FILE).write_text(json.dumps(
            manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        problems = (integrity.verify(staging, manifest)
                    + integrity.verify_against_tree(manifest, snapshot["files"]))
        if problems:
            raise OSError("배포본 검증 실패: " + "; ".join(problems[:4]))
        if target.exists():
            os.replace(target, retired)
        os.replace(staging, target)
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        if retired.exists() and not target.exists():
            try:
                os.replace(retired, target)
            except OSError:
                pass
        warn("공용 프로그램을 갱신하지 못했습니다 (다른 계정이 실행 중일 수 있습니다): %s" % exc)
        return False
    shutil.rmtree(retired, ignore_errors=True)
    problems = integrity.verify(target)
    if problems:
        warn("배포 후 공용 프로그램 무결성 확인 실패: " + "; ".join(problems[:4]))
        return False
    ok("공용 프로그램 갱신: %s (%s · Git 커밋과 일치 확인)" % (target, snapshot["commit"][:12]))
    return True


def installed_revision(target: Path) -> Optional[str]:
    try:
        data = json.loads((Path(target) / VERSION_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get("revision") if isinstance(data, dict) else None
    return str(value) if value else None


__all__ = ["deploy", "installed_revision", "same_place", "source_revision", "VERSION_FILE",
           "git_source", "verify_deployed", "DeploySourceError"]
