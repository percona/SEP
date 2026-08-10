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


def _ini_with_entries(*plugins: str) -> str:
    """Return a minimal ini whose ``version_locations`` lists ``plugins``.

    :param plugins: App names to list after the main-chain entry.
    :return: Ini text with the assignment already populated.
    """
    entries = [
        sync_alembic_version_locations.MAIN_VERSIONS_ENTRY,
        *(f"%(here)s/app/sep/apps/{name}/migrations/versions" for name in plugins),
    ]
    return _MINIMAL_INI.replace(
        "version_locations = %(here)s/app/sep/migrations/versions",
        f"version_locations = {':'.join(entries)}",
    )


class TestCurrentVersionLocations:
    """Cover reading the entries already listed in the ``[sep]`` section."""

    def test_splits_the_committed_value_on_the_separator(self):
        """Return one entry per colon-separated path, in file order."""
        text = _ini_with_entries("zebra", "alpha")

        assert sync_alembic_version_locations.current_version_locations(text) == (
            "%(here)s/app/sep/migrations/versions",
            "%(here)s/app/sep/apps/zebra/migrations/versions",
            "%(here)s/app/sep/apps/alpha/migrations/versions",
        )

    def test_strips_padding_and_drops_empty_entries(self):
        """Tolerate a hand-spaced value without inventing phantom entries."""
        text = _MINIMAL_INI.replace(
            "version_locations = %(here)s/app/sep/migrations/versions",
            "version_locations =  %(here)s/app/sep/migrations/versions : "
            "%(here)s/app/sep/apps/alpha/migrations/versions :",
        )

        assert sync_alembic_version_locations.current_version_locations(text) == (
            "%(here)s/app/sep/migrations/versions",
            "%(here)s/app/sep/apps/alpha/migrations/versions",
        )

    def test_returns_nothing_for_an_empty_assignment(self):
        """Treat a blank value as zero entries rather than one empty entry."""
        text = _MINIMAL_INI.replace(
            "version_locations = %(here)s/app/sep/migrations/versions",
            "version_locations =",
        )

        assert sync_alembic_version_locations.current_version_locations(text) == ()

    def test_rejects_a_missing_sep_section(self):
        """Raise rather than report an empty list for a malformed ini."""
        with pytest.raises(ValueError, match=r"no \[sep\] section"):
            sync_alembic_version_locations.current_version_locations(
                "[alembic]\ndatabases = sep\n"
            )

    def test_ignores_a_version_locations_line_outside_the_sep_section(self):
        """Read only the ``[sep]`` value, not a same-named key elsewhere."""
        text = _MINIMAL_INI.replace(
            "[post_write_hooks]",
            "[other]\nversion_locations = %(here)s/decoy\n\n[post_write_hooks]",
        )

        assert sync_alembic_version_locations.current_version_locations(text) == (
            "%(here)s/app/sep/migrations/versions",
        )


class TestRemovalRefusal:
    """Cover the guard that keeps a regeneration from pruning entries."""

    def test_refuses_to_drop_a_configured_entry(self, tmp_path):
        """Fail without writing when the walk omits a listed app."""
        apps_root = tmp_path / "apps"
        apps_root.mkdir()
        ini_path = tmp_path / "alembic.ini"
        ini_path.write_text(_ini_with_entries("alpha"))
        before = ini_path.read_text()

        with pytest.raises(
            sync_alembic_version_locations.VersionLocationsRemovalError
        ) as excinfo:
            sync_alembic_version_locations.sync_alembic_ini(ini_path, apps_root)

        assert excinfo.value.removed == (
            "%(here)s/app/sep/apps/alpha/migrations/versions",
        )
        assert ini_path.read_text() == before

    def test_refuses_a_tree_that_both_adds_and_removes(self, tmp_path):
        """Use a set difference, not a subset test, to spot the removal.

        The discovered set is not a subset of the configured one here, so a
        subset test would wave this through and prune ``alpha``.
        """
        apps_root = tmp_path / "apps"
        apps_root.mkdir()
        _migration_plugin(apps_root, "beta")
        ini_path = tmp_path / "alembic.ini"
        ini_path.write_text(_ini_with_entries("alpha"))

        with pytest.raises(
            sync_alembic_version_locations.VersionLocationsRemovalError
        ) as excinfo:
            sync_alembic_version_locations.sync_alembic_ini(ini_path, apps_root)

        assert excinfo.value.removed == (
            "%(here)s/app/sep/apps/alpha/migrations/versions",
        )

    def test_names_every_removed_entry_in_configuration_order(self, tmp_path):
        """List each pruned entry as the file ordered them."""
        apps_root = tmp_path / "apps"
        apps_root.mkdir()
        ini_path = tmp_path / "alembic.ini"
        ini_path.write_text(_ini_with_entries("zebra", "alpha"))

        with pytest.raises(
            sync_alembic_version_locations.VersionLocationsRemovalError
        ) as excinfo:
            sync_alembic_version_locations.sync_alembic_ini(ini_path, apps_root)

        assert excinfo.value.removed == (
            "%(here)s/app/sep/apps/zebra/migrations/versions",
            "%(here)s/app/sep/apps/alpha/migrations/versions",
        )

    def test_additive_only_change_still_writes(self, tmp_path):
        """Leave the existing add-an-app workflow untouched."""
        apps_root = tmp_path / "apps"
        apps_root.mkdir()
        _migration_plugin(apps_root, "alpha")
        _migration_plugin(apps_root, "beta")
        ini_path = tmp_path / "alembic.ini"
        ini_path.write_text(_ini_with_entries("alpha"))

        assert sync_alembic_version_locations.sync_alembic_ini(ini_path, apps_root)
        assert "app/sep/apps/beta/migrations/versions" in ini_path.read_text()

    def test_reordering_alone_is_not_a_removal(self, tmp_path):
        """Compare entry sets, so a re-sorted list writes without refusing."""
        apps_root = tmp_path / "apps"
        apps_root.mkdir()
        _migration_plugin(apps_root, "alpha")
        _migration_plugin(apps_root, "zebra")
        ini_path = tmp_path / "alembic.ini"
        ini_path.write_text(_ini_with_entries("zebra", "alpha"))

        assert sync_alembic_version_locations.sync_alembic_ini(ini_path, apps_root)

    def test_check_reports_the_refusal_instead_of_plain_drift(self, tmp_path):
        """Refuse under ``--check`` too, so CI sees the pruning attempt."""
        apps_root = tmp_path / "apps"
        apps_root.mkdir()
        ini_path = tmp_path / "alembic.ini"
        ini_path.write_text(_ini_with_entries("alpha"))

        with pytest.raises(sync_alembic_version_locations.VersionLocationsRemovalError):
            sync_alembic_version_locations.sync_alembic_ini(
                ini_path, apps_root, check=True
            )

    def test_opt_in_flag_performs_the_removing_write(self, tmp_path):
        """Allow a deliberate deletion of an app's migration chain."""
        apps_root = tmp_path / "apps"
        apps_root.mkdir()
        ini_path = tmp_path / "alembic.ini"
        ini_path.write_text(_ini_with_entries("alpha"))

        assert sync_alembic_version_locations.sync_alembic_ini(
            ini_path, apps_root, allow_removals=True
        )
        assert "app/sep/apps/alpha/migrations/versions" not in ini_path.read_text()

    def test_malformed_ini_is_still_reported_as_malformed(self, tmp_path):
        """Keep the parse errors ahead of the removal check."""
        apps_root = tmp_path / "apps"
        apps_root.mkdir()
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


class TestRemovalRefusalCli:
    """Cover how the CLI surfaces a refused removal."""

    def test_exits_non_zero_naming_the_removed_entries(self, tmp_path, capsys):
        """Print the pruned entries and the opt-in flag, not a traceback."""
        apps_root = tmp_path / "apps"
        apps_root.mkdir()
        ini_path = tmp_path / "alembic.ini"
        ini_path.write_text(_ini_with_entries("alpha"))

        assert (
            sync_alembic_version_locations.main(
                ["--ini", str(ini_path), "--apps-root", str(apps_root)]
            )
            == 1
        )
        err = capsys.readouterr().err
        assert "app/sep/apps/alpha/migrations/versions" in err
        assert "--allow-removals" in err
        assert "Traceback" not in err

    def test_check_exits_non_zero_on_a_pruning_tree(self, tmp_path, capsys):
        """Fail ``--check`` when entries would be pruned."""
        apps_root = tmp_path / "apps"
        apps_root.mkdir()
        ini_path = tmp_path / "alembic.ini"
        ini_path.write_text(_ini_with_entries("alpha"))

        assert (
            sync_alembic_version_locations.main(
                ["--check", "--ini", str(ini_path), "--apps-root", str(apps_root)]
            )
            == 1
        )
        assert "app/sep/apps/alpha/migrations/versions" in capsys.readouterr().err

    def test_opt_in_flag_writes_and_exits_zero(self, tmp_path):
        """Let ``--allow-removals`` complete the removing write from the CLI."""
        apps_root = tmp_path / "apps"
        apps_root.mkdir()
        ini_path = tmp_path / "alembic.ini"
        ini_path.write_text(_ini_with_entries("alpha"))

        assert (
            sync_alembic_version_locations.main(
                [
                    "--allow-removals",
                    "--ini",
                    str(ini_path),
                    "--apps-root",
                    str(apps_root),
                ]
            )
            == 0
        )
        assert "app/sep/apps/alpha/migrations/versions" not in ini_path.read_text()
