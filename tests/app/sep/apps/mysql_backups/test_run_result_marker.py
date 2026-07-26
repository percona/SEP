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

"""Tests for the backup payloads' run-result marker producer.

The payload scripts import heavy runtime deps (boto3, pymysql) and cannot be
exec'd here, so the sentinel constant and the pure ``_build_run_result_marker``
helper are extracted from each payload's source via AST and exec'd in isolation.
"""

import ast
import json
import pathlib

import pytest

from app.tasks.run_result import RUN_RESULT_MARKER

_PAYLOADS = {
    "mydumper": pathlib.Path(__file__).parents[5]
    / "app/sep/apps/mysql_backups/mydumper_payload",
    "xtrabackup": pathlib.Path(__file__).parents[5]
    / "app/sep/apps/mysql_backups/xtrabackup_payload",
}

# The sentinel constant plus the builder function.
_MARKER_API_NODE_COUNT = 2


def _load_marker_api(path: pathlib.Path):
    """Extract ``RUN_RESULT_MARKER`` and ``_build_run_result_marker`` from a payload.

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
                isinstance(t, ast.Name) and t.id == "RUN_RESULT_MARKER"
                for t in node.targets
            )
        )
        or (
            isinstance(node, ast.FunctionDef)
            and node.name == "_build_run_result_marker"
        )
    ]
    if len(nodes) != _MARKER_API_NODE_COUNT:
        raise RuntimeError(
            f"RUN_RESULT_MARKER / _build_run_result_marker not found in {path}."
        )
    namespace = {"json": json}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace["RUN_RESULT_MARKER"], namespace["_build_run_result_marker"]


@pytest.mark.parametrize("payload", sorted(_PAYLOADS))
def test_sentinel_matches_canonical_constant(payload):
    """Assert each payload's sentinel literal equals the canonical constant."""
    marker, _ = _load_marker_api(_PAYLOADS[payload])
    assert marker == RUN_RESULT_MARKER


@pytest.mark.parametrize("payload", sorted(_PAYLOADS))
def test_builds_single_line_marker_with_three_facts(payload):
    """Assert the helper emits one sentinel-prefixed line carrying the three facts."""
    marker, build = _load_marker_api(_PAYLOADS[payload])

    line = build("/data/backup/20260725", 4096, "s3://bucket/backup")

    assert "\n" not in line
    assert line.startswith(marker)
    assert json.loads(line[len(marker) :]) == {
        "backup_dir": "/data/backup/20260725",
        "size_bytes": 4096,
        "upload_destination": "s3://bucket/backup",
    }


@pytest.mark.parametrize("payload", sorted(_PAYLOADS))
def test_null_upload_destination_and_zero_size(payload):
    """Assert a no-upload zero-size backup serializes ``null`` and ``0`` cleanly."""
    marker, build = _load_marker_api(_PAYLOADS[payload])

    payload_json = json.loads(build("/data/backup/20260725", 0, None)[len(marker) :])

    assert payload_json["upload_destination"] is None
    assert payload_json["size_bytes"] == 0
