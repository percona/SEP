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

"""Tests for the ``scripts/merge_alembic_heads.py`` CLI."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from alembic.config import Config
from alembic.script import ScriptDirectory

from tests.scripts import load_script, PROJECT_ROOT
from tests.scripts.alembic_tree import (
    script_location_with_mako,
    write_ini,
    write_revision,
)

if TYPE_CHECKING:
    from pathlib import Path

merge_alembic_heads = load_script("merge_alembic_heads")
check_alembic_revision_tree = load_script("check_alembic_revision_tree")


def _script_directory(ini_path: Path, track: str) -> ScriptDirectory:
    """Load the revision map for one named track.

    :param ini_path: Path to the synthetic ``alembic.ini``.
    :param track: Section name.
    :return: Loaded ``ScriptDirectory``.
    """
    return ScriptDirectory.from_config(Config(str(ini_path), ini_section=track))


def _revision_files(versions_dir: Path) -> set[str]:
    """Return basenames of revision modules under ``versions_dir``.

    :param versions_dir: Directory that holds revision modules.
    :return: Set of ``*.py`` filenames.
    """
    return {path.name for path in versions_dir.glob("*.py")}


def _down_revision_parents(text: str) -> set[str]:
    """Parse parent revision ids from a revision module's ``down_revision``.

    :param text: Source of a revision module.
    :return: Set of parent revision ids (empty when ``down_revision`` is None).
    """
    match = re.search(r"down_revision[^=]*=\s*(.+)", text)
    assert match is not None, "down_revision assignment not found"
    value = match.group(1).strip()
    if value == "None":
        return set()
    return {a or b for a, b in re.findall(r"'([^']+)'|\"([^\"]+)\"", value)}


def _assert_merge_file(
    versions_dir: Path,
    *,
    parents: set[str],
) -> Path:
    """Find the merge revision written under ``versions_dir`` and check it.

    :param versions_dir: Directory expected to contain the new merge file.
    :param parents: Expected ``down_revision`` parent ids.
    :return: Path to the merge revision file.
    """
    by_slug = sorted(versions_dir.glob("*merge*.py"))
    assert by_slug, f"no merge revision found under {versions_dir}"
    merge_path = by_slug[0]
    text = merge_path.read_text(encoding="utf-8")
    assert _down_revision_parents(text) == parents
    assert re.search(r"branch_labels.*=\s*None", text)
    return merge_path


def test_noop_on_converged_single_branch(tmp_path, capsys):
    """Exit 0 and write nothing when a single-branch track is already converged."""
    script_location = script_location_with_mako(tmp_path)
    versions_dir = script_location / "versions"
    write_revision(versions_dir, "aaaa", None)
    write_revision(versions_dir, "bbbb", "aaaa")
    before = _revision_files(versions_dir)
    ini_path = write_ini(
        tmp_path,
        databases="widget",
        sections={"widget": {"script_location": str(script_location)}},
    )

    assert merge_alembic_heads.main(["--ini", str(ini_path)]) == 0
    assert _revision_files(versions_dir) == before
    assert "No forked Alembic heads" in capsys.readouterr().out


def test_noop_on_converged_multibranch_tree(tmp_path, capsys):
    """Exit 0 when independent branches each already have one head."""
    script_location = script_location_with_mako(tmp_path)
    versions_dir = script_location / "versions"
    write_revision(versions_dir, "r1", None)
    write_revision(versions_dir, "h1", "r1")
    write_revision(versions_dir, "r2", None)
    write_revision(versions_dir, "h2", "r2")
    before = _revision_files(versions_dir)
    ini_path = write_ini(
        tmp_path,
        databases="widget",
        sections={"widget": {"script_location": str(script_location)}},
    )

    assert merge_alembic_heads.main(["--ini", str(ini_path)]) == 0
    assert _revision_files(versions_dir) == before
    assert "No forked Alembic heads" in capsys.readouterr().out


def test_merges_simple_two_head_fork(tmp_path, capsys):
    """Create one merge revision that joins two forked heads under one root."""
    script_location = script_location_with_mako(tmp_path)
    versions_dir = script_location / "versions"
    write_revision(versions_dir, "aaaa", None)
    write_revision(versions_dir, "bbbb", "aaaa")
    write_revision(versions_dir, "cccc", "aaaa")
    ini_path = write_ini(
        tmp_path,
        databases="widget",
        sections={"widget": {"script_location": str(script_location)}},
    )

    assert merge_alembic_heads.main(["--ini", str(ini_path)]) == 0
    out = capsys.readouterr().out
    assert "bbbb" in out
    assert "cccc" in out

    script = _script_directory(ini_path, "widget")
    assert len(script.get_heads()) == 1
    assert list(script.get_bases()) == ["aaaa"]
    _assert_merge_file(versions_dir, parents={"bbbb", "cccc"})

    trees = check_alembic_revision_tree.inspect_revision_trees(ini_path)
    assert len(trees) == 1
    assert trees[0].is_forked is False
    assert check_alembic_revision_tree.main(["--ini", str(ini_path)]) == 0


def test_merges_three_head_fork_into_one_revision(tmp_path):
    """Resolve three forked heads with a single three-parent merge revision."""
    script_location = script_location_with_mako(tmp_path)
    versions_dir = script_location / "versions"
    # Avoid revision id "base" — it collides with Alembic's special "base" token.
    write_revision(versions_dir, "root0", None)
    write_revision(versions_dir, "c1", "root0")
    write_revision(versions_dir, "c2", "root0")
    write_revision(versions_dir, "c3", "root0")
    ini_path = write_ini(
        tmp_path,
        databases="widget",
        sections={"widget": {"script_location": str(script_location)}},
    )

    actions = merge_alembic_heads.merge_forked_heads(ini_path)
    assert len(actions) == 1
    assert set(actions[0].heads) == {"c1", "c2", "c3"}

    script = _script_directory(ini_path, "widget")
    assert len(script.get_heads()) == 1
    _assert_merge_file(versions_dir, parents={"c1", "c2", "c3"})


def test_merges_only_forked_branch_in_multibranch_track(tmp_path):
    """Leave unforked branches alone when only one branch in a track is forked."""
    script_location = script_location_with_mako(tmp_path)
    versions_main = (tmp_path / "main" / "versions").resolve()
    versions_plugin = (tmp_path / "plugin" / "versions").resolve()
    write_revision(versions_main, "r1", None, branch_labels=("sep_main",))
    write_revision(versions_main, "h1a", "r1")
    write_revision(versions_main, "h1b", "r1")
    write_revision(versions_plugin, "r2", None, branch_labels=("alerts",))
    write_revision(versions_plugin, "h2", "r2")
    plugin_before = _revision_files(versions_plugin)
    ini_path = write_ini(
        tmp_path,
        databases="widget",
        sections={
            "widget": {
                "script_location": str(script_location),
                "version_locations": f"{versions_main}:{versions_plugin}",
            },
        },
    )

    assert merge_alembic_heads.main(["--ini", str(ini_path)]) == 0

    script = _script_directory(ini_path, "widget")
    heads = set(script.get_heads())
    bases = set(script.get_bases())
    assert bases == {"r1", "r2"}
    assert len(heads) == 2  # noqa: PLR2004
    assert "h2" in heads
    assert "h1a" not in heads
    assert "h1b" not in heads
    _assert_merge_file(versions_main, parents={"h1a", "h1b"})
    assert _revision_files(versions_plugin) == plugin_before

    merge_head = next(h for h in heads if h != "h2")
    assert script.get_revision(merge_head).branch_labels == {"sep_main"}
    assert script.get_revision("h2").branch_labels == {"alerts"}
    assert (
        check_alembic_revision_tree.inspect_revision_trees(ini_path)[0].is_forked
        is False
    )


def test_merges_two_forked_branches_separately(tmp_path):
    """Create one merge revision per forked branch when two branches fork at once."""
    script_location = script_location_with_mako(tmp_path)
    versions_a = (tmp_path / "chain_a" / "versions").resolve()
    versions_b = (tmp_path / "chain_b" / "versions").resolve()
    write_revision(versions_a, "ra", None, branch_labels=("branch_a",))
    write_revision(versions_a, "ha1", "ra")
    write_revision(versions_a, "ha2", "ra")
    write_revision(versions_b, "rb", None, branch_labels=("branch_b",))
    write_revision(versions_b, "hb1", "rb")
    write_revision(versions_b, "hb2", "rb")
    ini_path = write_ini(
        tmp_path,
        databases="widget",
        sections={
            "widget": {
                "script_location": str(script_location),
                "version_locations": f"{versions_a}:{versions_b}",
            },
        },
    )

    actions = merge_alembic_heads.merge_forked_heads(ini_path)
    assert len(actions) == 2  # noqa: PLR2004
    assert {frozenset(action.heads) for action in actions} == {
        frozenset({"ha1", "ha2"}),
        frozenset({"hb1", "hb2"}),
    }

    script = _script_directory(ini_path, "widget")
    assert len(script.get_heads()) == 2  # noqa: PLR2004
    assert set(script.get_bases()) == {"ra", "rb"}
    _assert_merge_file(versions_a, parents={"ha1", "ha2"})
    _assert_merge_file(versions_b, parents={"hb1", "hb2"})


def test_groups_by_root_not_branch_label(tmp_path):
    """Group unlabeled forked heads by shared root (tasks/inventory shape)."""
    script_location = script_location_with_mako(tmp_path)
    versions_dir = script_location / "versions"
    write_revision(versions_dir, "root", None)  # no branch_labels
    write_revision(versions_dir, "left", "root")
    write_revision(versions_dir, "right", "root")
    ini_path = write_ini(
        tmp_path,
        databases="tasks",
        sections={"tasks": {"script_location": str(script_location)}},
    )

    script = _script_directory(ini_path, "tasks")
    groups = merge_alembic_heads.group_heads_by_root(script)
    assert groups == {"root": ("left", "right")}

    actions = merge_alembic_heads.merge_forked_heads(ini_path)
    assert len(actions) == 1
    assert actions[0].message == "merge tasks migration heads"
    for head in ("left", "right"):
        # Reload after merge would change heads; inspect the parents' labels
        # from the original script map used for grouping.
        assert not script.get_revision(head).branch_labels


def test_fork_in_one_track_does_not_block_another(tmp_path, capsys):
    """Merge every forked track in one run; a fork elsewhere does not stop others."""
    widget_loc = script_location_with_mako(tmp_path, "widget_migrations")
    gadget_loc = script_location_with_mako(tmp_path, "gadget_migrations")
    widget_versions = widget_loc / "versions"
    gadget_versions = gadget_loc / "versions"
    write_revision(widget_versions, "wa", None)
    write_revision(widget_versions, "wb", "wa")
    write_revision(widget_versions, "wc", "wa")
    write_revision(gadget_versions, "ga", None)
    write_revision(gadget_versions, "gb", "ga")
    write_revision(gadget_versions, "gc", "ga")
    ini_path = write_ini(
        tmp_path,
        databases="widget, gadget",
        sections={
            "widget": {"script_location": str(widget_loc)},
            "gadget": {"script_location": str(gadget_loc)},
        },
    )

    assert merge_alembic_heads.main(["--ini", str(ini_path)]) == 0
    out = capsys.readouterr().out
    assert "widget" in out
    assert "gadget" in out

    widget = _script_directory(ini_path, "widget")
    gadget = _script_directory(ini_path, "gadget")
    assert len(widget.get_heads()) == 1
    assert len(gadget.get_heads()) == 1
    _assert_merge_file(widget_versions, parents={"wb", "wc"})
    _assert_merge_file(gadget_versions, parents={"gb", "gc"})


def test_merge_revision_declares_no_branch_label(tmp_path):
    """Assert generated merge revisions set ``branch_labels = None``.

    Uses the sep-track ``script.py.mako`` so the Sequence annotation change
    in that template is exercised, not only the tasks copy.
    """
    sep_mako = PROJECT_ROOT / "app" / "sep" / "migrations" / "script.py.mako"
    script_location = script_location_with_mako(tmp_path, mako_template=sep_mako)
    versions_dir = script_location / "versions"
    write_revision(versions_dir, "root", None, branch_labels=("sep_main",))
    write_revision(versions_dir, "left", "root")
    write_revision(versions_dir, "right", "root")
    ini_path = write_ini(
        tmp_path,
        databases="sep",
        sections={"sep": {"script_location": str(script_location)}},
    )

    merge_alembic_heads.merge_forked_heads(ini_path)
    merge_path = _assert_merge_file(versions_dir, parents={"left", "right"})
    text = merge_path.read_text(encoding="utf-8")
    assert "down_revision: Union[str, Sequence[str], None]" in text
    assert "branch_labels: Union[str, Sequence[str], None] = None" in text

    script = _script_directory(ini_path, "sep")
    head = script.get_heads()[0]
    assert script.get_revision(head).branch_labels == {"sep_main"}


def test_new_root_with_branch_label_is_not_a_fork(tmp_path, capsys):
    """Treat a table-owning app root (new head + new root) as converged, not a fork."""
    script_location = script_location_with_mako(tmp_path)
    versions_main = (tmp_path / "main" / "versions").resolve()
    versions_new = (tmp_path / "new_app" / "versions").resolve()
    write_revision(versions_main, "r1", None, branch_labels=("sep_main",))
    write_revision(versions_main, "h1", "r1")
    write_revision(versions_new, "r_new", None, branch_labels=("new_app",))
    before_main = _revision_files(versions_main)
    before_new = _revision_files(versions_new)
    ini_path = write_ini(
        tmp_path,
        databases="widget",
        sections={
            "widget": {
                "script_location": str(script_location),
                "version_locations": f"{versions_main}:{versions_new}",
            },
        },
    )

    assert merge_alembic_heads.main(["--ini", str(ini_path)]) == 0
    assert "No forked Alembic heads" in capsys.readouterr().out
    assert _revision_files(versions_main) == before_main
    assert _revision_files(versions_new) == before_new

    script = _script_directory(ini_path, "widget")
    assert set(script.get_heads()) == {"h1", "r_new"}
    assert set(script.get_bases()) == {"r1", "r_new"}


def test_idempotent_after_merge(tmp_path, capsys):
    """Write no further revisions on a second run after a successful merge."""
    script_location = script_location_with_mako(tmp_path)
    versions_dir = script_location / "versions"
    write_revision(versions_dir, "aaaa", None)
    write_revision(versions_dir, "bbbb", "aaaa")
    write_revision(versions_dir, "cccc", "aaaa")
    ini_path = write_ini(
        tmp_path,
        databases="widget",
        sections={"widget": {"script_location": str(script_location)}},
    )

    assert merge_alembic_heads.main(["--ini", str(ini_path)]) == 0
    after_first = _revision_files(versions_dir)
    assert merge_alembic_heads.main(["--ini", str(ini_path)]) == 0
    assert _revision_files(versions_dir) == after_first
    assert "No forked Alembic heads" in capsys.readouterr().out


def test_message_uses_branch_label_when_present(tmp_path):
    """Prefer the inherited branch label over the track name in the merge message."""
    script_location = script_location_with_mako(tmp_path)
    versions_dir = script_location / "versions"
    write_revision(versions_dir, "root", None, branch_labels=("sep_main",))
    write_revision(versions_dir, "left", "root")
    write_revision(versions_dir, "right", "root")
    ini_path = write_ini(
        tmp_path,
        databases="sep",
        sections={"sep": {"script_location": str(script_location)}},
    )

    actions = merge_alembic_heads.plan_merges(ini_path, "sep")
    assert len(actions) == 1
    assert actions[0].message == "merge sep_main migration heads"


def test_partial_merge_reports_already_written_files(tmp_path, capsys, monkeypatch):
    """Report merge files already written for earlier tracks on mid-run failure."""
    widget_loc = script_location_with_mako(tmp_path, "widget_migrations")
    gadget_loc = script_location_with_mako(tmp_path, "gadget_migrations")
    widget_versions = widget_loc / "versions"
    gadget_versions = gadget_loc / "versions"
    write_revision(widget_versions, "wa", None)
    write_revision(widget_versions, "wb", "wa")
    write_revision(widget_versions, "wc", "wa")
    write_revision(gadget_versions, "ga", None)
    write_revision(gadget_versions, "gb", "ga")
    write_revision(gadget_versions, "gc", "ga")
    ini_path = write_ini(
        tmp_path,
        databases="widget, gadget",
        sections={
            "widget": {"script_location": str(widget_loc)},
            "gadget": {"script_location": str(gadget_loc)},
        },
    )

    real_merge = merge_alembic_heads.command.merge
    call_count = {"n": 0}

    def flaky_merge(config, revisions, message=None, **kwargs):
        call_count["n"] += 1
        if call_count["n"] > 1:
            raise merge_alembic_heads.CommandError("simulated merge failure")
        return real_merge(config, revisions=revisions, message=message, **kwargs)

    monkeypatch.setattr(merge_alembic_heads.command, "merge", flaky_merge)

    assert merge_alembic_heads.main(["--ini", str(ini_path)]) == 1
    err = capsys.readouterr().err
    assert "Error after creating 1 merge revision(s)" in err
    assert "working tree may contain new migration files" in err
    assert "widget" in err
    assert list(widget_versions.glob("*merge*.py"))
    assert not list(gadget_versions.glob("*merge*.py"))


def test_partial_merge_reports_same_track_second_branch(tmp_path, capsys, monkeypatch):
    """Report the first merge when a later forked root on the same track fails."""
    script_location = script_location_with_mako(tmp_path)
    versions_a = (tmp_path / "chain_a" / "versions").resolve()
    versions_b = (tmp_path / "chain_b" / "versions").resolve()
    write_revision(versions_a, "ra", None, branch_labels=("branch_a",))
    write_revision(versions_a, "ha1", "ra")
    write_revision(versions_a, "ha2", "ra")
    write_revision(versions_b, "rb", None, branch_labels=("branch_b",))
    write_revision(versions_b, "hb1", "rb")
    write_revision(versions_b, "hb2", "rb")
    ini_path = write_ini(
        tmp_path,
        databases="widget",
        sections={
            "widget": {
                "script_location": str(script_location),
                "version_locations": f"{versions_a}:{versions_b}",
            },
        },
    )

    real_merge = merge_alembic_heads.command.merge
    call_count = {"n": 0}

    def flaky_merge(config, revisions, message=None, **kwargs):
        call_count["n"] += 1
        if call_count["n"] > 1:
            raise merge_alembic_heads.CommandError("simulated same-track failure")
        return real_merge(config, revisions=revisions, message=message, **kwargs)

    monkeypatch.setattr(merge_alembic_heads.command, "merge", flaky_merge)

    assert merge_alembic_heads.main(["--ini", str(ini_path)]) == 1
    err = capsys.readouterr().err
    assert "Error after creating 1 merge revision(s)" in err
    assert "working tree may contain new migration files" in err
    assert "simulated same-track failure" in err
    # plan_merges sorts by root id; "ra" precedes "rb", so chain_a is merged first.
    assert list(versions_a.glob("*merge*.py"))
    assert not list(versions_b.glob("*merge*.py"))


def test_first_merge_failure_reports_plain_error(tmp_path, capsys, monkeypatch):
    """Return 1 with the cause only when the first merge fails before any write."""
    script_location = script_location_with_mako(tmp_path)
    versions_dir = script_location / "versions"
    write_revision(versions_dir, "aaaa", None)
    write_revision(versions_dir, "bbbb", "aaaa")
    write_revision(versions_dir, "cccc", "aaaa")
    before = _revision_files(versions_dir)
    ini_path = write_ini(
        tmp_path,
        databases="widget",
        sections={"widget": {"script_location": str(script_location)}},
    )

    def failing_merge(config, revisions, message=None, **kwargs):
        raise merge_alembic_heads.CommandError("simulated first merge failure")

    monkeypatch.setattr(merge_alembic_heads.command, "merge", failing_merge)

    assert merge_alembic_heads.main(["--ini", str(ini_path)]) == 1
    err = capsys.readouterr().err
    assert "simulated first merge failure" in err
    assert "Error after creating" not in err
    assert "working tree may contain new migration files" not in err
    assert _revision_files(versions_dir) == before
    assert not list(versions_dir.glob("*merge*.py"))
