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

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPT_PATH = _PROJECT_ROOT / "scripts" / "check_alembic_revision_tree.py"

_spec = importlib.util.spec_from_file_location(
    "check_alembic_revision_tree", _SCRIPT_PATH
)
assert _spec is not None, f"cannot load {_SCRIPT_PATH}"
assert _spec.loader is not None, f"cannot load {_SCRIPT_PATH}"
check_alembic_revision_tree = importlib.util.module_from_spec(_spec)
sys.modules["check_alembic_revision_tree"] = check_alembic_revision_tree
_spec.loader.exec_module(check_alembic_revision_tree)

_REVISION_TEMPLATE = """\
revision = {revision!r}
down_revision = {down_revision!r}
branch_labels = None
depends_on = None

def upgrade():
    pass

def downgrade():
    pass
"""


def _write_revision(
    versions_dir: Path, revision: str, down_revision: str | None
) -> None:
    """Write a minimal Alembic revision module.

    :param versions_dir: Directory that holds revision modules.
    :param revision: Revision id.
    :param down_revision: Parent revision id, or ``None`` for a root.
    """
    versions_dir.mkdir(parents=True, exist_ok=True)
    (versions_dir / f"{revision}.py").write_text(
        _REVISION_TEMPLATE.format(revision=revision, down_revision=down_revision),
        encoding="utf-8",
    )


def _write_ini(
    tmp_path: Path,
    *,
    databases: str,
    sections: dict[str, dict[str, str]],
) -> Path:
    """Write a minimal ``alembic.ini`` for synthetic trees.

    :param tmp_path: Pytest temporary directory.
    :param databases: Value for ``[alembic] databases``.
    :param sections: Named section options keyed by section name.
    :return: Path to the written ini file.
    """
    lines = [
        "[alembic]",
        f"databases = {databases}",
        "version_path_separator = :",
        "",
        "[DEFAULT]",
        "path_separator = :",
        "",
    ]
    for name, options in sections.items():
        lines.append(f"[{name}]")
        for key, value in options.items():
            lines.append(f"{key} = {value}")
        lines.append("")
    ini_path = tmp_path / "alembic.ini"
    ini_path.write_text("\n".join(lines), encoding="utf-8")
    return ini_path


def _dummy_script_location(tmp_path: Path, name: str = "migrations") -> Path:
    """Create a dummy ``script_location`` directory with an empty ``env.py``.

    :param tmp_path: Pytest temporary directory.
    :param name: Directory name under ``tmp_path``.
    :return: The script location path.
    """
    script_location = tmp_path / name
    script_location.mkdir(parents=True, exist_ok=True)
    (script_location / "env.py").write_text("", encoding="utf-8")
    return script_location


def test_check_fails_on_forked_tree(tmp_path, capsys):
    """Fail when one root fans out into more heads than roots."""
    script_location = _dummy_script_location(tmp_path)
    versions_dir = script_location / "versions"
    _write_revision(versions_dir, "aaaa", None)
    _write_revision(versions_dir, "bbbb", "aaaa")
    _write_revision(versions_dir, "cccc", "aaaa")
    ini_path = _write_ini(
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
    script_location = _dummy_script_location(tmp_path)
    versions_dir = script_location / "versions"
    _write_revision(versions_dir, "r1", None)
    _write_revision(versions_dir, "h1", "r1")
    _write_revision(versions_dir, "r2", None)
    _write_revision(versions_dir, "h2", "r2")
    ini_path = _write_ini(
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
    script_location = _dummy_script_location(tmp_path)
    versions_dir = script_location / "versions"
    _write_revision(versions_dir, "base", None)
    _write_revision(versions_dir, "c1", "base")
    _write_revision(versions_dir, "c2", "base")
    merge_template = """\
revision = 'm'
down_revision = ('c1', 'c2')
branch_labels = None
depends_on = None

def upgrade():
    pass

def downgrade():
    pass
"""
    (versions_dir / "m.py").write_text(merge_template, encoding="utf-8")
    ini_path = _write_ini(
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


def test_discovers_tracks_from_databases_key(tmp_path):
    """Discover track names from ``[alembic] databases``, not hard-coded lists."""
    script_a = _dummy_script_location(tmp_path, "migrations_a")
    script_b = _dummy_script_location(tmp_path, "migrations_b")
    (script_a / "versions").mkdir()
    (script_b / "versions").mkdir()
    ini_path = _write_ini(
        tmp_path,
        databases="widget, gadget",
        sections={
            "widget": {"script_location": str(script_a)},
            "gadget": {"script_location": str(script_b)},
        },
    )

    assert check_alembic_revision_tree.list_track_names(ini_path) == (
        "widget",
        "gadget",
    )


def test_rejects_databases_with_no_track_names(tmp_path, capsys):
    """Fail closed when ``databases`` parses to an empty track list."""
    ini_path = _write_ini(tmp_path, databases=",", sections={})

    with pytest.raises(ValueError, match="missing or empty"):
        check_alembic_revision_tree.list_track_names(ini_path)

    assert check_alembic_revision_tree.main(["--ini", str(ini_path)]) == 1
    assert "databases" in capsys.readouterr().err


def test_uses_version_locations_from_ini(tmp_path, capsys):
    """Read ``version_locations`` from the ini instead of hard-coded paths."""
    script_location = _dummy_script_location(tmp_path)
    versions_a = tmp_path / "chain_a"
    versions_b = tmp_path / "chain_b"
    _write_revision(versions_a, "ra", None)
    _write_revision(versions_a, "ha", "ra")
    _write_revision(versions_b, "rb", None)
    _write_revision(versions_b, "hb", "rb")
    ini_path = _write_ini(
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
    ini_path = _PROJECT_ROOT / "alembic.ini"
    trees = check_alembic_revision_tree.inspect_revision_trees(ini_path)
    names = {tree.name for tree in trees}
    assert {"tasks", "inventory", "sep"} <= names
    assert all(not tree.is_forked for tree in trees)


def test_reintroducing_sep_1824_fork_fails(tmp_path, capsys):
    """Fail when the SEP-1824 fork is reintroduced in the tasks track."""
    versions_copy = tmp_path / "versions"
    shutil.copytree(
        _PROJECT_ROOT / "app" / "tasks" / "migrations" / "versions",
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

    script_location = _PROJECT_ROOT / "app" / "tasks" / "migrations"
    ini_path = _write_ini(
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
    assert "a19da5cf0bca" in tree.heads
    assert "e2f3a4b5c6d7" in tree.heads

    error = check_alembic_revision_tree.format_fork_error(tree)
    assert "tasks" in error
    assert "a19da5cf0bca" in error
    assert "e2f3a4b5c6d7" in error

    assert check_alembic_revision_tree.main(["--ini", str(ini_path)]) == 1
    err = capsys.readouterr().err
    assert "tasks" in err
    assert "a19da5cf0bca" in err
    assert "e2f3a4b5c6d7" in err
