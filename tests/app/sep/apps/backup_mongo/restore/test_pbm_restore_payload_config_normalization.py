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

"""Exercise the payload-level ``script_config`` normalization in the restore payloads.

``yaml.safe_load`` can legally return a truthy non-dict (a bare scalar or a list),
so ``restore/pbm_logical_restore_payload``, ``restore/pbm_physical_restore_payload``,
and ``restore/pbm_restore_config_payload`` all normalize a non-dict parse result to
``{}`` right after loading ``script_config``, before it feeds ``_creds_path_from_config``
or is read with ``.get()`` / ``.items()``. These tests exec the real payloads with
``subprocess.Popen`` stubbed, feeding a malformed ``script_config`` file, and assert
the documented fallback/exit behavior is reached instead of an ``AttributeError``
traceback.
"""

import pathlib
import subprocess

import pytest
import yaml

from tests.app.sep.apps.backup_mongo.pbm_payload_exec import FakePopen, run_payload

_APP_DIR = (
    pathlib.Path(__file__).resolve().parents[6] / "app/sep/apps/backup_mongo/restore"
)
_RESTORE_PAYLOADS = {
    "logical": _APP_DIR / "pbm_logical_restore_payload",
    "physical": _APP_DIR / "pbm_physical_restore_payload",
}
_MALFORMED_CONFIGS = {
    "bare_scalar": "just a string\n",
    "list": "- one\n- two\n",
}


class TestLogicalAndPhysicalRestoreConfigNormalization:
    """Cover the ``script_config`` load site shared by the two restore payloads."""

    @pytest.mark.parametrize("payload", ["logical", "physical"])
    @pytest.mark.parametrize("malformed", sorted(_MALFORMED_CONFIGS))
    def test_non_dict_config_falls_back_to_home_credentials(
        self,
        payload: str,
        malformed: str,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ):
        """Resolve credentials via the ``$HOME`` fallback instead of raising.

        With no ``backupSource`` reachable on the normalized (empty) config, the
        payload still exits cleanly on the documented ``BACKUP_SOURCE`` check
        rather than crashing on ``config.get(...)`` for a non-dict config.
        """
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("NOMAD_TASK_DIR", str(tmp_path))
        (tmp_path / ".mongodb_uri").write_text("mongodb://localhost:27017/")
        (tmp_path / "script_config").write_text(_MALFORMED_CONFIGS[malformed])
        monkeypatch.setattr(subprocess, "Popen", FakePopen)

        with pytest.raises(SystemExit) as exc:
            run_payload(_RESTORE_PAYLOADS[payload])

        assert exc.value.code == 1
        assert "BACKUP_SOURCE (backup name) is required" in capsys.readouterr().out


class TestRestoreConfigPayloadNormalization:
    """Cover the two ``script_config`` / ``current_pbm_config`` load sites."""

    def test_unreadable_script_config_exits_cleanly(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ):
        """Exit 1 with the documented message when ``script_config`` can't be read.

        Covers the ``except`` branch around the ``script_config`` load, distinct
        from the non-dict normalization it wraps.
        """
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("NOMAD_TASK_DIR", str(tmp_path))
        (tmp_path / ".mongodb_uri").write_text("mongodb://localhost:27017/")
        # No script_config file is written, so the open() call raises.

        with pytest.raises(SystemExit) as exc:
            run_payload(_APP_DIR / "pbm_restore_config_payload")

        assert exc.value.code == 1
        assert "Error reading script_config" in capsys.readouterr().err

    @pytest.mark.parametrize("malformed", sorted(_MALFORMED_CONFIGS))
    def test_non_dict_script_config_skips_restore_update_cleanly(
        self,
        malformed: str,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ):
        """Normalize a non-dict ``script_config`` to ``{}`` and skip the update.

        A non-dict ``script_config`` also implies an empty ``restore`` section, so
        the payload takes the documented "no restore configuration provided" exit
        path instead of raising on ``script_config.get(...)``.
        """
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("NOMAD_TASK_DIR", str(tmp_path))
        (tmp_path / ".mongodb_uri").write_text("mongodb://localhost:27017/")
        (tmp_path / "script_config").write_text(_MALFORMED_CONFIGS[malformed])

        current_pbm_config = yaml.safe_dump(
            {"storage": {"type": "s3", "s3": {"bucket": "backups"}}}
        )

        def _communicate_result(cmd: list[str]) -> tuple[bytes, bytes]:
            if cmd[:2] == ["pbm", "config"] and "--file" not in cmd:
                return current_pbm_config.encode(), b""
            return b"", b""

        monkeypatch.setattr(
            subprocess,
            "Popen",
            lambda cmd, *a, **kw: FakePopen(
                cmd, *a, communicate_result=_communicate_result, **kw
            ),
        )

        run_payload(_APP_DIR / "pbm_restore_config_payload")

        assert (
            "No restore configuration provided, skipping update"
            in capsys.readouterr().out
        )

    def test_non_dict_current_pbm_config_does_not_crash(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
    ):
        """Normalize a non-dict ``pbm config`` readback instead of raising on ``.get()``.

        ``pbm config``'s stdout is attacker-controlled only in the sense that any
        external ``pbm`` bug could hand back malformed YAML; the payload must still
        take the documented "Storage is not configured" exit rather than crash.
        """
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("NOMAD_TASK_DIR", str(tmp_path))
        (tmp_path / ".mongodb_uri").write_text("mongodb://localhost:27017/")
        (tmp_path / "script_config").write_text(yaml.safe_dump({"restore": {}}))

        def _communicate_result(cmd: list[str]) -> tuple[bytes, bytes]:
            if cmd[:2] == ["pbm", "config"] and "--file" not in cmd:
                return b"- malformed\n- list\n", b""
            return b"", b""

        monkeypatch.setattr(
            subprocess,
            "Popen",
            lambda cmd, *a, **kw: FakePopen(
                cmd, *a, communicate_result=_communicate_result, **kw
            ),
        )

        with pytest.raises(SystemExit) as exc:
            run_payload(_APP_DIR / "pbm_restore_config_payload")

        assert exc.value.code == 1
        assert "Storage is not configured in PBM" in capsys.readouterr().out
