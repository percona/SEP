# Copyright (C) 2026 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Tests for the ``scripts/sync_alembic_version_locations.py`` CLI."""

import importlib.util
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPT_PATH = _PROJECT_ROOT / "scripts" / "sync_alembic_version_locations.py"

_spec = importlib.util.spec_from_file_location(
    "sync_alembic_version_locations", _SCRIPT_PATH
)
assert _spec is not None, f"cannot load {_SCRIPT_PATH}"
assert _spec.loader is not None, f"cannot load {_SCRIPT_PATH}"
sync_alembic_version_locations = importlib.util.module_from_spec(_spec)
sys.modules["sync_alembic_version_locations"] = sync_alembic_version_locations
_spec.loader.exec_module(sync_alembic_version_locations)

_MINIMAL_INI = """\
[alembic]
databases = sep

[sep]
# path to migration scripts.
script_location = app/sep/migrations
# stale hand-written comment
version_locations = %(here)s/app/sep/migrations/versions

[post_write_hooks]
# keep this section marker
"""


def _migration_plugin(root: Path, name: str) -> Path:
    """Create a regular plugin package with ``migrations/versions/``.

    :param root: Parent directory acting as the apps root.
    :param name: Plugin directory name.
    :return: The plugin directory path.
    """
    plugin_dir = root / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "__init__.py").write_text("")
    (plugin_dir / "migrations" / "versions").mkdir(parents=True)
    return plugin_dir


def test_sync_regenerates_from_synthetic_app_tree(tmp_path):
    """Rewrite ``version_locations`` from a synthetic apps tree."""
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    _migration_plugin(apps_root, "zebra")
    _migration_plugin(apps_root, "alpha")
    ini_path = tmp_path / "alembic.ini"
    ini_path.write_text(_MINIMAL_INI)

    assert sync_alembic_version_locations.sync_alembic_ini(ini_path, apps_root)
    text = ini_path.read_text()
    expected = (
        "%(here)s/app/sep/migrations/versions:"
        "%(here)s/app/sep/apps/alpha/migrations/versions:"
        "%(here)s/app/sep/apps/zebra/migrations/versions"
    )
    assert f"version_locations = {expected}" in text
    assert "GENERATED" in text
    assert "stale hand-written comment" not in text


def test_sync_is_idempotent_on_second_run(tmp_path):
    """Leave the file byte-identical on a second sync."""
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    _migration_plugin(apps_root, "alpha")
    ini_path = tmp_path / "alembic.ini"
    ini_path.write_text(_MINIMAL_INI)

    assert sync_alembic_version_locations.sync_alembic_ini(ini_path, apps_root)
    after_first = ini_path.read_text()
    assert sync_alembic_version_locations.sync_alembic_ini(ini_path, apps_root)
    assert ini_path.read_text() == after_first
    assert sync_alembic_version_locations.sync_alembic_ini(
        ini_path, apps_root, check=True
    )


def test_sync_preserves_crlf_line_endings(tmp_path):
    """Preserve CRLF ``alembic.ini`` without converting to ``LF``."""
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    _migration_plugin(apps_root, "alpha")
    ini_path = tmp_path / "alembic.ini"
    crlf_ini = _MINIMAL_INI.replace("\n", "\r\n").encode("utf-8")
    ini_path.write_bytes(crlf_ini)

    assert sync_alembic_version_locations.sync_alembic_ini(ini_path, apps_root)
    rewritten = ini_path.read_bytes()
    assert b"\r\n" in rewritten
    assert b"\n" not in rewritten.replace(b"\r\n", b"")
    assert b"app/sep/apps/alpha/migrations/versions" in rewritten


def test_sync_rejects_multiline_version_locations(tmp_path):
    """Reject ``version_locations`` values with indented continuation lines."""
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    _migration_plugin(apps_root, "alpha")
    ini_path = tmp_path / "alembic.ini"
    ini_path.write_text(
        _MINIMAL_INI.replace(
            "version_locations = %(here)s/app/sep/migrations/versions\n",
            "version_locations = %(here)s/app/sep/migrations/versions:\n"
            "    %(here)s/app/sep/apps/stale/migrations/versions\n",
        )
    )

    with pytest.raises(ValueError, match="single line"):
        sync_alembic_version_locations.sync_alembic_ini(ini_path, apps_root)


def test_sync_rejects_missing_sep_section(tmp_path):
    """Reject an ini that lacks a ``[sep]`` section."""
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    ini_path = tmp_path / "alembic.ini"
    ini_path.write_text("[alembic]\ndatabases = sep\n")

    with pytest.raises(ValueError, match=r"no \[sep\] section"):
        sync_alembic_version_locations.sync_alembic_ini(ini_path, apps_root)


def test_sync_rejects_missing_version_locations_assignment(tmp_path):
    """Reject a ``[sep]`` section that has no ``version_locations`` assignment."""
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    ini_path = tmp_path / "alembic.ini"
    ini_path.write_text("[alembic]\ndatabases = sep\n\n[sep]\nscript_location = x\n")

    with pytest.raises(ValueError, match="no version_locations assignment"):
        sync_alembic_version_locations.sync_alembic_ini(ini_path, apps_root)


def test_main_reports_malformed_ini_cleanly(tmp_path, capsys):
    """Report a malformed ini as a one-line CLI error, not a traceback."""
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    ini_path = tmp_path / "alembic.ini"
    ini_path.write_text("[alembic]\ndatabases = sep\n")

    assert (
        sync_alembic_version_locations.main(
            ["--ini", str(ini_path), "--apps-root", str(apps_root)]
        )
        == 1
    )
    err = capsys.readouterr().err
    assert "no [sep] section" in err
    assert "Traceback" not in err


def test_sync_preserves_comment_block_and_other_sections(tmp_path):
    """Keep ``script_location`` and non-``[sep]`` sections intact."""
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    _migration_plugin(apps_root, "alpha")
    ini_path = tmp_path / "alembic.ini"
    ini_path.write_text(_MINIMAL_INI)

    sync_alembic_version_locations.sync_alembic_ini(ini_path, apps_root)
    text = ini_path.read_text()
    assert "script_location = app/sep/migrations" in text
    assert "[post_write_hooks]" in text
    assert "# keep this section marker" in text
    assert "databases = sep" in text
    assert "GENERATED — do not hand-edit" in text


def test_sync_check_detects_drift(tmp_path):
    """Fail ``--check`` when the committed value is stale."""
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    _migration_plugin(apps_root, "alpha")
    ini_path = tmp_path / "alembic.ini"
    ini_path.write_text(_MINIMAL_INI)

    assert not sync_alembic_version_locations.sync_alembic_ini(
        ini_path, apps_root, check=True
    )
    assert (
        sync_alembic_version_locations.main(
            ["--check", "--ini", str(ini_path), "--apps-root", str(apps_root)]
        )
        == 1
    )


def test_committed_alembic_ini_matches_discovery():
    """Confirm committed ``alembic.ini`` matches the filesystem walk."""
    assert sync_alembic_version_locations.main(["--check"]) == 0
