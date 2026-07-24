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
_BACKUP_FAILURE_CODE = 7


def _run_incremental(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    *,
    list_stdout: str = '{"snapshots":[]}',
    list_returncode: int = 0,
    config: dict | None = None,
    backup_returncode: int = 0,
    popen_error: Exception | None = None,
    run_error: Exception | None = None,
) -> list[list[str]]:
    """Exec the incremental payload and return every Popen/run command.

    :param monkeypatch: pytest monkeypatch fixture.
    :param tmp_path: Temporary directory for credentials and task dir.
    :param list_stdout: stdout returned for ``pbm list -o json``.
    :param list_returncode: exit code for ``pbm list``.
    :param config: Optional NOMAD_META_CONFIG mapping.
    :param backup_returncode: exit code reported by ``pbm backup`` / ``pbm config``.
    :param popen_error: Optional error raised when constructing ``Popen``.
    :param run_error: Optional error raised from ``subprocess.run`` (``pbm list``).
    :return: Captured Popen/run command lists in call order.
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
        return FakePopen(
            cmd,
            *args,
            captured=captured,
            returncode=backup_returncode,
            construction_error=popen_error,
            **kwargs,
        )

    def _run(
        cmd: list[str], *args: object, **kwargs: object
    ) -> subprocess.CompletedProcess:
        if run_error is not None:
            raise run_error
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

    def test_list_as_array_detects_incremental(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Treat a top-level list payload as the snapshot list."""
        captured = _run_incremental(
            monkeypatch,
            tmp_path,
            list_stdout=json.dumps([{"name": "base", "backupType": "incremental"}]),
        )
        assert "--base" not in _backup_cmd(captured)

    def test_storage_snapshot_nested_list(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Read nested ``storage.snapshot`` lists from ``pbm list`` JSON."""
        captured = _run_incremental(
            monkeypatch,
            tmp_path,
            list_stdout=json.dumps(
                {"storage": {"snapshot": [{"type": "incremental/base"}]}}
            ),
        )
        assert "--base" not in _backup_cmd(captured)

    def test_skips_non_mapping_snapshot_entries(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Ignore non-dict snapshot entries and still require ``--base``."""
        captured = _run_incremental(
            monkeypatch,
            tmp_path,
            list_stdout=json.dumps({"snapshots": ["bad", {"type": "logical"}]}),
        )
        assert "--base" in _backup_cmd(captured)

    def test_list_failure_aborts(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Abort when ``pbm list`` fails rather than guessing ``--base``."""
        with pytest.raises(SystemExit) as exc_info:
            _run_incremental(monkeypatch, tmp_path, list_stdout="", list_returncode=1)
        assert exc_info.value.code == 1

    def test_list_oserror_aborts(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Abort when ``pbm list`` cannot be executed."""
        with pytest.raises(SystemExit) as exc_info:
            _run_incremental(
                monkeypatch,
                tmp_path,
                run_error=OSError("No such file or directory: 'pbm'"),
            )
        assert exc_info.value.code == 1

    def test_list_parse_failure_aborts(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Abort when ``pbm list`` stdout is not valid YAML/JSON."""
        with pytest.raises(SystemExit) as exc_info:
            _run_incremental(
                monkeypatch, tmp_path, list_stdout="{unterminated", list_returncode=0
            )
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


class TestIncrementalCommandExtras:
    """Cover compression, storage apply, and failure paths on the incremental runner."""

    def test_compression_flags_appended(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Append compression flags after the incremental type/base/wait group."""
        captured = _run_incremental(
            monkeypatch,
            tmp_path,
            config={"backup": {"compression": "gzip", "compressionLevel": 6}},
        )
        cmd = _backup_cmd(captured)
        assert cmd == [
            "pbm",
            "backup",
            "--type",
            "incremental",
            "--base",
            "--wait",
            "--compression",
            "gzip",
            "--compression-level",
            "6",
        ]

    def test_applies_storage_config_before_backup(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Run ``pbm config --file`` when storage is present, stripping selective keys."""
        captured = _run_incremental(
            monkeypatch,
            tmp_path,
            config={
                "storage": {
                    "type": "filesystem",
                    "filesystem": {"path": "/tmp/e2e-pbm"},
                },
                "backup": {
                    "compression": "s2",
                    "namespaces": "db.*",
                    "withUsersAndRoles": True,
                },
            },
        )
        assert ["pbm", "config", "--file", f"{tmp_path}/script_config"] in captured
        written = yaml.safe_load((tmp_path / "script_config").read_text())
        assert written["storage"]["type"] == "filesystem"
        assert written["backup"] == {"compression": "s2"}
        assert "namespaces" not in written["backup"]

    def test_bad_config_aborts(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Abort when NOMAD_META_CONFIG is present but not a mapping."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("NOMAD_TASK_DIR", str(tmp_path))
        monkeypatch.setenv("NOMAD_META_CONFIG", "- just a list\n")
        (tmp_path / ".mongodb_uri").write_text("mongodb://localhost:27017/")

        def _should_not_run(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("should not run")

        monkeypatch.setattr(subprocess, "Popen", _should_not_run)
        monkeypatch.setattr(subprocess, "run", _should_not_run)
        with pytest.raises(SystemExit) as exc_info:
            run_payload(_INCREMENTAL_PAYLOAD)
        assert exc_info.value.code == 1

    def test_backup_nonzero_exit_propagates(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Propagate a non-zero ``pbm backup`` exit code."""
        with pytest.raises(SystemExit) as exc_info:
            _run_incremental(
                monkeypatch, tmp_path, backup_returncode=_BACKUP_FAILURE_CODE
            )
        assert exc_info.value.code == _BACKUP_FAILURE_CODE

    def test_backup_oserror_aborts(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """Abort when ``pbm backup`` cannot be executed."""
        with pytest.raises(SystemExit) as exc_info:
            _run_incremental(
                monkeypatch,
                tmp_path,
                popen_error=OSError("No such file or directory: 'pbm'"),
            )
        assert exc_info.value.code == 1
