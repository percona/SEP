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

"""Test the MongoDB logical restore payload command."""

import os
import pathlib
import subprocess

import pytest
import yaml

_PAYLOAD = (
    pathlib.Path(__file__).parents[6]
    / "app/sep/apps/backup_mongo/restore/pbm_logical_restore_payload"
)


def _run_payload_capture_command(
    namespace: str | None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> list[str]:
    """Execute the logical payload with a stubbed process and return its command.

    :param namespace: Namespace value to write to the restore config, or ``None``
        to omit the key.
    :param monkeypatch: Pytest environment and process patch helper.
    :param tmp_path: Temporary directory for config and credentials.
    :return: The command passed to ``subprocess.Popen``.
    """
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    config = {"backupSource": "2026-04-29T10:00:00"}
    if namespace is not None:
        config["namespace"] = namespace
    (task_dir / "script_config").write_text(yaml.safe_dump(config))
    (tmp_path / ".mongodb_uri").write_text("mongodb://localhost:27017/")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("NOMAD_TASK_DIR", str(task_dir))

    captured: dict[str, list[str]] = {}

    class _FakePopen:
        def __init__(self, cmd: list[str], *args: object, **kwargs: object) -> None:
            captured["cmd"] = cmd

        def wait(self) -> None:
            return None

        def poll(self) -> int:
            return 0

    monkeypatch.setattr(subprocess, "Popen", _FakePopen)

    namespace_globals: dict[str, object] = {}
    exec(compile(_PAYLOAD.read_text(), str(_PAYLOAD), "exec"), namespace_globals)
    os.environ.pop("PBM_MONGODB_URI", None)
    return captured["cmd"]


def test_namespace_filter_reaches_logical_restore_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """Append the configured namespace before the wait flag."""
    command = _run_payload_capture_command(
        "db1.*,db2.collection",
        monkeypatch,
        tmp_path,
    )

    assert command == [
        "pbm",
        "restore",
        "2026-04-29T10:00:00",
        "--ns",
        "db1.*,db2.collection",
        "--wait",
    ]


@pytest.mark.parametrize("namespace", [None, ""])
def test_empty_namespace_keeps_logical_restore_command_bare(
    namespace: str | None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """Keep the existing bare restore command when no namespace is configured."""
    command = _run_payload_capture_command(namespace, monkeypatch, tmp_path)

    assert command == [
        "pbm",
        "restore",
        "2026-04-29T10:00:00",
        "--wait",
    ]
