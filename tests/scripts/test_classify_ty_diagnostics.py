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

"""Tests for the ``scripts/classify_ty_diagnostics.py`` CLI."""

import re

import pytest

from tests.scripts import load_script

classify_ty_diagnostics = load_script("classify_ty_diagnostics")

ARTIFACT_LINE = 12
ARTIFACT_COLUMN = 9
DUPLICATE_ROWS = 3
ARTIFACT_ROW = (
    "tests/app/core/test_config.py:12:9: warning[unknown-argument] "
    "Argument `_env_file` does not match any known parameter"
)
FIRST_PARTY_ROW = (
    "tests/app/sep/test_config.py:145:9: warning[unknown-argument] "
    "Argument `PMM` does not match any known parameter"
)
NOTE_BLOCK = (
    "app/core/db/crud.py:227:24: warning[no-matching-overload] "
    "No overload of bound method `AsyncSession.exec` matches arguments\n"
    "        🚨 You probably want to use `session.exec()` instead of `session.execute()`.\n"
    "        This is the original SQLAlchemy `session.execute()` method that returns objects\n"
    "        ```Python\n"
    "        heroes = await session.exec(select(Hero)).all()\n"
    "        ```\n"
)


def _output(*rows, total=None):
    """Render ``rows`` as ty concise output with a ``Found N diagnostics`` trailer.

    :param rows: Raw output lines, each already newline-free or note-block shaped.
    :param total: The count to write into the trailer; defaults to ``len(rows)``.
    :return: The rendered output text.
    """
    body = "".join(row if row.endswith("\n") else f"{row}\n" for row in rows)
    count = len(rows) if total is None else total
    return f"{body}Found {count} diagnostics\n"


def _write(tmp_path, name, text):
    """Write ``text`` to ``tmp_path/name`` and return the path.

    :param tmp_path: pytest's per-test temporary directory.
    :param name: The filename to create under ``tmp_path``.
    :param text: UTF-8 contents to write.
    :return: The newly-written path.
    """
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _manifest(tmp_path, before_text):
    """Emit a baseline manifest from ``before_text`` and return its path.

    :param tmp_path: pytest's per-test temporary directory.
    :param before_text: ty concise output to capture as the baseline.
    :return: The path the manifest was written to.
    """
    source = _write(tmp_path, "before.txt", before_text)
    manifest = tmp_path / "baseline.json"
    assert (
        classify_ty_diagnostics.main(
            ["baseline", "--from", str(source), "--out", str(manifest)]
        )
        == 0
    )
    return manifest


def _check(tmp_path, manifest, after_text):
    """Run ``check`` over ``after_text`` against ``manifest`` and return its exit code.

    :param tmp_path: pytest's per-test temporary directory.
    :param manifest: The baseline manifest path.
    :param after_text: ty concise output for the post-suppression run.
    :return: The CLI exit status.
    """
    source = _write(tmp_path, "after.txt", after_text)
    return classify_ty_diagnostics.main(
        ["check", "--from", str(source), "--baseline", str(manifest)]
    )


def test_parse_captures_rule_and_message():
    """Capture the rule and message of a concise diagnostic row."""
    (diagnostic,) = classify_ty_diagnostics.parse_diagnostics(_output(ARTIFACT_ROW))

    assert diagnostic.path == "tests/app/core/test_config.py"
    assert diagnostic.line == ARTIFACT_LINE
    assert diagnostic.column == ARTIFACT_COLUMN
    assert diagnostic.rule == "unknown-argument"
    assert (
        diagnostic.message == "Argument `_env_file` does not match any known parameter"
    )


def test_parse_ignores_note_block_continuations():
    """Skip the indented continuations of a note block instead of counting them."""
    diagnostics = classify_ty_diagnostics.parse_diagnostics(
        _output(NOTE_BLOCK, total=1)
    )

    assert [d.rule for d in diagnostics] == ["no-matching-overload"]


def test_parse_counts_duplicate_positions_separately():
    """Count repeated ``file:line:col`` rows as distinct diagnostics."""
    diagnostics = classify_ty_diagnostics.parse_diagnostics(
        _output(ARTIFACT_ROW, ARTIFACT_ROW, ARTIFACT_ROW)
    )

    assert len(diagnostics) == DUPLICATE_ROWS


def test_parse_rejects_total_disagreeing_with_trailer():
    """Fail when the parsed row count disagrees with ty's own total."""
    with pytest.raises(
        classify_ty_diagnostics.ReconciliationError, match="ty reported 4"
    ):
        classify_ty_diagnostics.parse_diagnostics(
            _output(ARTIFACT_ROW, FIRST_PARTY_ROW, total=4)
        )


def test_parse_rejects_output_without_trailer():
    """Fail loudly when ty printed no trailer, rather than trusting a truncated run."""
    with pytest.raises(classify_ty_diagnostics.ReconciliationError, match="trailer"):
        classify_ty_diagnostics.parse_diagnostics(f"{ARTIFACT_ROW}\n")


def test_parse_accepts_a_run_with_no_diagnostics():
    """Return an empty list for a clean run rather than raising."""
    assert classify_ty_diagnostics.parse_diagnostics("Found 0 diagnostics\n") == []


def test_classify_splits_a_mixed_unknown_argument_shape():
    """Separate the pydantic-settings kwarg from the first-party one under one rule."""
    artifact, first_party = classify_ty_diagnostics.parse_diagnostics(
        _output(ARTIFACT_ROW, FIRST_PARTY_ROW)
    )

    assert classify_ty_diagnostics.classify(artifact.fingerprint) is not None
    assert classify_ty_diagnostics.classify(first_party.fingerprint) is None


def test_classify_confines_absent_modules_to_the_scaffolded_paths():
    """Treat an unresolvable import outside the known paths as a first-party defect."""
    scaffolded, mistyped = classify_ty_diagnostics.parse_diagnostics(
        _output(
            "tests/app/sep/apps/framework/golden/task/app.py:9:20: "
            "warning[unresolved-import] Cannot resolve imported module "
            "`app.sep.apps.golden_task.models`",
            "app/sep/routes/reports.py:9:20: warning[unresolved-import] "
            "Cannot resolve imported module `app.sep.reprots`",
        )
    )

    assert classify_ty_diagnostics.classify(scaffolded.fingerprint) is not None
    assert classify_ty_diagnostics.classify(mistyped.fingerprint) is None


def test_check_passes_when_only_artifacts_were_removed(tmp_path, capsys):
    """Accept a run whose every dropped fingerprint is classified as an artifact."""
    manifest = _manifest(tmp_path, _output(ARTIFACT_ROW, FIRST_PARTY_ROW))

    assert _check(tmp_path, manifest, _output(FIRST_PARTY_ROW)) == 0
    assert "unknown-argument" in capsys.readouterr().out


def test_check_fails_when_an_artifact_still_reports(tmp_path, capsys):
    """Reject a run still emitting an artifact that is not listed in ``RETAINED``."""
    manifest = _manifest(tmp_path, _output(ARTIFACT_ROW, FIRST_PARTY_ROW))

    assert _check(tmp_path, manifest, _output(ARTIFACT_ROW, FIRST_PARTY_ROW)) == 1
    out = capsys.readouterr().out
    assert "unknown-argument" in out
    assert "tests/app/core/test_config.py" in out


def test_check_fails_when_a_first_party_diagnostic_was_suppressed(tmp_path, capsys):
    """Name the first-party fingerprint a suppression removed, even when totals reconcile."""
    manifest = _manifest(tmp_path, _output(ARTIFACT_ROW, FIRST_PARTY_ROW))
    unrelated = (
        "app/sep/config.py:474:5: warning[invalid-assignment] "
        "Object of type `FieldInfo` is not assignable to `int`"
    )

    assert _check(tmp_path, manifest, _output(unrelated)) == 1
    out = capsys.readouterr().out
    assert "tests/app/sep/test_config.py" in out
    assert "`PMM`" in out


def test_check_names_the_rule_and_delta_when_the_drop_is_wrong(tmp_path, capsys):
    """Report the rule and the delta when more rows dropped than the classification predicts."""
    manifest = _manifest(tmp_path, _output(ARTIFACT_ROW, FIRST_PARTY_ROW))

    assert _check(tmp_path, manifest, _output()) == 1
    assert re.search(
        r"unknown-argument.*dropped 2.*expected 1", capsys.readouterr().out
    )


def test_check_honours_and_reports_a_retained_entry(tmp_path, capsys, monkeypatch):
    """Accept a still-reporting artifact that ``RETAINED`` names, and print the entry."""
    retained = classify_ty_diagnostics.Retained(
        fingerprint=(
            "tests/app/core/test_config.py",
            "unknown-argument",
            "Argument `_env_file` does not match any known parameter",
        ),
        reason="collides on one line with a first-party hit that cannot be split",
    )
    monkeypatch.setattr(classify_ty_diagnostics, "RETAINED", (retained,))
    manifest = _manifest(tmp_path, _output(ARTIFACT_ROW, FIRST_PARTY_ROW))

    assert _check(tmp_path, manifest, _output(ARTIFACT_ROW, FIRST_PARTY_ROW)) == 0
    assert retained.reason in capsys.readouterr().out


def test_check_fails_when_a_retained_entry_no_longer_matches(
    tmp_path, capsys, monkeypatch
):
    """Reject a stale ``RETAINED`` entry whose fingerprint the run no longer emits."""
    stale = classify_ty_diagnostics.Retained(
        fingerprint=("app/gone.py", "unknown-argument", "Argument `_env_file` x"),
        reason="stale",
    )
    manifest = _manifest(tmp_path, _output(ARTIFACT_ROW, FIRST_PARTY_ROW))
    monkeypatch.setattr(classify_ty_diagnostics, "RETAINED", (stale,))

    assert _check(tmp_path, manifest, _output(FIRST_PARTY_ROW)) == 1
    assert "app/gone.py" in capsys.readouterr().out


def test_report_prints_a_zero_row_for_a_group_with_no_hits(tmp_path, capsys):
    """Print a zero row, not a stale warning, for a group the run does not match.

    Every group reaches zero on a neutralized tree, so a zero in ``report`` is the
    expected end state rather than a signal.
    """
    source = _write(tmp_path, "run.txt", _output(FIRST_PARTY_ROW))

    assert classify_ty_diagnostics.main(["report", "--from", str(source)]) == 0
    out = capsys.readouterr().out
    assert "    0  pydantic-settings-private-kwargs" in out
    assert "STALE" not in out


def test_check_names_a_group_that_matched_nothing_in_the_baseline(tmp_path, capsys):
    """Raise staleness against the baseline, the only run where a zero means drift."""
    manifest = _manifest(tmp_path, _output(ARTIFACT_ROW, FIRST_PARTY_ROW))

    assert _check(tmp_path, manifest, _output(FIRST_PARTY_ROW)) == 0
    out = capsys.readouterr().out
    assert "STALE groups (matched nothing in the baseline): 10" in out
    assert "pydantic-settings-private-kwargs" not in out.split("STALE groups")[1]


def test_report_flags_a_line_holding_an_artifact_and_a_first_party_hit(
    tmp_path, capsys
):
    """Flag a ``file:line:rule`` a per-site comment cannot discriminate."""
    collision = (
        "tests/app/sep/test_config.py:145:40: warning[unknown-argument] "
        "Argument `_env_file` does not match any known parameter"
    )
    source = _write(tmp_path, "run.txt", _output(FIRST_PARTY_ROW, collision))

    assert classify_ty_diagnostics.main(["report", "--from", str(source)]) == 0
    out = capsys.readouterr().out
    assert "tests/app/sep/test_config.py:145" in out
    assert "Unsuppressable-by-comment sites: 1" in out
