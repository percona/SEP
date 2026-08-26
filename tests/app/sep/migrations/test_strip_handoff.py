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

"""Define the end-to-end handoff between the sync generator and the orphan-head filter.

One tree, readable by both halves, asserts the refusal and arming outcomes
for every strip shape the shipped advice claims to cover.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.sep.migrations._orphan_heads import empty_version_locations

from .conftest import load_sync_alembic_version_locations, write_revision

sync_alembic_version_locations = load_sync_alembic_version_locations()

_ALPHA_ENTRY = "%(here)s/app/sep/apps/alpha/migrations/versions"
_MAIN_ENTRY = sync_alembic_version_locations.MAIN_VERSIONS_ENTRY


def _build_handoff_tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Build a tree both the generator walk and ScriptDirectory can read.

    Layout mirrors the committed repo so ``%(here)s/...`` entries resolve under
    ``tmp_path``, and ``discover_plugin_version_dirs`` scans the same apps root.

    :param tmp_path: Pytest temporary directory acting as ``%(here)s``.
    :return: ``(ini_path, apps_root, alpha_versions)``.
    """
    apps_root = tmp_path / "app" / "sep" / "apps"
    main_versions = tmp_path / "app" / "sep" / "migrations" / "versions"
    alpha = apps_root / "alpha"
    alpha_versions = alpha / "migrations" / "versions"

    (tmp_path / "app" / "sep" / "migrations").mkdir(parents=True)
    write_revision(main_versions, "main00000001", "sep_main")
    alpha.mkdir(parents=True)
    (alpha / "__init__.py").write_text("", encoding="utf-8")
    write_revision(alpha_versions, "alpha0000001", "alpha")

    ini_path = tmp_path / "alembic.ini"
    ini_path.write_text(
        "[alembic]\n"
        "databases = sep\n"
        "\n"
        "[sep]\n"
        "script_location = %(here)s/app/sep/migrations\n"
        "version_path_separator = :\n"
        f"version_locations = {_MAIN_ENTRY}:"
        f"{_ALPHA_ENTRY}\n",
        encoding="utf-8",
    )
    return ini_path, apps_root, alpha_versions


def _apply_strip(shape: str, apps_root: Path, alpha_versions: Path) -> None:
    """Mutate the alpha package into one of the four strip shapes."""
    alpha = apps_root / "alpha"
    if shape == "versions-removed":
        shutil.rmtree(alpha_versions)
    elif shape == "package-removed":
        shutil.rmtree(alpha)
    elif shape == "init-gone":
        (alpha / "__init__.py").unlink()
        for script in alpha_versions.glob("*.py"):
            script.unlink()
    elif shape == "versions-empty":
        for script in alpha_versions.glob("*.py"):
            script.unlink()
    else:
        raise AssertionError(f"unknown strip shape {shape!r}")


def _generator_refused(ini_path: Path, apps_root: Path) -> bool:
    """Return whether ``sync_alembic_ini`` refused to drop the alpha entry."""
    try:
        sync_alembic_version_locations.sync_alembic_ini(ini_path, apps_root)
    except sync_alembic_version_locations.VersionLocationsRemovalError as exc:
        return _ALPHA_ENTRY in exc.removed
    return False


def _filter_armed(ini_path: Path) -> bool:
    """Return whether the orphan-head filter would arm on this tree."""
    script = ScriptDirectory.from_config(Config(str(ini_path), ini_section="sep"))
    empty = empty_version_locations(script)
    return any(
        Path(location).as_posix().endswith("apps/alpha/migrations/versions")
        for location in empty
    )


@pytest.mark.parametrize(
    ("shape", "expect_refuse", "expect_arm"),
    [
        ("versions-removed", True, True),
        ("package-removed", True, True),
        ("init-gone", True, True),
        ("versions-empty", False, True),
    ],
)
def test_strip_shape_handoff_matches_shipped_claim(
    tmp_path, shape, expect_refuse, expect_arm
):
    """Drive generator refusal and filter arming against one tree per strip shape."""
    ini_path, apps_root, alpha_versions = _build_handoff_tree(tmp_path)
    before = ini_path.read_text(encoding="utf-8")
    _apply_strip(shape, apps_root, alpha_versions)

    refused = _generator_refused(ini_path, apps_root)
    assert refused is expect_refuse
    if refused:
        assert ini_path.read_text(encoding="utf-8") == before
    else:
        assert _ALPHA_ENTRY in ini_path.read_text(encoding="utf-8")

    assert _filter_armed(ini_path) is expect_arm
