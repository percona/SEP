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

"""Tests for the backup payloads' run-result file producer.

The payload scripts import heavy runtime deps (boto3, pymysql) and cannot be
exec'd here, so the filename constant and the pure ``_write_run_result`` helper
are extracted from each payload's source via AST and exec'd in isolation.
"""

import ast
import json
import os
import pathlib

import pytest

from app.tasks.run_result import RUN_RESULT_FILENAME

_PAYLOADS = {
    "mydumper": pathlib.Path(__file__).parents[5]
    / "app/sep/apps/mysql_backups/mydumper_payload",
    "xtrabackup": pathlib.Path(__file__).parents[5]
    / "app/sep/apps/mysql_backups/xtrabackup_payload",
}

# The filename constant plus the writer function.
_RESULT_API_NODE_COUNT = 2


def _load_result_api(path: pathlib.Path):
    """Extract ``RUN_RESULT_FILENAME`` and ``_write_run_result`` from a payload.

    Compile only those two module-level nodes in isolation so the payload's
    heavy imports never run. Raise loudly if either has been renamed or removed.
    """
    tree = ast.parse(path.read_text())
    nodes = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "RUN_RESULT_FILENAME"
                for t in node.targets
            )
        )
        or (isinstance(node, ast.FunctionDef) and node.name == "_write_run_result")
    ]
    if len(nodes) != _RESULT_API_NODE_COUNT:
        raise RuntimeError(
            f"RUN_RESULT_FILENAME / _write_run_result not found in {path}."
        )
    namespace = {"json": json, "os": os}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace["RUN_RESULT_FILENAME"], namespace["_write_run_result"]


@pytest.mark.parametrize("payload", sorted(_PAYLOADS))
def test_filename_matches_canonical_constant(payload):
    """Assert each payload's filename literal equals the canonical constant."""
    filename, _ = _load_result_api(_PAYLOADS[payload])
    assert filename == RUN_RESULT_FILENAME


@pytest.mark.parametrize("payload", sorted(_PAYLOADS))
def test_writes_the_three_facts_to_the_working_directory(
    payload, tmp_path, monkeypatch
):
    """Assert the writer lands one JSON file of the three facts under the CWD."""
    filename, write = _load_result_api(_PAYLOADS[payload])
    monkeypatch.chdir(tmp_path)

    write("/data/backup/20260725", 4096, "s3://bucket/backup")

    assert json.loads((tmp_path / filename).read_text()) == {
        "backup_dir": "/data/backup/20260725",
        "size_bytes": 4096,
        "upload_destination": "s3://bucket/backup",
    }


@pytest.mark.parametrize("payload", sorted(_PAYLOADS))
def test_leaves_no_temp_file_behind(payload, tmp_path, monkeypatch):
    """Assert the write is a rename, so no partial file survives it."""
    filename, write = _load_result_api(_PAYLOADS[payload])
    monkeypatch.chdir(tmp_path)

    write("/data/backup/20260725", 4096, None)

    assert sorted(p.name for p in tmp_path.iterdir()) == [filename]


@pytest.mark.parametrize("payload", sorted(_PAYLOADS))
def test_null_upload_destination_and_zero_size(payload, tmp_path, monkeypatch):
    """Assert a no-upload zero-size backup serializes ``null`` and ``0`` cleanly."""
    filename, write = _load_result_api(_PAYLOADS[payload])
    monkeypatch.chdir(tmp_path)

    write("/data/backup/20260725", 0, None)

    written = json.loads((tmp_path / filename).read_text())
    assert written["upload_destination"] is None
    assert written["size_bytes"] == 0
