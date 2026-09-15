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

"""Tests for the ``scripts/check_alembic_revision_tree.py`` CLI."""

from __future__ import annotations

import shutil

from tests.scripts import load_script, PROJECT_ROOT
from tests.scripts.alembic_tree import (
    dummy_script_location,
    write_ini,
    write_revision,
)

check_alembic_revision_tree = load_script("check_alembic_revision_tree")


def test_check_fails_on_forked_tree(tmp_path, capsys):
    """Fail when one root fans out into more heads than roots."""
    script_location = dummy_script_location(tmp_path)
    versions_dir = script_location / "versions"
    write_revision(versions_dir, "aaaa", None)
    write_revision(versions_dir, "bbbb", "aaaa")
    write_revision(versions_dir, "cccc", "aaaa")
    ini_path = write_ini(
        tmp_path,
        databases="widget",
        sections={
            "widget": {
                "script_location": str(script_location),
            },
        },
    )

    trees = check_alembic_revision_tree.inspect_revision_trees(ini_path)
    assert len(trees) == 1
    tree = trees[0]
    assert tree.is_forked is True
    assert set(tree.heads) == {"bbbb", "cccc"}
    assert tree.roots == ("aaaa",)

    error = check_alembic_revision_tree.format_fork_error(tree)
    assert "widget" in error
    assert "bbbb" in error
    assert "cccc" in error

    assert check_alembic_revision_tree.main(["--ini", str(ini_path)]) == 1
    err = capsys.readouterr().err
    assert "bbbb" in err
    assert "cccc" in err


def test_check_passes_on_converged_multibranch_tree(tmp_path, capsys):
    """Pass when independent branches each have one root and one head."""
    script_location = dummy_script_location(tmp_path)
    versions_dir = script_location / "versions"
    write_revision(versions_dir, "r1", None)
    write_revision(versions_dir, "h1", "r1")
    write_revision(versions_dir, "r2", None)
    write_revision(versions_dir, "h2", "r2")
    ini_path = write_ini(
        tmp_path,
        databases="widget",
        sections={
            "widget": {
                "script_location": str(script_location),
            },
        },
    )

    trees = check_alembic_revision_tree.inspect_revision_trees(ini_path)
    assert len(trees) == 1
    assert trees[0].is_forked is False

    assert check_alembic_revision_tree.main(["--ini", str(ini_path)]) == 0
    out = capsys.readouterr().out
    assert "widget" in out


def test_check_passes_on_reconverged_siblings(tmp_path, capsys):
    """Pass when sibling branches merge back into one head."""
    script_location = dummy_script_location(tmp_path)
    versions_dir = script_location / "versions"
    write_revision(versions_dir, "base", None)
    write_revision(versions_dir, "c1", "base")
    write_revision(versions_dir, "c2", "base")
    write_revision(versions_dir, "m", ("c1", "c2"))
    ini_path = write_ini(
        tmp_path,
        databases="widget",
        sections={
            "widget": {
                "script_location": str(script_location),
            },
        },
    )

    trees = check_alembic_revision_tree.inspect_revision_trees(ini_path)
    assert len(trees) == 1
    assert trees[0].is_forked is False
    assert check_alembic_revision_tree.main(["--ini", str(ini_path)]) == 0


def test_rejects_empty_databases_via_cli(tmp_path, capsys):
    """Exit 1 when ``[alembic] databases`` parses to no track names."""
    ini_path = write_ini(tmp_path, databases=",", sections={})

    assert check_alembic_revision_tree.main(["--ini", str(ini_path)]) == 1
    assert "databases" in capsys.readouterr().err


def test_uses_version_locations_from_ini(tmp_path, capsys):
    """Read ``version_locations`` from the ini instead of hard-coded paths."""
    script_location = dummy_script_location(tmp_path)
    versions_a = tmp_path / "chain_a"
    versions_b = tmp_path / "chain_b"
    write_revision(versions_a, "ra", None)
    write_revision(versions_a, "ha", "ra")
    write_revision(versions_b, "rb", None)
    write_revision(versions_b, "hb", "rb")
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

    trees = check_alembic_revision_tree.inspect_revision_trees(ini_path)
    assert len(trees) == 1
    assert trees[0].is_forked is False
    assert set(trees[0].roots) == {"ra", "rb"}
    assert set(trees[0].heads) == {"ha", "hb"}
    assert check_alembic_revision_tree.main(["--ini", str(ini_path)]) == 0


def test_repo_alembic_ini_is_converged():
    """Confirm the committed repo tree has no forked Alembic tracks."""
    ini_path = PROJECT_ROOT / "alembic.ini"
    trees = check_alembic_revision_tree.inspect_revision_trees(ini_path)
    names = {tree.name for tree in trees}
    assert {"tasks", "inventory", "sep"} <= names
    assert all(not tree.is_forked for tree in trees)


def test_reintroducing_sep_1824_fork_fails(tmp_path, capsys):
    """Fail when the SEP-1824 fork is reintroduced in the tasks track."""
    versions_copy = tmp_path / "versions"
    shutil.copytree(
        PROJECT_ROOT / "app" / "tasks" / "migrations" / "versions",
        versions_copy,
    )
    fork_file = versions_copy / (
        "2026_08_13_2143-a19da5cf0bca_add_taskhistory_log_state_capture_status.py"
    )
    text = fork_file.read_text(encoding="utf-8")
    text = text.replace(
        'down_revision: Union[str, None] = "e2f3a4b5c6d7"',
        'down_revision: Union[str, None] = "6a19d56d7985"',
    )
    text = text.replace(
        'down_revision = "e2f3a4b5c6d7"',
        'down_revision = "6a19d56d7985"',
    )
    fork_file.write_text(text, encoding="utf-8")

    script_location = PROJECT_ROOT / "app" / "tasks" / "migrations"
    ini_path = write_ini(
        tmp_path,
        databases="tasks",
        sections={
            "tasks": {
                "script_location": str(script_location),
                "version_locations": str(versions_copy),
            },
        },
    )

    trees = check_alembic_revision_tree.inspect_revision_trees(ini_path)
    assert len(trees) == 1
    tree = trees[0]
    assert tree.name == "tasks"
    assert tree.is_forked is True
    assert len(tree.heads) == len(tree.roots) + 1
    assert "e2f3a4b5c6d7" in tree.heads

    error = check_alembic_revision_tree.format_fork_error(tree)
    assert "tasks" in error
    assert "e2f3a4b5c6d7" in error

    assert check_alembic_revision_tree.main(["--ini", str(ini_path)]) == 1
    err = capsys.readouterr().err
    assert "tasks" in err
    assert "e2f3a4b5c6d7" in err
