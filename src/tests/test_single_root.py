"""Everything this product owns lives in one folder, and gets there safely.

The install used to be scattered: the managed environment and ``user_data``
inside whatever folder the user unzipped the download into, the model store in
Ollama's own ``C:\\Ollama\\models``, session logs in a third place decided by
walking up the source tree. Each module composed its own path from a "project
root", so moving one of them moved three quarters of the install and the rest
kept writing where it always had.

These tests hold the layout to one root and hold the move to it to the only
standard worth having for forty gigabytes of downloads: interrupt it anywhere
and nothing is lost, and when it finishes, the count is checked rather than
assumed.
"""
import ast
import os
from pathlib import Path

import pytest

from core import runtime_root
from installer.core import filesystem, relocate

SRC = Path(__file__).resolve().parents[1]


# ── the layout ────────────────────────────────────────────────────────────

def test_every_directory_the_product_writes_to_is_under_the_root(monkeypatch, tmp_path):
    monkeypatch.setenv('LOCAL_AI_ROOT', str(tmp_path / 'root'))
    monkeypatch.setenv('LOCAL_AI_ACCOUNT', 'Tester')
    monkeypatch.delenv('LLM_MODEL_DIR', raising=False)
    monkeypatch.delenv('OLLAMA_MODELS', raising=False)
    import project_paths
    root = tmp_path / 'root'
    assert project_paths.runtime_dir() == root
    # Shared: one copy per machine, straight off the root.
    for resolved in (project_paths.env_dir(), project_paths.model_dir()):
        assert resolved.parent == root, resolved
    # Private: this account's, and inside the root all the same.
    account = project_paths.account_dir()
    assert account.parent == root / 'users'
    for resolved in (project_paths.user_data_dir(), project_paths.logs_dir(),
                     project_paths.workspace_dir()):
        assert resolved.parent == account, resolved


def composed_runtime_names(tree):
    """Names joined onto a path with ``/`` - ``something / "user_data"``.

    Only the two that name a branch of the root are watched. ``env / "logs"``
    or ``user_data.root() / "models"`` hangs a subfolder off a base that is
    already resolved; the mistake being guarded against is a module deciding
    for itself where the root's own ``user_data`` or environment folder is.
    """
    watched = {'user_data', 'llm_environment'}
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)):
            continue
        right = node.right
        if isinstance(right, ast.Constant) and right.value in watched:
            found.append((right.lineno, right.value))
    return found


def test_the_modules_that_write_ask_for_the_path_instead_of_building_it():
    """A module that composes ``<root>/user_data`` itself is the whole bug.

    ``launcher.core.user_data`` said ``project_root() / "user_data"``,
    ``settings_store`` said it again, ``lifelog`` walked the source tree for a
    folder called ``llm_environment``, and ``model_roles`` climbed two
    directories from its own file and landed on ``src/user_data`` - a folder
    nothing else ever reads, so a registry.json written there was silently
    ignored. Four answers, one machine.

    The layout belongs to ``core.runtime_root`` and is handed out by
    ``project_paths``; the files listed here are the ones allowed to know it.
    """
    allowed = {
        'project_paths.py',                     # hands out every path
        'core/runtime_root.py',                 # owns the layout
        'core/ollama_paths.py',                 # the store's own rules
        'installer/core/filesystem.py',         # creates the tree
        'installer/core/relocate.py',           # moves the old tree into it
        'launcher/core/user_data.py',           # the user_data subtree
        # These three take an explicit root meaning "the whole install is
        # here", which is how a portable run and the tests express themselves.
        'launcher/settings_store.py',
        'launcher/agent/interpreter_backend.py',
        'services/desktop.py',
        'integrations/legacy/desktop.py',
    }
    offenders = []
    for path in sorted(SRC.rglob('*.py')):
        relative = path.relative_to(SRC)
        if relative.parts[0] == 'tests' or relative.as_posix() in allowed:
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for lineno, name in composed_runtime_names(tree):
            offenders.append('%s:%d  / "%s"' % (relative, lineno, name))
    assert offenders == [], ('런타임 경로를 직접 조립하는 곳:\n  '
                            + '\n  '.join(offenders))


def test_the_guard_above_can_actually_see_a_composed_path():
    found = composed_runtime_names(ast.parse('p = root / "user_data" / "settings"\n'))
    assert found and found[0][1] == 'user_data'
    assert composed_runtime_names(ast.parse('p = root / "somewhere_else"\n')) == []


def test_the_store_is_not_where_ollamas_uninstaller_can_delete_it():
    from core import ollama_paths
    assert ollama_paths.SHARED_MODELS_DIR.parent != ollama_paths.PROJECT_INSTALL_DIR
    assert runtime_root.is_inside(ollama_paths.SHARED_MODELS_DIR,
                                  {}, windows=True)


def test_a_store_the_user_chose_is_still_theirs(monkeypatch, tmp_path):
    monkeypatch.delenv('LLM_MODEL_DIR', raising=False)
    monkeypatch.setenv('OLLAMA_MODELS', str(tmp_path / 'their-drive'))
    monkeypatch.setenv('LOCAL_AI_ROOT', str(tmp_path / 'root'))
    import project_paths
    assert project_paths.model_dir() == tmp_path / 'their-drive'


# ── the move ──────────────────────────────────────────────────────────────

def seeded(path, *names):
    path = Path(path)
    (path / 'blobs').mkdir(parents=True, exist_ok=True)
    for name in names:
        (path / 'blobs' / name).write_text(name, encoding='utf-8')
    return path


def names_in(path):
    folder = Path(path) / 'blobs'
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def test_an_install_left_in_the_checkout_moves_into_the_root(tmp_path):
    checkout, root = tmp_path / 'Downloads' / 'Local_AI_Agent', tmp_path / 'LocalAI'
    account = root / 'users' / 'Tester'
    seeded(checkout / 'llm_environment' / 'searxng', 'settings.yml')
    seeded(checkout / 'user_data' / 'settings', 'user_config.json')

    results = filesystem.migrate_runtime_root(checkout, root, account)

    # Shared where the machine shares, private where the person does.
    assert names_in(root / 'environment' / 'searxng') == ['settings.yml']
    assert names_in(account / 'user_data' / 'settings') == ['user_config.json']
    assert not (root / 'user_data').exists()
    assert not (checkout / 'llm_environment').exists()
    assert not (checkout / 'user_data').exists()
    assert all(result.verified for result in results.values())


def test_records_shared_by_the_previous_layout_move_into_this_account(tmp_path):
    """The release before this one put user_data at the root, for everyone.

    Settings, projects, chat history and every agent trace sat in a folder the
    machine's other accounts could open - and two signed-in users writing the
    same settings file corrupt each other, which is worse than the leak.
    """
    root = tmp_path / 'LocalAI'
    account = root / 'users' / 'Tester'
    seeded(root / 'user_data' / 'settings', 'user_config.json')
    seeded(root / 'logs', 'session.log')

    results = filesystem.migrate_runtime_root(tmp_path / 'checkout', root, account)

    assert names_in(account / 'user_data' / 'settings') == ['user_config.json']
    assert names_in(account / 'logs') == ['session.log']
    assert not (root / 'user_data').exists()
    assert not (root / 'logs').exists()
    assert results['user_data'].verified and results['logs'].verified


def test_a_move_reports_what_it_actually_carried(tmp_path):
    source = seeded(tmp_path / 'old', 'a', 'b', 'c')
    result = relocate.relocate([source], tmp_path / 'new', label='models')
    assert result.files == 3
    assert result.total_bytes == sum(len(n) for n in ('a', 'b', 'c'))
    assert result.verified and not result.problem


def test_a_move_that_loses_files_says_so_instead_of_reporting_success(tmp_path):
    """Verification has to be able to fail, or it is decoration."""
    source = seeded(tmp_path / 'old', 'a', 'b')
    target = tmp_path / 'new'
    real_move = relocate.move

    def lossy(src, dst):
        real_move(src, dst)
        (Path(dst) / 'blobs' / 'b').unlink()

    relocate.move = lossy
    try:
        result = relocate.relocate([source], target, label='models')
    finally:
        relocate.move = real_move
    assert not result.verified
    assert 'models' in result.problem
    assert '2개' in result.problem and '1개' in result.problem
    assert names_in(target) == ['a']


def test_nothing_is_merged_into_a_location_already_in_use(tmp_path):
    checkout, root = tmp_path / 'checkout', tmp_path / 'root'
    account = root / 'users' / 'Tester'
    seeded(checkout / 'user_data' / 'settings', 'old.json')
    seeded(account / 'user_data' / 'settings', 'current.json')

    results = filesystem.migrate_runtime_root(checkout, root, account)

    assert names_in(account / 'user_data' / 'settings') == ['current.json']
    assert names_in(checkout / 'user_data' / 'settings') == ['old.json']
    assert results['user_data'].leftovers == [checkout / 'user_data']


def test_an_empty_destination_left_by_an_earlier_run_does_not_block_the_move(tmp_path):
    checkout, root = tmp_path / 'checkout', tmp_path / 'root'
    account = root / 'users' / 'Tester'
    seeded(checkout / 'user_data' / 'settings', 'real.json')
    (account / 'user_data').mkdir(parents=True)

    filesystem.migrate_runtime_root(checkout, root, account)

    assert names_in(account / 'user_data' / 'settings') == ['real.json']


def test_an_interrupted_copy_is_discarded_while_the_original_survives(tmp_path):
    checkout, root = tmp_path / 'checkout', tmp_path / 'root'
    account = root / 'users' / 'Tester'
    seeded(checkout / 'user_data', 'whole')
    staging = relocate.staging_for(account / 'user_data')
    seeded(staging, 'half')          # no marker: the copy never finished

    filesystem.migrate_runtime_root(checkout, root, account)

    assert names_in(account / 'user_data') == ['whole']
    assert not staging.exists()
    assert not (checkout / 'user_data').exists()


def test_a_finished_copy_is_promoted_even_though_the_run_stopped(tmp_path):
    checkout, root = tmp_path / 'checkout', tmp_path / 'root'
    account = root / 'users' / 'Tester'
    staging = relocate.staging_for(account / 'user_data')
    seeded(staging, 'complete')
    (staging / relocate.MARKER_NAME).write_text(
        'complete\n%s\n' % (checkout / 'user_data'), encoding='utf-8')
    seeded(checkout / 'user_data', 'complete')   # source cleanup never ran

    results = filesystem.migrate_runtime_root(checkout, root, account)

    assert names_in(account / 'user_data') == ['complete']
    assert not staging.exists()
    assert not (checkout / 'user_data').exists()
    assert results['user_data'].promoted


def test_a_development_checkout_keeps_its_shared_environment_in_place(tmp_path):
    """When the checkout is the root, the environment is already where it goes."""
    seeded(tmp_path / 'environment' / 'searxng', 'settings.yml')
    account = tmp_path / 'users' / 'Tester'
    results = filesystem.migrate_runtime_root(tmp_path, tmp_path, account)
    assert 'environment' not in results
    assert names_in(tmp_path / 'environment' / 'searxng') == ['settings.yml']


def test_the_store_ollama_used_to_own_is_a_migration_source(tmp_path):
    from core import ollama_paths
    sources = filesystem.legacy_model_stores(tmp_path / 'env', tmp_path / 'models')
    assert ollama_paths.LEGACY_INSTALL_STORE in sources
    assert ollama_paths.LEGACY_FORCED_STORE in sources


# ── what the window says about it ─────────────────────────────────────────

def test_the_window_is_told_where_an_older_install_still_is(tmp_path, monkeypatch):
    """Reporting "nothing installed" when the install is one folder away.

    With the root moved, a machine that installed with the previous release
    has a complete, working environment the new paths cannot see. Saying so is
    the difference between a one-click repair and a re-download.
    """
    from integrations.legacy import desktop
    checkout, root = tmp_path / 'checkout', tmp_path / 'root'
    seeded(checkout / 'llm_environment' / 'searxng', 'settings.yml')
    monkeypatch.setenv('LLM_PROJECT_ROOT', str(checkout))
    monkeypatch.setenv('LOCAL_AI_ROOT', str(root))
    import project_paths
    monkeypatch.setattr(project_paths, 'PROJECT_ROOT', checkout)
    monkeypatch.setattr(project_paths, 'RUNTIME_ROOT', root)

    backend = desktop.LegacyBackend(root / 'environment', root / 'models', checkout)
    assert checkout / 'llm_environment' in backend.runtime_root_leftovers()
    message = backend.describe_runtime_root()
    assert message and str(checkout / 'llm_environment') in message
    assert str(root) in message


def test_a_tidy_install_says_nothing(tmp_path, monkeypatch):
    from integrations.legacy import desktop
    root = tmp_path / 'root'
    (root / 'environment').mkdir(parents=True)
    import project_paths
    monkeypatch.setattr(project_paths, 'PROJECT_ROOT', tmp_path / 'checkout')
    monkeypatch.setattr(project_paths, 'RUNTIME_ROOT', root)
    backend = desktop.LegacyBackend(root / 'environment', root / 'models',
                                    tmp_path / 'checkout')
    assert backend.describe_runtime_root() is None


# ── the window's own words ────────────────────────────────────────────────

def test_the_chat_page_names_the_old_location_instead_of_saying_not_ready(tmp_path):
    """The install is complete, one folder away. "준비 안 됨" is the wrong answer.

    A machine that installed with the previous release keeps a working
    environment in the checkout. Once the paths moved, the window polled the
    new root, found nothing, and said Chat was not ready - the one message
    that makes a user re-download tens of gigabytes they already have.
    """
    import gc
    gc.collect()
    tk = pytest.importorskip('tkinter')
    from test_desktop_services import make
    from test_desktop_ui import pump
    from apps.shared.window import DesktopWindow

    services, backend = make(tmp_path)
    stray = tmp_path / 'Downloads' / 'Local_AI_Agent' / 'llm_environment'
    backend.health = lambda max_age=None: {
        'ollama': False, 'docker': False, 'chat_image': False, 'chat': False,
        'search': False,
        'runtime_root': ('예전 위치에 설치 데이터가 남아 있습니다: %s. '
                         '[설치 / 복구] 를 한 번 실행하면 %s 아래로 옮기고 확인합니다.'
                         % (stray, tmp_path / 'LocalAI'))}
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip('Real Tk requires DISPLAY; run with Xvfb on Linux')
    window = DesktopWindow('studio', services, root=root, start_polling=False)
    try:
        window.navigate('chat')
        window.refresh_health(fresh=True)
        pump(window, lambda: '예전 위치' in window.chat_state.get())
        assert str(stray) in window.chat_state.get()
        # And the screen that fixes it is one button away.
        assert window.chat_status.action.winfo_ismapped()
        window.chat_status.action.invoke()
        pump(window)
        assert window.current_page == 'setup'
    finally:
        window.runner.shutdown()
        window._unsubscribe()
        services.close()
        try:
            root.after_cancel(window._timer)
        except tk.TclError:
            pass
        try:
            root.destroy()
        except tk.TclError:
            pass


# ── every feature wired to the same root ──────────────────────────────────
#
# The final check the layout has to pass: each runtime, each store and each
# log the product touches resolves inside the root. A single one that does not
# is a feature that quietly stops seeing its own data the moment the root
# moves - which is exactly how the model store, the settings file and the
# session log ended up in three different places.

def wired_paths():
    """(name, host path) for everything the product reads or writes."""
    import project_paths
    from core.projects.registry import ProjectRegistry
    from core.settings.store import SettingsStore
    from launcher import anythingllm_runtime, searxng_runtime, tor_runtime
    from launcher.agent import folder_policy, interpreter_backend
    from launcher.core import lifelog, user_data
    from launcher.models import model_files, model_roles
    from launcher.services.ollama import OllamaService
    from launcher import settings_store

    env = project_paths.ENV_DIR
    service = OllamaService(env, model_dir=project_paths.MODEL_STORAGE_DIR)
    return [
        ('models', project_paths.MODEL_STORAGE_DIR),
        ('environment', env),
        ('user_data', user_data.root()),
        ('session logs', lifelog._llm_session_log_dir()),
        ('agent traces', user_data.logs_dir()),
        ('ollama run log', service.log_file),
        ('ollama runtime state', service.runtime_state_file),
        ('searxng config', searxng_runtime._cfg_dir(env)),
        ('tor torrc', Path(tor_runtime._write_torrc(env) or (env / 'tor' / 'torrc'))),
        ('anythingllm storage', anythingllm_runtime.storage_dir()),
        ('sandbox state', user_data.interpreter_dir('sandbox')),
        ('interpreter home', interpreter_backend.runtime_interpreter_home()),
        ('interpreter binary', interpreter_backend.managed_interpreter_exe()),
        ('user settings', settings_store.path()),
        ('desktop settings', SettingsStore().store.path),
        ('folder policy', folder_policy._store_path()),
        ('project registry', ProjectRegistry().store.path),
        ('model registry', Path(model_roles._registry_path())),
        ('model csv', model_files.default_csv_path(project_paths.MODEL_STORAGE_DIR)),
    ]


def test_every_feature_reads_and_writes_inside_the_one_root():
    import project_paths
    root = Path(project_paths.RUNTIME_ROOT).resolve()
    outside = []
    for name, path in wired_paths():
        try:
            Path(path).resolve().relative_to(root)
        except ValueError:
            outside.append('%s → %s' % (name, path))
    assert outside == [], ('런타임 루트(%s) 밖을 보는 기능:\n  ' % root
                           + '\n  '.join(outside))


def test_the_wiring_check_covers_the_runtimes_that_can_be_turned_on_and_off():
    """A list that quietly loses an entry checks nothing."""
    names = {name for name, _ in wired_paths()}
    for required in ('models', 'environment', 'user_data', 'searxng config',
                     'tor torrc', 'anythingllm storage', 'sandbox state',
                     'ollama run log', 'session logs'):
        assert required in names, required
