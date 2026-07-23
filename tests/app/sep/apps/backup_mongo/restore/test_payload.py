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
from types import SimpleNamespace

import pytest
import yaml

from app.sep.apps.backup_mongo.pbm_creds_common import (
    _append_pbm_restore_yes_if_supported,
    _PBM_RESTORE_HELP_TIMEOUT_SECONDS,
    RESTORE_YES_BEGIN,
    RESTORE_YES_END,
    restore_yes_source,
)

_PAYLOAD = (
    pathlib.Path(__file__).parents[6]
    / "app/sep/apps/backup_mongo/restore/pbm_logical_restore_payload"
)
_PHYSICAL_PAYLOAD = (
    pathlib.Path(__file__).parents[6]
    / "app/sep/apps/backup_mongo/restore/pbm_physical_restore_payload"
)


def _run_payload_capture_command(
    namespace: str | None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    *,
    restore_help: str,
) -> list[str]:
    """Execute the logical payload with a stubbed process and return its command.

    :param namespace: Namespace value to write to the restore config, or ``None``
        to omit the key.
    :param monkeypatch: Pytest environment and process patch helper.
    :param tmp_path: Temporary directory for config and credentials.
    :param restore_help: Fake ``pbm restore --help`` text used by the ``--yes`` probe.
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

    def _fake_run(cmd: list[str], *args: object, **kwargs: object) -> SimpleNamespace:
        if cmd[:3] == ["pbm", "restore", "--help"]:
            assert kwargs.get("timeout") == _PBM_RESTORE_HELP_TIMEOUT_SECONDS
            return SimpleNamespace(stdout=restore_help, stderr="", returncode=0)
        raise AssertionError(f"Unexpected subprocess.run command: {cmd!r}")

    monkeypatch.setattr(subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(subprocess, "run", _fake_run)

    namespace_globals: dict[str, object] = {}
    exec(compile(_PAYLOAD.read_text(), str(_PAYLOAD), "exec"), namespace_globals)
    os.environ.pop("PBM_MONGODB_URI", None)
    return captured["cmd"]


def test_namespace_filter_reaches_logical_restore_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """Append ``--yes`` (when supported) and the namespace before ``--wait``."""
    command = _run_payload_capture_command(
        "db1.*,db2.collection",
        monkeypatch,
        tmp_path,
        restore_help="Usage:\n  -y, --yes  Don't ask for confirmation\n",
    )

    assert command == [
        "pbm",
        "restore",
        "2026-04-29T10:00:00",
        "--yes",
        "--ns",
        "db1.*,db2.collection",
        "--wait",
    ]


@pytest.mark.parametrize("namespace", [None, ""])
def test_empty_namespace_omits_ns_but_keeps_yes_when_supported(
    namespace: str | None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """Omit ``--ns`` when unset, but still pass ``--yes`` on modern PBM."""
    command = _run_payload_capture_command(
        namespace,
        monkeypatch,
        tmp_path,
        restore_help="Usage:\n  -y, --yes  Don't ask for confirmation\n",
    )

    assert command == [
        "pbm",
        "restore",
        "2026-04-29T10:00:00",
        "--yes",
        "--wait",
    ]


def test_old_pbm_without_yes_keeps_command_compatible(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """Omit ``--yes`` when the installed PBM CLI does not advertise it."""
    command = _run_payload_capture_command(
        None,
        monkeypatch,
        tmp_path,
        restore_help="Usage:\n  -w, --wait  Wait for the restore to finish\n",
    )

    assert command == [
        "pbm",
        "restore",
        "2026-04-29T10:00:00",
        "--wait",
    ]


class TestRestoreYesHelperNoDrift:
    """Assert the restore ``--yes`` probe tracks one canonical generated source."""

    @staticmethod
    def _region(path: pathlib.Path) -> str:
        """Return the restore-yes region carried between the markers in ``path``."""
        lines = path.read_text(encoding="utf-8").split("\n")
        begin = lines.index(RESTORE_YES_BEGIN)
        end = lines.index(RESTORE_YES_END, begin + 1)
        return "\n".join(lines[begin + 1 : end]).strip("\n")

    @pytest.mark.parametrize(
        "payload",
        [_PAYLOAD, _PHYSICAL_PAYLOAD],
        ids=["logical", "physical"],
    )
    def test_region_matches_canonical(self, payload: pathlib.Path) -> None:
        """Require each restore payload's probe to equal the canonical source."""
        assert self._region(payload) == restore_yes_source()


class TestAppendPbmRestoreYesIfSupported:
    """Exercise the importable ``_append_pbm_restore_yes_if_supported`` helper."""

    def test_appends_yes_when_help_advertises_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Append ``--yes`` when help text includes the flag."""

        def _fake_run(
            cmd: list[str], *args: object, **kwargs: object
        ) -> SimpleNamespace:
            assert cmd == ["pbm", "restore", "--help"]
            assert kwargs.get("timeout") == _PBM_RESTORE_HELP_TIMEOUT_SECONDS
            return SimpleNamespace(
                stdout="  -y, --yes  Don't ask for confirmation\n",
                stderr="",
                returncode=0,
            )

        monkeypatch.setattr(subprocess, "run", _fake_run)
        cmd = ["pbm", "restore", "backup"]
        _append_pbm_restore_yes_if_supported(cmd)
        assert cmd == ["pbm", "restore", "backup", "--yes"]

    def test_omits_yes_when_help_lacks_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Leave ``cmd`` unchanged when help does not advertise ``--yes``."""

        def _fake_run(
            cmd: list[str], *args: object, **kwargs: object
        ) -> SimpleNamespace:
            del cmd, args
            assert kwargs.get("timeout") == _PBM_RESTORE_HELP_TIMEOUT_SECONDS
            return SimpleNamespace(stdout="  -w, --wait\n", stderr="", returncode=0)

        monkeypatch.setattr(subprocess, "run", _fake_run)
        cmd = ["pbm", "restore", "backup"]
        _append_pbm_restore_yes_if_supported(cmd)
        assert cmd == ["pbm", "restore", "backup"]

    def test_timeout_warns_without_appending(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Warn on help-probe timeout and leave ``cmd`` unchanged."""

        def _fake_run(
            cmd: list[str], *args: object, **kwargs: object
        ) -> SimpleNamespace:
            del args
            raise subprocess.TimeoutExpired(cmd, timeout=kwargs["timeout"])

        monkeypatch.setattr(subprocess, "run", _fake_run)
        cmd = ["pbm", "restore", "backup"]
        _append_pbm_restore_yes_if_supported(cmd)
        assert cmd == ["pbm", "restore", "backup"]
        assert "timed out while probing for --yes support" in capsys.readouterr().err

    def test_os_error_warns_without_appending(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Warn when ``pbm`` cannot be executed and leave ``cmd`` unchanged."""

        def _fake_run(
            cmd: list[str], *args: object, **kwargs: object
        ) -> SimpleNamespace:
            del cmd, args, kwargs
            raise FileNotFoundError("pbm")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        cmd = ["pbm", "restore", "backup"]
        _append_pbm_restore_yes_if_supported(cmd)
        assert cmd == ["pbm", "restore", "backup"]
        assert "Could not probe pbm restore --help" in capsys.readouterr().err
