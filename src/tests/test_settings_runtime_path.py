from pathlib import Path

from launcher import settings_store
from project_paths import PROJECT_ROOT, SRC_ROOT


def test_agent_runtime_compat_path_follows_src_layout():
    expected = SRC_ROOT / "launcher" / "agent" / "settings"
    actual = settings_store._agent_runtime_compat_dir(PROJECT_ROOT)
    assert actual == expected


def test_external_root_keeps_legacy_layout_for_migration(tmp_path: Path):
    expected = tmp_path / "launcher" / "agent" / "settings"
    actual = settings_store._agent_runtime_compat_dir(tmp_path)
    assert actual == expected
