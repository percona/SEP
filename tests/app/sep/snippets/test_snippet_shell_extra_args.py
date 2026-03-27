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

"""Test that snippet shells forward extra args when metadata allows them."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from app.sep.snippets.models.snippet import BaseSnippet


def _repo_root() -> Path:
    """Return the repository root directory containing pyproject.toml and snippets/."""
    here = Path(__file__).resolve()
    for base in (here, *here.parents):
        if (base / "pyproject.toml").is_file() and (base / "snippets").is_dir():
            return base
    raise RuntimeError("Repository root not found (pyproject.toml + snippets/).")


REPO_ROOT = _repo_root()
SNIPPETS_DIR = REPO_ROOT / "snippets"


def _gnu_getopt_snippets_runnable() -> bool:
    """Return True if GNU getopt-based snippet scripts run on this host (False on BSD/macOS)."""
    proc = subprocess.run(
        ["bash", str(SNIPPETS_DIR / "pt-summary.sh"), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return proc.returncode == 0


requires_gnu_getopt = pytest.mark.skipif(
    not _gnu_getopt_snippets_runnable(),
    reason="Snippet scripts require GNU getopt (e.g. Linux CI)",
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "expected_allow"),
    [
        ("pt-summary.sh", True),
        ("pt-mysql-summary.sh", True),
        ("pt-stalk.sh", True),
        ("mysql_query_tuning.sh", True),
        ("mysql_replica_status.sh", True),
        ("mysql_tables_without_pk.sh", True),
        ("mysql_gr_queries.sh", True),
        ("disk_usage.sh", False),
        ("mysql_version.sh", False),
        ("dmesg.sh", False),
        ("mysql_config_files.sh", False),
        ("mysql_log_extractor.sh", False),
        ("proxysql_status.sh", False),
    ],
)
async def test_snippet_allow_extra_args_metadata(
    filename: str,
    expected_allow: bool,  # noqa: FBT001
):
    """Assert allow_extra_args in snippet metadata matches the expected value per file."""
    path = SNIPPETS_DIR / filename
    assert path.is_file(), f"missing {path}"
    meta = await BaseSnippet.get_meta_by_path(path)
    assert meta.get("allow_extra_args", False) is expected_allow


@pytest.mark.asyncio
async def test_mysql_query_tuning_meta_uses_allow_extra_not_strict():
    """Assert mysql_query_tuning enables allow_extra_args and does not set strict."""
    meta = await BaseSnippet.get_meta_by_path(SNIPPETS_DIR / "mysql_query_tuning.sh")
    assert "strict" not in meta
    assert meta.get("allow_extra_args") is True


def _prepend_path(env: dict[str, str], directory: Path) -> dict[str, str]:
    """Return a copy of env with directory prepended to PATH."""
    out = {**env}
    out["PATH"] = f"{directory}{os.pathsep}{out.get('PATH', '')}"
    return out


@requires_gnu_getopt
def test_pt_summary_forwards_args_after_double_dash(tmp_path: Path):
    """Assert tokens after -- are forwarded to pt-summary."""
    captured = tmp_path / "args.txt"
    wrapper = tmp_path / "pt-summary"
    wrapper.write_text(
        f'#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" > "{captured}"\nexit 0\n'
    )
    wrapper.chmod(0o755)
    env = _prepend_path(os.environ, tmp_path)
    script = SNIPPETS_DIR / "pt-summary.sh"
    proc = subprocess.run(
        ["bash", str(script), "--", "--custom-tool-flag", "x"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    lines = captured.read_text().splitlines()
    assert "--custom-tool-flag" in lines
    assert "x" in lines


@requires_gnu_getopt
def test_pt_mysql_summary_forwards_args_after_double_dash(tmp_path: Path):
    """Assert tokens after -- are forwarded to pt-mysql-summary."""
    captured = tmp_path / "args.txt"
    wrapper = tmp_path / "pt-mysql-summary"
    wrapper.write_text(
        f'#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" > "{captured}"\nexit 0\n'
    )
    wrapper.chmod(0o755)
    env = _prepend_path(os.environ, tmp_path)
    script = SNIPPETS_DIR / "pt-mysql-summary.sh"
    proc = subprocess.run(
        ["bash", str(script), "--", "--init-command", "SELECT 1"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    lines = captured.read_text().splitlines()
    assert "--init-command" in lines
    assert "SELECT 1" in lines


@requires_gnu_getopt
def test_pt_stalk_forwards_args_after_double_dash(tmp_path: Path):
    """Assert tokens after -- are forwarded to pt-stalk (e.g. --mysql-only)."""
    captured = tmp_path / "args.txt"
    wrapper = tmp_path / "pt-stalk"
    wrapper.write_text(
        f'#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" > "{captured}"\nexit 0\n'
    )
    wrapper.chmod(0o755)
    env = _prepend_path(os.environ, tmp_path)
    script = SNIPPETS_DIR / "pt-stalk.sh"
    proc = subprocess.run(
        [
            "bash",
            str(script),
            "--dest",
            str(tmp_path / "stalk_out"),
            "--",
            "--mysql-only",
        ],
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    text = captured.read_text()
    assert "--mysql-only" in text


@requires_gnu_getopt
def test_mysql_query_tuning_forwards_mysql_flags_with_execute(tmp_path: Path):
    """Assert remaining argv is passed to mysql when --execute is set."""
    captured = tmp_path / "mysql.args"
    mysql_mock = tmp_path / "mysql"
    mysql_mock.write_text(
        f'#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" > "{captured}"\nexit 0\n'
    )
    mysql_mock.chmod(0o755)
    env = _prepend_path(os.environ, tmp_path)
    script = SNIPPETS_DIR / "mysql_query_tuning.sh"
    proc = subprocess.run(
        [
            "bash",
            str(script),
            "--query=SELECT 1",
            "--execute",
            "--",
            "--ssl-mode",
            "DISABLED",
        ],
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    lines = captured.read_text().splitlines()
    assert any(line == "--ssl-mode" or line.startswith("--ssl-mode") for line in lines)
    assert "DISABLED" in lines


def test_mysql_replica_status_forwards_mysql_cli_args(tmp_path: Path):
    """Assert argv after --defaults-file is forwarded to mysql."""
    captured = tmp_path / "mysql.args"
    mysql_mock = tmp_path / "mysql"
    mysql_mock.write_text(
        f'#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" >> "{captured}"\necho OK\nexit 0\n'
    )
    mysql_mock.chmod(0o755)
    env = _prepend_path(os.environ, tmp_path)
    script = SNIPPETS_DIR / "mysql_replica_status.sh"
    proc = subprocess.run(
        [
            "bash",
            str(script),
            "--defaults-file=/tmp/no-such.cnf",
            "-h127.0.0.1",
        ],
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    lines = captured.read_text().splitlines()
    assert "-h127.0.0.1" in lines


def test_mysql_tables_without_pk_forwards_mysql_cli_args(tmp_path: Path):
    """Assert extra mysql client argv is forwarded on the heredoc query path."""
    captured = tmp_path / "mysql.args"
    mysql_mock = tmp_path / "mysql"
    mysql_mock.write_text(
        f'#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" >> "{captured}"\ncat >/dev/null\nexit 0\n'
    )
    mysql_mock.chmod(0o755)
    env = _prepend_path(os.environ, tmp_path)
    script = SNIPPETS_DIR / "mysql_tables_without_pk.sh"
    proc = subprocess.run(
        [
            "bash",
            str(script),
            "--defaults-file=/tmp/no-such.cnf",
            "-h127.0.0.1",
        ],
        env=env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    lines = captured.read_text().splitlines()
    assert "-h127.0.0.1" in lines
