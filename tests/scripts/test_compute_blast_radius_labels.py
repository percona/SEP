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

"""Tests for ``scripts/compute_blast_radius_labels.py``."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPT_PATH = _PROJECT_ROOT / "scripts" / "compute_blast_radius_labels.py"

_spec = importlib.util.spec_from_file_location(
    "compute_blast_radius_labels", _SCRIPT_PATH
)
assert _spec is not None, f"cannot load {_SCRIPT_PATH}"
assert _spec.loader is not None, f"cannot load {_SCRIPT_PATH}"
compute_blast_radius_labels = importlib.util.module_from_spec(_spec)
sys.modules["compute_blast_radius_labels"] = compute_blast_radius_labels
_spec.loader.exec_module(compute_blast_radius_labels)

_LABELER_PATH = _PROJECT_ROOT / ".github" / "labeler.yml"
_LABELER_TEXT = _LABELER_PATH.read_text(encoding="utf-8")
_APP_GLOBS = compute_blast_radius_labels.parse_app_globs(_LABELER_TEXT)


def _file(name: str, additions: int = 0, deletions: int = 0):
    return compute_blast_radius_labels.PrFile(
        filename=name, additions=additions, deletions=deletions
    )


def test_parse_app_globs_discovers_all_app_labels():
    """Parse every ``app:<name>`` block from the committed labeler config."""
    labels = list(_APP_GLOBS)
    assert len(labels) == len(_APP_GLOBS)
    assert "app:report" in labels
    assert "app:archives" in labels


def test_archives_template_alias_resolves_through_labeler_globs():
    """Map ``templates/archiver`` to the ``app:archives`` label."""
    assert (
        compute_blast_radius_labels.app_of("templates/archiver/report.j2", _APP_GLOBS)
        == "app:archives"
    )
    assert (
        compute_blast_radius_labels.app_of("templates/archives/report.j2", _APP_GLOBS)
        is None
    )


def test_e2e_hyphen_aliases_resolve_to_underscore_app_labels():
    """Map hyphenated Playwright specs to underscore app labels."""
    assert (
        compute_blast_radius_labels.app_of(
            "frontend/packages/e2e/tests/mysql-backups.spec.ts", _APP_GLOBS
        )
        == "app:mysql_backups"
    )
    assert (
        compute_blast_radius_labels.app_of(
            "frontend/packages/e2e/tests/alert-troubleshooting.spec.ts",
            _APP_GLOBS,
        )
        == "app:alert_troubleshooting"
    )


def test_svc_and_cross_cutting_paths_are_not_app_slices():
    """Exclude mounted services and framework paths from app-slice membership."""
    assert compute_blast_radius_labels.app_of("app/tasks/worker.py", _APP_GLOBS) is None
    assert compute_blast_radius_labels.app_of("app/core/config.py", _APP_GLOBS) is None
    assert compute_blast_radius_labels.app_of(".github/labeler.yml", _APP_GLOBS) is None


def test_inventory_e2e_prefix_matches_the_app_label():
    """Match inventory-related e2e specs via the ``inventory*.spec.ts`` glob."""
    assert (
        compute_blast_radius_labels.app_of(
            "frontend/packages/e2e/tests/inventory-sync.spec.ts", _APP_GLOBS
        )
        == "app:inventory"
    )


def test_match_glob_supports_directory_and_wildcard_patterns():
    """Support ``/**`` directory globs and single-segment ``*`` wildcards."""
    assert compute_blast_radius_labels.match_glob(
        "app/sep/apps/report/**", "app/sep/apps/report/routes.py"
    )
    assert compute_blast_radius_labels.match_glob(
        "frontend/packages/e2e/tests/report*.spec.ts",
        "frontend/packages/e2e/tests/report.spec.ts",
    )


def test_is_generated_discounts_lockfiles_and_generated_api_paths():
    """Exclude lockfiles and generated API client paths from diff sizing."""
    assert compute_blast_radius_labels.is_generated("poetry.lock")
    assert compute_blast_radius_labels.is_generated("frontend/pnpm-lock.yaml")
    assert compute_blast_radius_labels.is_generated(
        "frontend/packages/api/src/generated/client.ts"
    )
    assert not compute_blast_radius_labels.is_generated("app/sep/apps/report/routes.py")


def test_compute_blast_radius_marks_a_single_app_pr_as_isolated():
    """Mark a PR confined to one app slice as ``app-isolated``."""
    files = [
        _file("app/sep/apps/report/a.py", additions=1),
        _file("frontend/packages/apps/report/b.ts", additions=2),
    ]
    result = compute_blast_radius_labels.compute_blast_radius(files, _APP_GLOBS)
    assert result.app_isolated is True
    assert result.touched_apps == ("app:report",)


def test_compute_blast_radius_rejects_mixed_app_and_cross_cutting_prs():
    """Reject PRs that span apps or touch cross-cutting paths."""
    mixed_apps = [
        _file("app/sep/apps/report/a.py", additions=1),
        _file("app/sep/apps/alerts/b.py", additions=1),
    ]
    assert (
        compute_blast_radius_labels.compute_blast_radius(
            mixed_apps, _APP_GLOBS
        ).app_isolated
        is False
    )

    cross_cutting = [
        _file("app/sep/apps/report/a.py", additions=1),
        _file("app/core/x.py", additions=1),
    ]
    assert (
        compute_blast_radius_labels.compute_blast_radius(
            cross_cutting, _APP_GLOBS
        ).app_isolated
        is False
    )

    github_only = [_file(".github/labeler.yml", additions=10)]
    assert (
        compute_blast_radius_labels.compute_blast_radius(
            github_only, _APP_GLOBS
        ).app_isolated
        is False
    )


def test_compute_blast_radius_applies_threshold_with_generated_discount():
    """Apply the 1500-line threshold and discount generated paths."""
    at_threshold = [_file("app/sep/apps/report/a.py", additions=1000, deletions=500)]
    assert (
        compute_blast_radius_labels.compute_blast_radius(
            at_threshold, _APP_GLOBS
        ).large_diff
        is False
    )

    over_threshold = [_file("app/sep/apps/report/a.py", additions=1000, deletions=501)]
    assert (
        compute_blast_radius_labels.compute_blast_radius(
            over_threshold, _APP_GLOBS
        ).large_diff
        is True
    )

    discounted = [
        _file("app/sep/apps/report/a.py", additions=100),
        _file("frontend/packages/api/src/generated/x.ts", additions=5000),
        _file("poetry.lock", additions=9000),
    ]
    result = compute_blast_radius_labels.compute_blast_radius(discounted, _APP_GLOBS)
    assert result.changed_lines == discounted[0].additions
    assert result.large_diff is False


def test_sync_blast_radius_labels_adds_and_removes_labels():
    """Add missing labels and remove stale ones."""
    client = Mock()
    client.list_issue_labels.return_value = {"large-diff"}
    result = compute_blast_radius_labels.BlastRadiusResult(
        changed_lines=10,
        large_diff=False,
        app_isolated=True,
        touched_apps=("app:report",),
    )

    compute_blast_radius_labels.sync_blast_radius_labels(
        client, "percona", "SEP", 42, result, log=lambda _message: None
    )

    client.add_issue_labels.assert_called_once_with(
        "percona", "SEP", 42, ["app-isolated"]
    )
    client.remove_issue_label.assert_called_once_with(
        "percona", "SEP", 42, "large-diff"
    )


def test_main_requires_github_token(tmp_path, monkeypatch, capsys):
    """Fail cleanly when the GitHub token environment variable is unset."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    labeler = tmp_path / "labeler.yml"
    labeler.write_text("app:demo:\n- any: []\n", encoding="utf-8")

    assert (
        compute_blast_radius_labels.main(
            [
                "--owner",
                "percona",
                "--repo",
                "SEP",
                "--pr-number",
                "1",
                "--labeler",
                str(labeler),
            ]
        )
        == 1
    )
    assert "GITHUB_TOKEN is not set" in capsys.readouterr().err


def test_main_reports_missing_labeler_cleanly(monkeypatch, capsys):
    """Report a missing labeler file as a one-line CLI error."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    assert (
        compute_blast_radius_labels.main(
            [
                "--owner",
                "percona",
                "--repo",
                "SEP",
                "--pr-number",
                "1",
                "--labeler",
                "/tmp/does-not-exist-labeler.yml",
                "--token-env",
                "GITHUB_TOKEN",
            ]
        )
        == 1
    )
    err = capsys.readouterr().err
    assert "file not found" in err
    assert "Traceback" not in err
