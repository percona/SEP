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

"""Tests for the ``scripts/changelog.py`` CLI."""

import importlib.util
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPT_PATH = _PROJECT_ROOT / "scripts" / "changelog.py"

_spec = importlib.util.spec_from_file_location("changelog", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None, f"cannot load {_SCRIPT_PATH}"
changelog = importlib.util.module_from_spec(_spec)
sys.modules["changelog"] = changelog
_spec.loader.exec_module(changelog)


SAMPLE_CHANGELOG = """\
# Changelog

Intro text.

## [Unreleased]

## [v0.11.0] - 2026-04-02

### Added

- SEP-100: Old feature

[Unreleased]: https://github.com/percona/SEP/compare/v0.11.0...HEAD
[v0.11.0]: https://github.com/percona/SEP/compare/v0.10.0...v0.11.0
"""


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Set up a fresh repo layout in ``tmp_path`` and chdir into it.

    :param tmp_path: pytest's per-test temporary directory.
    :type tmp_path: pathlib.Path
    :param monkeypatch: pytest monkeypatch fixture.
    :type monkeypatch: pytest.MonkeyPatch
    :return: The temporary repo root.
    :rtype: pathlib.Path
    """
    (tmp_path / "changelog.d").mkdir()
    (tmp_path / "CHANGELOG.md").write_text(SAMPLE_CHANGELOG, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


# --- add subcommand --------------------------------------------------------


def test_add_creates_fragment(repo):
    """Running ``add`` writes a fragment file with the given message.

    :param repo: Test repo fixture.
    :type repo: pathlib.Path
    """
    exit_code = changelog.main(
        ["add", "--ticket", "SEP-503", "--section", "added", "--message", "New alert"],
    )
    assert exit_code == 0
    fragment = repo / "changelog.d" / "SEP-503.added.md"
    assert fragment.exists()
    assert fragment.read_text(encoding="utf-8") == "New alert\n"


def test_add_rejects_duplicate_without_force(repo, capsys):
    """``add`` fails if the fragment already exists and ``--force`` is not set.

    :param repo: Test repo fixture.
    :type repo: pathlib.Path
    :param capsys: pytest output capture fixture.
    :type capsys: pytest.CaptureFixture
    """
    (repo / "changelog.d" / "SEP-503.added.md").write_text("First\n", encoding="utf-8")
    exit_code = changelog.main(
        ["add", "--ticket", "SEP-503", "--section", "added", "--message", "Second"],
    )
    assert exit_code == 1
    assert "already exists" in capsys.readouterr().err
    assert (repo / "changelog.d" / "SEP-503.added.md").read_text(
        encoding="utf-8",
    ) == "First\n"


def test_add_force_overwrites(repo):
    """``add --force`` overwrites an existing fragment.

    :param repo: Test repo fixture.
    :type repo: pathlib.Path
    """
    (repo / "changelog.d" / "SEP-503.added.md").write_text("First\n", encoding="utf-8")
    exit_code = changelog.main(
        [
            "add",
            "--ticket",
            "SEP-503",
            "--section",
            "added",
            "--message",
            "Second",
            "--force",
        ],
    )
    assert exit_code == 0
    assert (repo / "changelog.d" / "SEP-503.added.md").read_text(
        encoding="utf-8",
    ) == "Second\n"


def test_add_rejects_invalid_ticket(repo, capsys):
    """``add`` rejects ticket keys that do not match ``SEP-<digits>``.

    :param repo: Test repo fixture.
    :type repo: pathlib.Path
    :param capsys: pytest output capture fixture.
    :type capsys: pytest.CaptureFixture
    """
    exit_code = changelog.main(
        ["add", "--ticket", "FOO-1", "--section", "added", "--message", "x"],
    )
    assert exit_code == 1
    assert "invalid ticket" in capsys.readouterr().err


def test_add_rejects_multiline_message(repo, capsys):
    """``add`` refuses a message that spans multiple lines.

    :param repo: Test repo fixture.
    :type repo: pathlib.Path
    :param capsys: pytest output capture fixture.
    :type capsys: pytest.CaptureFixture
    """
    exit_code = changelog.main(
        [
            "add",
            "--ticket",
            "SEP-503",
            "--section",
            "added",
            "--message",
            "line one\nline two",
        ],
    )
    assert exit_code == 1
    assert "single line" in capsys.readouterr().err


# --- check subcommand ------------------------------------------------------


def test_check_passes_on_empty_dir(repo):
    """``check`` exits 0 when ``changelog.d/`` contains no fragments.

    :param repo: Test repo fixture.
    :type repo: pathlib.Path
    """
    assert changelog.main(["check"]) == 0


def test_check_passes_on_valid_fragments(repo):
    """``check`` exits 0 when all fragments are well-formed.

    :param repo: Test repo fixture.
    :type repo: pathlib.Path
    """
    (repo / "changelog.d" / "SEP-503.added.md").write_text("Fix\n", encoding="utf-8")
    (repo / "changelog.d" / "SEP-816.changed.md").write_text(
        "Tweak\n", encoding="utf-8"
    )
    assert changelog.main(["check"]) == 0


def test_check_fails_on_malformed_filename(repo, capsys):
    """``check`` rejects fragments whose filename does not match the pattern.

    :param repo: Test repo fixture.
    :type repo: pathlib.Path
    :param capsys: pytest output capture fixture.
    :type capsys: pytest.CaptureFixture
    """
    (repo / "changelog.d" / "SEP-503.bogus.md").write_text("x\n", encoding="utf-8")
    assert changelog.main(["check"]) == 1
    assert "invalid filename" in capsys.readouterr().err


def test_check_fails_on_empty_fragment(repo, capsys):
    """``check`` rejects fragments whose content is empty after stripping.

    :param repo: Test repo fixture.
    :type repo: pathlib.Path
    :param capsys: pytest output capture fixture.
    :type capsys: pytest.CaptureFixture
    """
    (repo / "changelog.d" / "SEP-503.added.md").write_text("   \n\n", encoding="utf-8")
    assert changelog.main(["check"]) == 1
    assert "empty" in capsys.readouterr().err


def test_check_fails_on_bullet_prefix(repo, capsys):
    """``check`` rejects fragments that contain the leading ``- SEP-XXX:`` prefix.

    :param repo: Test repo fixture.
    :type repo: pathlib.Path
    :param capsys: pytest output capture fixture.
    :type capsys: pytest.CaptureFixture
    """
    (repo / "changelog.d" / "SEP-503.added.md").write_text(
        "- SEP-503: Fix\n",
        encoding="utf-8",
    )
    assert changelog.main(["check"]) == 1
    assert "must not start with" in capsys.readouterr().err


def test_check_ignores_readme(repo):
    """``check`` ignores ``README.md`` inside ``changelog.d/``.

    :param repo: Test repo fixture.
    :type repo: pathlib.Path
    """
    (repo / "changelog.d" / "README.md").write_text(
        "# Changelog fragments\n",
        encoding="utf-8",
    )
    (repo / "changelog.d" / "SEP-503.added.md").write_text("Fix\n", encoding="utf-8")
    assert changelog.main(["check"]) == 0


# --- list subcommand -------------------------------------------------------


def test_list_groups_and_sorts_by_ticket(repo, capsys):
    """``list`` groups entries by section and sorts by numeric ticket ID.

    :param repo: Test repo fixture.
    :type repo: pathlib.Path
    :param capsys: pytest output capture fixture.
    :type capsys: pytest.CaptureFixture
    """
    (repo / "changelog.d" / "SEP-818.changed.md").write_text("A\n", encoding="utf-8")
    (repo / "changelog.d" / "SEP-503.added.md").write_text("B\n", encoding="utf-8")
    (repo / "changelog.d" / "SEP-100.added.md").write_text("C\n", encoding="utf-8")
    exit_code = changelog.main(["list"])
    assert exit_code == 0
    output = capsys.readouterr().out
    assert output.index("- SEP-100: C") < output.index("- SEP-503: B")
    assert output.index("### Added") < output.index("### Changed")


# --- assemble subcommand ---------------------------------------------------


def test_assemble_inserts_new_section(repo):
    """``assemble`` inserts a new ``[vX.Y.Z]`` section after ``[Unreleased]``.

    :param repo: Test repo fixture.
    :type repo: pathlib.Path
    """
    (repo / "changelog.d" / "SEP-503.added.md").write_text(
        "New alert\n",
        encoding="utf-8",
    )
    exit_code = changelog.main(
        [
            "assemble",
            "--version",
            "0.12.0",
            "--date",
            "2026-04-30",
            "--tickets",
            "SEP-503",
        ],
    )
    assert exit_code == 0
    content = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [v0.12.0] - 2026-04-30" in content
    assert "- SEP-503: New alert" in content
    unreleased_idx = content.index("## [Unreleased]")
    new_idx = content.index("## [v0.12.0]")
    old_idx = content.index("## [v0.11.0]")
    assert unreleased_idx < new_idx < old_idx


def test_assemble_updates_compare_links(repo):
    """``assemble`` rewrites the ``[Unreleased]`` compare link and adds a new one.

    :param repo: Test repo fixture.
    :type repo: pathlib.Path
    """
    (repo / "changelog.d" / "SEP-503.added.md").write_text("Fix\n", encoding="utf-8")
    changelog.main(
        [
            "assemble",
            "--version",
            "0.12.0",
            "--date",
            "2026-04-30",
            "--tickets",
            "SEP-503",
        ],
    )
    content = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert (
        "[Unreleased]: https://github.com/percona/SEP/compare/v0.12.0...HEAD" in content
    )
    assert (
        "[v0.12.0]: https://github.com/percona/SEP/compare/v0.11.0...v0.12.0" in content
    )
    # old unreleased link should be gone
    assert "compare/v0.11.0...HEAD" not in content


def test_assemble_deletes_consumed_fragments(repo):
    """``assemble`` removes fragments belonging to the target fix version.

    :param repo: Test repo fixture.
    :type repo: pathlib.Path
    """
    fragment = repo / "changelog.d" / "SEP-503.added.md"
    fragment.write_text("Fix\n", encoding="utf-8")
    changelog.main(
        [
            "assemble",
            "--version",
            "0.12.0",
            "--date",
            "2026-04-30",
            "--tickets",
            "SEP-503",
        ],
    )
    assert not fragment.exists()


def test_assemble_preserves_post_scope_lock_fragments(repo):
    """``assemble`` leaves fragments whose ticket is not in ``--tickets`` untouched.

    :param repo: Test repo fixture.
    :type repo: pathlib.Path
    """
    consumed = repo / "changelog.d" / "SEP-503.added.md"
    consumed.write_text("Scope\n", encoding="utf-8")
    kept = repo / "changelog.d" / "SEP-999.added.md"
    kept.write_text("PostScopeLock\n", encoding="utf-8")
    changelog.main(
        [
            "assemble",
            "--version",
            "0.12.0",
            "--date",
            "2026-04-30",
            "--tickets",
            "SEP-503",
        ],
    )
    assert not consumed.exists()
    assert kept.exists()
    content = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "- SEP-503: Scope" in content
    assert "SEP-999" not in content


def test_assemble_dry_run_touches_nothing(repo):
    """``assemble --dry-run`` prints the rendered block but does not modify files.

    :param repo: Test repo fixture.
    :type repo: pathlib.Path
    """
    (repo / "changelog.d" / "SEP-503.added.md").write_text("Fix\n", encoding="utf-8")
    original_changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    exit_code = changelog.main(
        [
            "assemble",
            "--version",
            "0.12.0",
            "--date",
            "2026-04-30",
            "--tickets",
            "SEP-503",
            "--dry-run",
        ],
    )
    assert exit_code == 0
    assert (repo / "changelog.d" / "SEP-503.added.md").exists()
    assert (repo / "CHANGELOG.md").read_text(encoding="utf-8") == original_changelog


def test_assemble_multiline_fragment_produces_multiple_entries(repo):
    """A fragment containing multiple non-empty lines is rendered as one entry per line.

    :param repo: Test repo fixture.
    :type repo: pathlib.Path
    """
    (repo / "changelog.d" / "SEP-491.config.md").write_text(
        "First setting\nSecond setting\n",
        encoding="utf-8",
    )
    changelog.main(
        [
            "assemble",
            "--version",
            "0.12.0",
            "--date",
            "2026-04-30",
            "--tickets",
            "SEP-491",
        ],
    )
    content = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "- SEP-491: First setting" in content
    assert "- SEP-491: Second setting" in content


def test_assemble_empty_ticket_list_is_noop(repo):
    """Passing an empty ticket list leaves CHANGELOG.md and fragments unchanged.

    :param repo: Test repo fixture.
    :type repo: pathlib.Path
    """
    (repo / "changelog.d" / "SEP-503.added.md").write_text("Fix\n", encoding="utf-8")
    original = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    exit_code = changelog.main(
        [
            "assemble",
            "--version",
            "0.12.0",
            "--date",
            "2026-04-30",
            "--tickets",
            "",
        ],
    )
    assert exit_code == 1
    assert (repo / "CHANGELOG.md").read_text(encoding="utf-8") == original
    assert (repo / "changelog.d" / "SEP-503.added.md").exists()


def test_assemble_refuses_duplicate_version(repo, capsys):
    """``assemble`` refuses to run if the version section already exists.

    :param repo: Test repo fixture.
    :type repo: pathlib.Path
    :param capsys: pytest output capture fixture.
    :type capsys: pytest.CaptureFixture
    """
    existing = """\
# Changelog

Intro text.

## [Unreleased]

## [v0.12.0] - 2026-04-15

### Added

- SEP-503: Already assembled

## [v0.11.0] - 2026-04-02

### Added

- SEP-100: Old feature

[Unreleased]: https://github.com/percona/SEP/compare/v0.12.0...HEAD
[v0.12.0]: https://github.com/percona/SEP/compare/v0.11.0...v0.12.0
[v0.11.0]: https://github.com/percona/SEP/compare/v0.10.0...v0.11.0
"""
    (repo / "CHANGELOG.md").write_text(existing, encoding="utf-8")
    fragment = repo / "changelog.d" / "SEP-503.added.md"
    fragment.write_text("New alert\n", encoding="utf-8")
    exit_code = changelog.main(
        [
            "assemble",
            "--version",
            "0.12.0",
            "--date",
            "2026-04-30",
            "--tickets",
            "SEP-503",
        ],
    )
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "already contains" in err
    assert (repo / "CHANGELOG.md").read_text(encoding="utf-8") == existing
    assert fragment.exists()


def test_assemble_preserves_section_order(repo):
    """``assemble`` renders sections in the canonical order regardless of fragment order.

    :param repo: Test repo fixture.
    :type repo: pathlib.Path
    """
    (repo / "changelog.d" / "SEP-200.security.md").write_text("CVE\n", encoding="utf-8")
    (repo / "changelog.d" / "SEP-100.added.md").write_text(
        "Feature\n", encoding="utf-8"
    )
    (repo / "changelog.d" / "SEP-150.breaking.md").write_text(
        "Break\n", encoding="utf-8"
    )
    (repo / "changelog.d" / "SEP-175.fixed.md").write_text("Bug\n", encoding="utf-8")
    changelog.main(
        [
            "assemble",
            "--version",
            "0.12.0",
            "--date",
            "2026-04-30",
            "--tickets",
            "SEP-100,SEP-150,SEP-175,SEP-200",
        ],
    )
    content = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    added_idx = content.index("### Added")
    breaking_idx = content.index("### Breaking Changes")
    fixed_idx = content.index("### Fixed")
    security_idx = content.index("### Security")
    assert added_idx < breaking_idx < fixed_idx < security_idx
