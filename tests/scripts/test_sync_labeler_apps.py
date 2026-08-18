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

"""Tests for the ``scripts/sync_labeler_apps.py`` CLI."""

import importlib.util
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPT_PATH = _PROJECT_ROOT / "scripts" / "sync_labeler_apps.py"

_spec = importlib.util.spec_from_file_location("sync_labeler_apps", _SCRIPT_PATH)
assert _spec is not None, f"cannot load {_SCRIPT_PATH}"
assert _spec.loader is not None, f"cannot load {_SCRIPT_PATH}"
sync_labeler_apps = importlib.util.module_from_spec(_spec)
sys.modules["sync_labeler_apps"] = sync_labeler_apps
_spec.loader.exec_module(sync_labeler_apps)

_EXISTING_RULES = """\
python:
- any:
  - changed-files:
    - any-glob-to-any-file:
      - '**/**.py'

svc:tasks:
- any:
  - changed-files:
    - any-glob-to-any-file:
      - 'app/tasks/**'
"""


def _make_app(
    repo: Path,
    name: str,
    *,
    backend: bool = True,
    frontend: bool = False,
    tests: bool = False,
    e2e: str | None = None,
) -> None:
    """Create the requested surfaces for one synthetic app slice.

    :param repo: Synthetic repository root.
    :param name: App-slice name (its ``app/sep/apps`` directory).
    :param backend: Create the backend app directory.
    :param frontend: Create the ``frontend/packages/apps`` directory.
    :param tests: Create the ``tests/app/sep/apps`` directory.
    :param e2e: Optional e2e spec stem to materialize as ``<value>.spec.ts``.
    """
    if backend:
        app_dir = repo / "app" / "sep" / "apps" / name
        app_dir.mkdir(parents=True, exist_ok=True)
        (app_dir / "__init__.py").touch(exist_ok=True)
    if frontend:
        (repo / "frontend" / "packages" / "apps" / name).mkdir(
            parents=True, exist_ok=True
        )
    if tests:
        (repo / "tests" / "app" / "sep" / "apps" / name).mkdir(
            parents=True, exist_ok=True
        )
    if e2e is not None:
        e2e_dir = repo / "frontend" / "packages" / "e2e" / "tests"
        e2e_dir.mkdir(parents=True, exist_ok=True)
        (e2e_dir / f"{e2e}.spec.ts").write_text("", encoding="utf-8")


def _valid_repo(tmp_path: Path) -> Path:
    """Return a synthetic repo whose alias entries all resolve on disk.

    Materializes every aliased app so :func:`validate_aliases` passes, letting
    a test add or omit further apps without tripping the alias assertions.

    :param tmp_path: Pytest temporary directory.
    :return: The synthetic repository root.
    """
    repo = tmp_path / "repo"
    (repo / "app" / "sep" / "apps").mkdir(parents=True)
    _make_app(repo, "archives", e2e="archives")
    _make_app(repo, "alert_troubleshooting", e2e="alert-troubleshooting")
    _make_app(repo, "mysql_backups", e2e="mysql-backups")
    return repo


def _write_labeler(repo: Path, body: str) -> Path:
    """Write ``.github/labeler.yml`` under ``repo`` and return its path.

    :param repo: Synthetic repository root.
    :param body: File contents.
    :return: Path to the written labeler config.
    """
    labeler = repo / ".github" / "labeler.yml"
    labeler.parent.mkdir(parents=True, exist_ok=True)
    labeler.write_text(body, encoding="utf-8")
    return labeler


def _apps_root(repo: Path) -> Path:
    """Return the ``app/sep/apps`` directory for a synthetic repo.

    :param repo: Synthetic repository root.
    :return: The apps root directory.
    """
    return repo / "app" / "sep" / "apps"


def test_generates_block_for_each_app(tmp_path):
    """Emit one ``app:<name>`` entry per discovered app slice."""
    repo = _valid_repo(tmp_path)
    _make_app(repo, "zebra", frontend=True, tests=True, e2e="zebra")
    labeler = _write_labeler(repo, _EXISTING_RULES)

    assert sync_labeler_apps.sync_labeler(labeler, _apps_root(repo), repo)
    text = labeler.read_text(encoding="utf-8")

    assert "app:zebra:" in text
    assert "- 'app/sep/apps/zebra/**'" in text
    assert "- 'frontend/packages/apps/zebra/**'" in text
    assert "- 'tests/app/sep/apps/zebra/**'" in text
    assert "- 'frontend/packages/e2e/tests/zebra*.spec.ts'" in text


def test_only_existing_surfaces_are_emitted(tmp_path):
    """Skip globs for surfaces that do not exist on disk."""
    repo = _valid_repo(tmp_path)
    _make_app(repo, "backendonly")
    labeler = _write_labeler(repo, _EXISTING_RULES)

    sync_labeler_apps.sync_labeler(labeler, _apps_root(repo), repo)
    text = labeler.read_text(encoding="utf-8")

    assert "app:backendonly:" in text
    assert "- 'app/sep/apps/backendonly/**'" in text
    assert "frontend/packages/apps/backendonly" not in text
    assert "e2e/tests/backendonly" not in text


def test_e2e_alias_is_resolved(tmp_path):
    """Map underscore app names to their hyphenated e2e spec stems."""
    repo = _valid_repo(tmp_path)
    labeler = _write_labeler(repo, _EXISTING_RULES)

    sync_labeler_apps.sync_labeler(labeler, _apps_root(repo), repo)
    text = labeler.read_text(encoding="utf-8")

    assert "- 'frontend/packages/e2e/tests/alert-troubleshooting*.spec.ts'" in text
    assert "- 'frontend/packages/e2e/tests/mysql-backups*.spec.ts'" in text


def test_framework_and_shared_are_excluded(tmp_path):
    """Omit labels for the ``framework`` and ``shared`` internals."""
    repo = _valid_repo(tmp_path)
    _make_app(repo, "framework")
    _make_app(repo, "shared")
    (repo / "app" / "sep" / "apps" / "__pycache__").mkdir()
    labeler = _write_labeler(repo, _EXISTING_RULES)

    sync_labeler_apps.sync_labeler(labeler, _apps_root(repo), repo)
    text = labeler.read_text(encoding="utf-8")

    assert "app:framework:" not in text
    assert "app:shared:" not in text
    assert "__pycache__" not in text


def test_leftover_pycache_only_directory_is_not_an_app(tmp_path):
    """Exclude leftover ``__pycache__``-only directories from app discovery."""
    repo = _valid_repo(tmp_path)
    leftover = repo / "app" / "sep" / "apps" / "ghost_app"
    leftover.mkdir(parents=True)
    (leftover / "__pycache__").mkdir()

    apps = sync_labeler_apps.discover_apps(_apps_root(repo))
    assert "ghost_app" not in apps

    labeler = _write_labeler(repo, _EXISTING_RULES)
    sync_labeler_apps.sync_labeler(labeler, _apps_root(repo), repo)
    text = labeler.read_text(encoding="utf-8")
    assert "app:ghost_app:" not in text


def test_preserves_surrounding_rules(tmp_path):
    """Leave hand-maintained rules outside the markers untouched."""
    repo = _valid_repo(tmp_path)
    labeler = _write_labeler(repo, _EXISTING_RULES)

    sync_labeler_apps.sync_labeler(labeler, _apps_root(repo), repo)
    text = labeler.read_text(encoding="utf-8")

    assert "python:" in text
    assert "svc:tasks:" in text
    assert sync_labeler_apps.BEGIN_MARKER in text
    assert sync_labeler_apps.END_MARKER in text


def test_replaces_between_markers_dropping_stale_entries(tmp_path):
    """Rewrite only the marked region, dropping a stale generated entry."""
    repo = _valid_repo(tmp_path)
    stale = (
        _EXISTING_RULES
        + "\n"
        + sync_labeler_apps.BEGIN_MARKER
        + "\napp:ghost:\n- any: []\n"
        + sync_labeler_apps.END_MARKER
        + "\n\nfrontend:\n- any: []\n"
    )
    labeler = _write_labeler(repo, stale)

    sync_labeler_apps.sync_labeler(labeler, _apps_root(repo), repo)
    text = labeler.read_text(encoding="utf-8")

    assert "app:ghost:" not in text
    assert "app:archives:" in text
    assert text.rstrip().endswith("- any: []")


def test_idempotent_and_check_in_sync(tmp_path):
    """Leave the file byte-identical on a second sync and pass ``--check``."""
    repo = _valid_repo(tmp_path)
    labeler = _write_labeler(repo, _EXISTING_RULES)

    sync_labeler_apps.sync_labeler(labeler, _apps_root(repo), repo)
    after_first = labeler.read_text(encoding="utf-8")
    sync_labeler_apps.sync_labeler(labeler, _apps_root(repo), repo)
    assert labeler.read_text(encoding="utf-8") == after_first
    assert sync_labeler_apps.sync_labeler(labeler, _apps_root(repo), repo, check=True)


def test_check_detects_drift(tmp_path):
    """Fail ``--check`` when a new app has not been regenerated."""
    repo = _valid_repo(tmp_path)
    labeler = _write_labeler(repo, _EXISTING_RULES)
    sync_labeler_apps.sync_labeler(labeler, _apps_root(repo), repo)

    _make_app(repo, "newapp")
    assert not sync_labeler_apps.sync_labeler(
        labeler, _apps_root(repo), repo, check=True
    )
    assert (
        sync_labeler_apps.main(
            ["--check", "--labeler", str(labeler), "--repo-root", str(repo)]
        )
        == 1
    )


def test_stale_e2e_alias_raises(tmp_path):
    """Fail when an e2e alias spec no longer exists on disk."""
    repo = _valid_repo(tmp_path)
    (
        repo / "frontend" / "packages" / "e2e" / "tests" / "mysql-backups.spec.ts"
    ).unlink()
    labeler = _write_labeler(repo, _EXISTING_RULES)

    with pytest.raises(ValueError, match="stale e2e alias"):
        sync_labeler_apps.sync_labeler(labeler, _apps_root(repo), repo)


def test_alias_for_unknown_app_raises(tmp_path):
    """Fail when an alias key is not a discovered app."""
    repo = tmp_path / "repo"
    (repo / "app" / "sep" / "apps").mkdir(parents=True)
    _make_app(repo, "alert_troubleshooting", e2e="alert-troubleshooting")
    labeler = _write_labeler(repo, _EXISTING_RULES)

    with pytest.raises(ValueError, match="unknown app"):
        sync_labeler_apps.sync_labeler(labeler, _apps_root(repo), repo)


def test_mismatched_marker_raises(tmp_path):
    """Reject a file that has only one of the two block markers."""
    repo = _valid_repo(tmp_path)
    labeler = _write_labeler(
        repo, _EXISTING_RULES + "\n" + sync_labeler_apps.BEGIN_MARKER + "\n"
    )

    with pytest.raises(ValueError, match="mismatched"):
        sync_labeler_apps.sync_labeler(labeler, _apps_root(repo), repo)


def test_main_reports_error_cleanly(tmp_path, capsys):
    """Report a stale alias as a one-line CLI error, not a traceback."""
    repo = _valid_repo(tmp_path)
    (
        repo / "frontend" / "packages" / "e2e" / "tests" / "mysql-backups.spec.ts"
    ).unlink()
    labeler = _write_labeler(repo, _EXISTING_RULES)

    assert (
        sync_labeler_apps.main(["--labeler", str(labeler), "--repo-root", str(repo)])
        == 1
    )
    err = capsys.readouterr().err
    assert "stale e2e alias" in err
    assert "Traceback" not in err


def test_committed_labeler_matches_disk():
    """Confirm the committed ``.github/labeler.yml`` matches the walk."""
    assert sync_labeler_apps.main(["--check"]) == 0
