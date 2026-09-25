"""installer.core.filesystem — 환경 폴더 구조와 설치 식별 정보 관리."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional

from project_paths import (ACCOUNT_ROOT, ENV_DIRNAME, LEGACY_ENV_DIRNAME,
                           LEGACY_MODEL_DIRS, LOGS_DIRNAME, MODEL_STORAGE_DIR,
                           USER_DATA_DIRNAME)

from . import relocate
from .console import section, ok, warn


INSTALL_MANIFEST = "LOCAL_AI_AGENT_INSTALL.json"


def ensure_shared_model_access(model_dir: Path, windows: Optional[bool] = None) -> bool:
    """다른 로컬 사용자도 공용 모델을 읽을 수 있도록 최소 권한을 보장한다.

    정본은 ``integrations.ollama.sharing`` 이다. 설치 때 한 번만이 아니라
    나중에도 확인·복구할 수 있어야 해서 그쪽으로 옮겼고, 여기서는 설치
    화면이 쓰는 이름만 유지한다.
    """
    from integrations.ollama import sharing
    if sharing.ensure_readable(model_dir, windows=windows):
        return True
    warn("공용 모델 폴더 읽기 권한 설정 실패")
    return False


def publish_shared_model_dir(model_dir: Path, windows: Optional[bool] = None) -> bool:
    """다른 Windows 계정도 같은 저장소를 보도록 시스템 환경변수에 기록한다.

    읽기 권한만으로는 부족하다. 다른 계정의 Ollama 는 자기 프로필 밑
    ``.ollama\\models`` 를 보므로, 시스템 범위 ``OLLAMA_MODELS`` 가 있어야
    같은 모델을 가리킨다.

    관리자 권한이 필요하다. 실패해도 설치를 중단하지 않는다 — 이 계정에서는
    실행 시 주입하는 값으로 계속 동작하고, 모델 화면에서 나중에 고칠 수 있다.
    """
    from integrations.ollama import sharing
    if sharing.publish_machine_variable(model_dir, windows=windows):
        return True
    warn("시스템 범위 OLLAMA_MODELS 설정 실패")
    warn("이 계정에서는 정상 동작하지만, 다른 Windows 계정은 같은 모델을 "
         "보지 못합니다. 모델 화면의 '모든 계정 공용으로 고치기' 를 "
         "관리자 권한으로 한 번 실행하세요.")
    return False


def legacy_model_stores(env: Path, models: Path) -> list:
    """이 프로젝트가 예전에 모델을 두던 위치들. 최근 것부터.

    ``C:\\LocalAI\\models`` 는 바로 이전 릴리스가 쓰던 자리이고,
    ``C:\\LLM_Models`` 는 Ollama 가 위치를 갖기 전에 강제하던 저장소다. 둘 다
    Ollama 눈에는 안 보이므로, 설치기가 찾아서 옮겨 줘야 수십 GB 가 사라진
    것처럼 보이지 않는다.
    """
    out = []
    for candidate in tuple(LEGACY_MODEL_DIRS) + (Path(env) / "llm_models",):
        candidate = Path(candidate)
        if candidate != models and candidate not in out:
            out.append(candidate)
    return out


def _report_relocation(result, label: str) -> None:
    """옮긴 결과를 사람이 읽을 수 있게 알린다. 확인까지 마친 것만 ok 로."""
    if result.problem:
        warn(result.problem)
        return
    if result.moved_from is not None:
        ok("  %-20s %s → %s (%d개 / %s 확인)"
           % (label + " 이동", result.moved_from, result.target, result.files,
              relocate.human_bytes(result.total_bytes)))
    elif result.promoted:
        ok("  %-20s → %s (중단됐던 이전을 마무리했습니다)"
           % (label + " 이동", result.target))
    if result.leftovers:
        warn(
            "옮기지 못하고 남은 예전 %s 데이터가 있습니다: " % label
            + " / ".join(str(path) for path in result.leftovers)
            + " / 새 위치가 이미 사용 중이라 자동 병합하지 않습니다: %s" % result.target
        )


def _migrate_legacy_models(env: Path, models: Path) -> None:
    """예전 저장소들을 지금 쓰는 위치로 안전하게 옮긴다.

    같은 볼륨에서는 rename, 다른 볼륨에서는 staging 복사 → 완료 marker →
    원본 삭제 → 승격. 어느 지점에서 중단돼도 다음 실행이 완성본과 부분
    복사본을 구분한다. 자세한 규칙은 ``installer.core.relocate`` 에 있다.
    """
    models = Path(models)
    result = relocate.relocate(legacy_model_stores(Path(env), models), models,
                               label="models")
    _report_relocation(result, "models")


def runtime_root_sources(project_root: Path, root: Path,
                         account: Optional[Path] = None) -> dict:
    """무엇이 어디에서 어디로 와야 하는지. 이름 -> (후보들, 목적지).

    두 번의 이사를 한 번에 처리한다. 하나는 체크아웃 밖으로 — 체크아웃은
    사용자가 내려받은 폴더라 이름이 바뀌거나 통째로 옮겨지고, OneDrive
    아래라면 수십 GB 가 클라우드로 동기화된다. 다른 하나는 루트 안에서
    계정 폴더로 — 설정·대화·추적 기록은 이 PC 를 함께 쓰는 다른 Windows
    계정이 읽을 것이 아니다.
    """
    project_root, root = Path(project_root), Path(root)
    account = Path(account) if account is not None else ACCOUNT_ROOT
    return {
        "environment": ([project_root / LEGACY_ENV_DIRNAME,
                         project_root / ENV_DIRNAME],
                        root / ENV_DIRNAME),
        "user_data": ([root / USER_DATA_DIRNAME,
                       project_root / USER_DATA_DIRNAME],
                      account / USER_DATA_DIRNAME),
        "logs": ([root / LOGS_DIRNAME], account / LOGS_DIRNAME),
        # The agent worked on the user's own files in there. Listed after
        # "environment" so the move out of the checkout has already happened
        # by the time this one looks for it.
        "workspace": ([root / ENV_DIRNAME / "agent" / "workspace",
                       project_root / LEGACY_ENV_DIRNAME / "agent" / "workspace"],
                      account / "workspace"),
    }


def migrate_runtime_root(project_root: Path, root: Path,
                         account: Optional[Path] = None) -> dict:
    """예전 위치에 남은 환경·사용자 데이터·로그를 제자리로 옮긴다.

    설치/복구를 실행할 때마다 한 번 확인한다. 옮길 것이 없으면 아무 말도
    하지 않고, 옮겼으면 개수와 용량까지 확인한 뒤 보고한다.
    """
    project_root, root = Path(project_root), Path(root)
    account = Path(account) if account is not None else ACCOUNT_ROOT
    results: Dict[str, object] = {}
    plan = runtime_root_sources(project_root, root, account)
    announced = False
    for name, (candidates, target) in plan.items():
        candidates = [Path(c) for c in candidates if Path(c) != Path(target)]
        if _same_dir(project_root, root) and name == "environment":
            continue        # 개발용 체크아웃 자체가 루트인 경우
        if not any(c.exists() for c in candidates) and \
                not relocate.staging_for(target).exists():
            continue
        if not announced:
            section("기존 설치를 제자리로 옮기는 중 · %s" % root)
            announced = True
        result = relocate.relocate(candidates, target, label=name)
        results[name] = result
        _report_relocation(result, name)
    return results


def _same_dir(left: Path, right: Path) -> bool:
    try:
        return Path(left).resolve() == Path(right).resolve()
    except OSError:
        return str(left) == str(right)


def create_environment(env: Path, model_dir: Optional[Path] = None,
                       account_root: Optional[Path] = None) -> Dict[str, Path]:
    """관리 환경 트리와 공용 모델 저장소를 생성해 경로 dict를 반환한다.

    모델은 프로젝트 체크아웃과 분리된 Ollama 공용 저장소
    ``C:\\Ollama\\models`` 를 기본으로 사용한다. 예전 ``C:\\LLM_Models``
    저장소는 비어 있는 공용 저장소로 안전하게 이전한다. 테스트나 관리형
    배포에서는 ``model_dir`` 로 명시적으로 재정의할 수 있다.
    """
    try:
        from ..i18n import t
        section(t("install.create_dirs"))
    except Exception:
        section("Creating environment folders")

    env = Path(env)
    models = Path(model_dir) if model_dir is not None else MODEL_STORAGE_DIR
    account = Path(account_root) if account_root is not None else ACCOUNT_ROOT
    _migrate_legacy_models(env, models)

    paths = {
        "env":                   env,
        "ollama":                env / "ollama_runtime",
        "models":                models,
        "chat":                  env / "chat_ui",
        "agent":                 env / "agent",
        "sandbox":               env / "agent" / "sandbox",
        # The agent's default working folder holds the user's own files, so it
        # is theirs, not the machine's.
        "workspace":             account / "workspace",
        "open_interpreter":      env / "open_interpreter",
        "open_interpreter_bin":  env / "open_interpreter" / "bin",
        "open_interpreter_home": env / "open_interpreter" / "home",
        "searxng":               env / "searxng",
        "scripts":               env / "scripts",
        "logs":                  env / "logs",
        # Private to this Windows account. Settings, projects, chat history and
        # every agent trace are a record of what one person asked an AI to do.
        "account":               account,
        "user_data":             account / USER_DATA_DIRNAME,
        "session_logs":          account / LOGS_DIRNAME,
    }
    for name, p in paths.items():
        try:
            p.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            if name == "models":
                raise RuntimeError(
                    f"공용 모델 저장소를 만들 권한이 없습니다: {p}. "
                    "관리자 계정에서 RUN.bat --install을 한 번 실행하거나 폴더 권한을 확인하세요."
                ) from exc
            raise
        ok(f"  {name:<20} → {p}")

    # 기본 경로일 때만 기계 공용으로 만든다. 명시적으로 지정된 경로는
    # 호출자의 것이므로 권한이나 시스템 환경변수를 건드리지 않는다.
    if model_dir is None:
        ensure_shared_model_access(models)
        publish_shared_model_dir(models)
    ensure_private_account(account)
    return paths


ACCOUNT_MARKER = "ACCOUNT.txt"


def name_the_account(account: Path) -> None:
    """Record whose folder this is, in the account's real name.

    The folder name has to be ASCII and space-free - it ends up in a
    ``docker -v`` argument - so a Korean or spaced Windows account name is
    replaced by a fingerprint, and ``users\\user-9c6b9b1b`` tells nobody
    anything. The name itself goes inside, where no path rule applies.
    """
    from core import accounts
    marker = Path(account) / ACCOUNT_MARKER
    try:
        marker.write_text(
            "%s\n\n이 폴더는 위 Windows 계정 전용입니다.\n"
            "설정·프로젝트·대화·추적 기록·세션 로그가 들어 있고, 이 PC 의 다른\n"
            "계정은 읽을 수 없습니다. 모델은 공용이라 ..\\..\\models 에 한 벌만\n"
            "있습니다 — 계정마다 다시 받지 않습니다.\n" % accounts.current_name(),
            encoding="utf-8")
    except OSError:
        pass


def ensure_private_account(account: Path) -> Optional[bool]:
    """이 계정 폴더를 다른 Windows 계정이 못 읽게 잠근다.

    바로 옆 모델 저장소는 일부러 ``BUILTIN\\Users`` 읽기를 허용한다 — 그래야
    두 번째 계정이 수십 GB 를 다시 받지 않는다. 그 밑에 만들어진 폴더는 그
    허용을 상속하므로, 자리만 옮겨서는 개인 기록이 개인 것이 되지 않는다.
    상속을 끊고 확인까지 한다.
    """
    from integrations.windows import privacy
    name_the_account(account)
    state = privacy.ensure_private(account)
    if state is True:
        ok("  %-20s → %s (이 계정 전용)" % ("account", account))
    elif state is False:
        warn("개인 기록 폴더를 이 계정 전용으로 잠그지 못했습니다: %s" % account)
        warn("이 PC 의 다른 Windows 계정이 설정·대화·추적 기록을 읽을 수 있습니다.")
    return state


def write_install_manifest(
    paths: Dict[str, Path],
    project_root: Path,
    status: str,
    components: Iterable[str] = (),
    failed_components: Iterable[str] = (),
    skipped_components: Iterable[str] = (),
) -> Path:
    """설치 루트에 사람이 읽을 수 있는 설치 식별 JSON을 기록한다."""
    manifest = paths["env"] / INSTALL_MANIFEST
    now = datetime.now(timezone.utc).isoformat()

    installed_at = now
    if manifest.exists():
        try:
            previous = json.loads(manifest.read_text(encoding="utf-8"))
            installed_at = previous.get("installed_at", now)
        except (OSError, ValueError, TypeError):
            pass

    data = {
        "schema_version": 2,
        "product": "Local AI Agent",
        "repository": "geeeeeonho/Local_AI_Agent",
        "managed_environment": True,
        "status": status,
        "project_root": str(Path(project_root).resolve()),
        "environment_path": str(paths["env"].resolve()),
        "model_storage": str(paths["models"].resolve()),
        "model_storage_access": (
            "builtin-users-read-execute-requested; existing-acl-preserved"
        ),
        "components": list(components),
        "failed_components": list(failed_components),
        "skipped_components": list(skipped_components),
        "installed_at": installed_at,
        "updated_at": now,
        "note": "This directory is managed by Local AI Agent RUN.bat --install.",
    }
    manifest.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest
