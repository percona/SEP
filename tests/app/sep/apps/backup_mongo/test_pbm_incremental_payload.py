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

"""Tests for the PBM incremental backup payload base-vs-subsequent detection."""

import json
import pathlib
import subprocess

import pytest
import yaml

from tests.app.sep.apps.backup_mongo.pbm_payload_exec import FakePopen, run_payload

_APP_DIR = pathlib.Path(__file__).parents[5] / "app/sep/apps/backup_mongo"
_INCREMENTAL_PAYLOAD = _APP_DIR / "pbm_incremental_payload"


def _run_incremental(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    *,
    list_stdout: str = '{"snapshots":[]}',
    list_returncode: int = 0,
    config: dict | None = None,
) -> list[list[str]]:
    """Exec the incremental payload and return every Popen command.

    :param monkeypatch: pytest monkeypatch fixture.
    :param tmp_path: Temporary directory for credentials and task dir.
    :param list_stdout: stdout returned for ``pbm list -o json``.
    :param list_returncode: exit code for ``pbm list``.
    :param config: Optional NOMAD_META_CONFIG mapping.
    :return: Captured Popen command lists in call order.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("NOMAD_TASK_DIR", str(tmp_path))
    (tmp_path / ".mongodb_uri").write_text("mongodb://localhost:27017/")
    if config is None:
        monkeypatch.delenv("NOMAD_META_CONFIG", raising=False)
    else:
        monkeypatch.setenv("NOMAD_META_CONFIG", yaml.safe_dump(config))

    captured: list[list[str]] = []

    def _popen(cmd: list[str], *args: object, **kwargs: object) -> FakePopen:
        return FakePopen(cmd, *args, captured=captured, **kwargs)

    def _run(
        cmd: list[str], *args: object, **kwargs: object
    ) -> subprocess.CompletedProcess:
        captured.append(list(cmd))
        return subprocess.CompletedProcess(
            cmd, list_returncode, stdout=list_stdout, stderr=""
        )

    monkeypatch.setattr(subprocess, "Popen", _popen)
    monkeypatch.setattr(subprocess, "run", _run)
    run_payload(_INCREMENTAL_PAYLOAD)
    return captured


def _backup_cmd(captured: list[list[str]]) -> list[str]:
    """Return the ``pbm backup`` command from captured Popen/run calls."""
    for cmd in captured:
        if cmd[:2] == ["pbm", "backup"]:
            return cmd
    raise AssertionError(f"no pbm backup command in {captured!r}")


class TestIncrementalBaseDetection:
    """Exercise runtime ``--base`` selection for incremental backups."""

    def test_first_run_uses_base(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Emit ``--base`` when ``pbm list`` shows no incremental snapshots."""
        captured = _run_incremental(monkeypatch, tmp_path)
        cmd = _backup_cmd(captured)
        assert cmd == [
            "pbm",
            "backup",
            "--type",
            "incremental",
            "--base",
            "--wait",
        ]

    def test_subsequent_run_skips_base(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Omit ``--base`` when an incremental snapshot already exists."""
        captured = _run_incremental(
            monkeypatch,
            tmp_path,
            list_stdout=json.dumps(
                {"snapshots": [{"name": "2026-01-01", "type": "incremental"}]}
            ),
        )
        cmd = _backup_cmd(captured)
        assert cmd == ["pbm", "backup", "--type", "incremental", "--wait"]
        assert "--base" not in cmd

    def test_list_failure_aborts(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Abort when ``pbm list`` fails rather than guessing ``--base``."""
        with pytest.raises(SystemExit) as exc_info:
            _run_incremental(monkeypatch, tmp_path, list_stdout="", list_returncode=1)
        assert exc_info.value.code == 1

    def test_namespaces_never_emitted(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Never emit ``--ns`` on incremental even when namespaces are configured."""
        captured = _run_incremental(
            monkeypatch,
            tmp_path,
            config={
                "backup": {
                    "namespaces": "db1.*,db2.coll",
                    "withUsersAndRoles": True,
                }
            },
        )
        cmd = _backup_cmd(captured)
        assert "--ns" not in cmd
        assert "--with-users-and-roles" not in cmd
