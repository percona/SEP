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

"""Tests for the ``pbm backup`` compression-flag builder.

The logical and physical payload scripts cannot be exec'd in the test
environment (their module-level ``pbm()`` call spawns ``subprocess`` and
calls ``sys.exit``), so ``_compression_flags`` is extracted from the payload
source via AST and executed in isolation — exercising the real production
function without running the script. The helper is pure (builtins only), so
this round-trips the actual command-assembly logic.
"""

import ast
import os
import pathlib
import subprocess
from collections.abc import Callable

import pytest
import yaml

from app.sep.apps.backup_mongo.models import BackupCreate, BackupType
from app.sep.apps.backup_mongo.spec import (
    BackupMongoResolved,
    build_backup_mongo_spec,
)

_APP_DIR = pathlib.Path(__file__).parents[5] / "app/sep/apps/backup_mongo"
_PAYLOADS = {
    "logical": _APP_DIR / "pbm_logical_payload",
    "physical": _APP_DIR / "pbm_physical_payload",
}


def _extract_compression_flags(payload_path: pathlib.Path) -> Callable:
    """Extract and compile ``_compression_flags`` from a payload via AST.

    Parse the payload source, isolate the ``_compression_flags`` function
    definition, and compile only that node so no module-level side effects
    run. Fail loudly if the function is missing (renamed or removed).

    :param payload_path: Path to the payload script to extract from.
    :return: The compiled ``_compression_flags`` callable.
    """
    source = payload_path.read_text()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_compression_flags":
            module = ast.Module(body=[node], type_ignores=[])
            namespace: dict[str, object] = {}
            exec(compile(module, str(payload_path), "exec"), namespace)
            return namespace["_compression_flags"]
    raise RuntimeError(
        f"_compression_flags not found in {payload_path}. "
        "Has the function been renamed or removed?"
    )


_FLAG_BUILDERS = {name: _extract_compression_flags(p) for name, p in _PAYLOADS.items()}
_PARAMETRIZE_PAYLOADS = pytest.mark.parametrize("payload", ["logical", "physical"])


class TestCompressionFlags:
    """Exercise the extracted ``_compression_flags`` helper."""

    @_PARAMETRIZE_PAYLOADS
    def test_compression_only(self, payload: str):
        """Emit ``--compression <value>`` for a configured compression."""
        flags = _FLAG_BUILDERS[payload]({"backup": {"compression": "gzip"}})
        assert flags == ["--compression", "gzip"]

    @_PARAMETRIZE_PAYLOADS
    def test_compression_with_level(self, payload: str):
        """Emit both the compression and level flags, in order."""
        flags = _FLAG_BUILDERS[payload](
            {"backup": {"compression": "gzip", "compressionLevel": 6}}
        )
        assert flags == ["--compression", "gzip", "--compression-level", "6"]

    @_PARAMETRIZE_PAYLOADS
    def test_s2_is_emitted_explicitly(self, payload: str):
        """Emit the default ``s2`` explicitly for a deterministic command."""
        flags = _FLAG_BUILDERS[payload]({"backup": {"compression": "s2"}})
        assert flags == ["--compression", "s2"]

    @_PARAMETRIZE_PAYLOADS
    def test_level_zero_is_emitted(self, payload: str):
        """Emit level ``0`` — a valid level guarded by ``is not None``."""
        flags = _FLAG_BUILDERS[payload](
            {"backup": {"compression": "gzip", "compressionLevel": 0}}
        )
        assert flags == ["--compression", "gzip", "--compression-level", "0"]

    @_PARAMETRIZE_PAYLOADS
    def test_level_without_compression_omits_all(self, payload: str):
        """Omit a bare ``--compression-level`` when compression is unset."""
        flags = _FLAG_BUILDERS[payload]({"backup": {"compressionLevel": 6}})
        assert flags == []

    @_PARAMETRIZE_PAYLOADS
    @pytest.mark.parametrize(
        "config",
        [
            {},
            {"backup": {}},
            {"backup": None},
            {"backup": []},
            {"backup": ["compression"]},
            {"backup": "gzip"},
            {"other": {"compression": "gzip"}},
        ],
    )
    def test_no_backup_compression_omits_flags(self, payload: str, config: dict):
        """Omit all flags when backup compression is absent/empty or non-mapping (PBM keeps its default)."""
        assert _FLAG_BUILDERS[payload](config) == []


class TestFlagsWiredIntoCommand:
    """Guarantee the flags are spliced into the ``pbm backup`` command."""

    @_PARAMETRIZE_PAYLOADS
    def test_helper_present_in_source(self, payload: str):
        """Require ``_compression_flags`` to stay defined in the payload source."""
        assert "def _compression_flags(" in _PAYLOADS[payload].read_text()

    @_PARAMETRIZE_PAYLOADS
    def test_flags_spliced_into_cmd(self, payload: str):
        """Require the ``pbm backup`` command to extend itself with ``_compression_flags(...)``.

        Anchors on the ``cmd = [...]`` assignment specifically — not on the mere
        presence of the helper name (which its own ``def`` line would satisfy) —
        so deleting the wiring while leaving the helper defined turns this RED.
        """
        source = _PAYLOADS[payload].read_text()
        cmd_lines = [
            line
            for line in source.splitlines()
            if line.lstrip().startswith("cmd =") and "'pbm', 'backup'" in line
        ]
        assert cmd_lines, "no `cmd = ['pbm', 'backup', ...]` assignment found"
        assert all("_compression_flags(" in line for line in cmd_lines), (
            "the pbm backup command does not splice in _compression_flags(...)"
        )


_BACKUP_TYPE = {"logical": "logical", "physical": "physical"}


def _exec_payload_capture_cmd(
    payload: str,
    nomad_meta_config: str | None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> list[str]:
    """Exec a payload end-to-end with a raw ``NOMAD_META_CONFIG`` and capture the command.

    Drive the real module-level ``pbm()`` with ``subprocess.Popen`` stubbed to a
    success-returning fake. A HOME-based credentials file is always provided so
    ``pbm_creds()`` succeeds regardless of the config's shape (the config need not
    carry ``credentials_path``); this isolates the test to the compression path.

    :param payload: Payload key (``logical`` / ``physical``).
    :param nomad_meta_config: Verbatim NOMAD_META_CONFIG value, or None to leave it absent.
    :param monkeypatch: pytest monkeypatch fixture.
    :param tmp_path: pytest tmp_path fixture for the credentials file.
    :return: The argument list passed to ``subprocess.Popen``.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".mongodb_uri").write_text("mongodb://localhost:27017/")

    if nomad_meta_config is None:
        monkeypatch.delenv("NOMAD_META_CONFIG", raising=False)
    else:
        monkeypatch.setenv("NOMAD_META_CONFIG", nomad_meta_config)

    captured: dict[str, list[str]] = {}

    class _FakePopen:
        def __init__(self, cmd: list[str], *args: object, **kwargs: object):
            captured["cmd"] = cmd

        def wait(self) -> None:
            return None

        def poll(self) -> int:
            return 0

    monkeypatch.setattr(subprocess, "Popen", _FakePopen)

    namespace: dict[str, object] = {}
    path = _PAYLOADS[payload]
    exec(compile(path.read_text(), str(path), "exec"), namespace)
    os.environ.pop(
        "PBM_MONGODB_URI", None
    )  # payload sets this directly, outside monkeypatch
    return captured["cmd"]


def _run_pbm_capture_cmd(
    payload: str,
    config: dict | None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> list[str]:
    """Exec a payload with ``config`` serialized to YAML and capture the command.

    :param payload: Payload key (``logical`` / ``physical``).
    :param config: Config dict serialized to ``NOMAD_META_CONFIG``, or None to leave it absent.
    :param monkeypatch: pytest monkeypatch fixture.
    :param tmp_path: pytest tmp_path fixture for the credentials file.
    :return: The argument list passed to ``subprocess.Popen``.
    """
    nomad_meta_config = None if config is None else yaml.safe_dump(config)
    return _exec_payload_capture_cmd(payload, nomad_meta_config, monkeypatch, tmp_path)


class TestPbmCommandEndToEnd:
    """Exec ``pbm()`` with a stubbed Popen and assert the full command it builds."""

    @_PARAMETRIZE_PAYLOADS
    def test_selected_compression_reaches_command(
        self, payload: str, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ):
        """Thread a configured compression from NOMAD_META_CONFIG onto pbm backup."""
        cmd = _run_pbm_capture_cmd(
            payload, {"backup": {"compression": "gzip"}}, monkeypatch, tmp_path
        )
        assert cmd == [
            "pbm",
            "backup",
            "--type",
            _BACKUP_TYPE[payload],
            "--wait",
            "--compression",
            "gzip",
        ]

    @_PARAMETRIZE_PAYLOADS
    def test_compression_level_reaches_command(
        self, payload: str, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ):
        """Carry both compression and level onto the command, in order."""
        cmd = _run_pbm_capture_cmd(
            payload,
            {"backup": {"compression": "gzip", "compressionLevel": 6}},
            monkeypatch,
            tmp_path,
        )
        assert cmd == [
            "pbm",
            "backup",
            "--type",
            _BACKUP_TYPE[payload],
            "--wait",
            "--compression",
            "gzip",
            "--compression-level",
            "6",
        ]

    @_PARAMETRIZE_PAYLOADS
    def test_no_backup_block_leaves_command_bare(
        self, payload: str, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ):
        """Emit no compression flags when the config has no backup block (PBM default)."""
        cmd = _run_pbm_capture_cmd(payload, {}, monkeypatch, tmp_path)
        assert cmd == ["pbm", "backup", "--type", _BACKUP_TYPE[payload], "--wait"]

    @_PARAMETRIZE_PAYLOADS
    def test_absent_config_leaves_command_bare(
        self, payload: str, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ):
        """Emit no compression flags when NOMAD_META_CONFIG is absent, and still run."""
        cmd = _run_pbm_capture_cmd(payload, None, monkeypatch, tmp_path)
        assert cmd == ["pbm", "backup", "--type", _BACKUP_TYPE[payload], "--wait"]


class TestPbmCommandResilientToBadConfig:
    """Ensure a malformed / non-mapping NOMAD_META_CONFIG never aborts the backup."""

    @_PARAMETRIZE_PAYLOADS
    @pytest.mark.parametrize(
        "bad_config",
        [
            "{unterminated: [",  # malformed YAML -> YAMLError
            "- a\n- b\n",  # valid YAML, but a list (non-mapping)
            "just a scalar",  # valid YAML, but a scalar (non-mapping)
            "",  # empty env value
        ],
        ids=["malformed", "list", "scalar", "empty"],
    )
    def test_bad_config_runs_backup_without_flags(
        self,
        payload: str,
        bad_config: str,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: pathlib.Path,
    ):
        """Degrade to {} on unusable config so the backup still runs."""
        cmd = _exec_payload_capture_cmd(payload, bad_config, monkeypatch, tmp_path)
        assert cmd == ["pbm", "backup", "--type", _BACKUP_TYPE[payload], "--wait"]


def _spec_config_yaml(**overrides: object) -> str:
    """Return the ``meta.config`` YAML produced by the real spec builder.

    Build a minimal S3 :class:`BackupCreate`, run it through
    :func:`build_backup_mongo_spec`, and return the serialized PBM config — the
    exact string dispatched as ``NOMAD_META_CONFIG`` to the derived backup tasks.

    :param overrides: Field overrides applied to the create form.
    :return: The serialized PBM config YAML string.
    """
    form = BackupCreate(
        task_name="mongo-backup",
        hostname="mongo-host",
        service_id=1,
        backup_type=BackupType.PBM_CONFIG,
        pitr_compression="gzip",
        storage_type="s3",
        storage_s3_region="eu-west-1",
        storage_s3_bucket="backups",
        storage_s3_prefix="mongo",
        storage_s3_endpoint_url="https://s3.example.com",
        **overrides,
    )
    task = build_backup_mongo_spec(form, BackupMongoResolved())
    return task.data["meta"]["config"]


class TestSpecConfigThreadsThroughPayload:
    """Bind the spec serializer and the payload reader on the same config keys.

    The spec writes ``backup.compression`` / ``backup.compressionLevel`` and the
    payload reads them back. Feeding the real spec output into the real payload
    guarantees a key rename on either side fails loudly here — the split unit tests
    would each stay green while the integration silently regressed to ``s2``.
    """

    @_PARAMETRIZE_PAYLOADS
    def test_real_spec_compression_reaches_command(
        self, payload: str, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ):
        """Carry form-selected compression onto ``pbm backup`` via the real config."""
        config_yaml = _spec_config_yaml(
            backup_compression="gzip", backup_compression_level=6
        )
        cmd = _exec_payload_capture_cmd(payload, config_yaml, monkeypatch, tmp_path)

        assert "--compression" in cmd
        assert cmd[cmd.index("--compression") + 1] == "gzip"
        assert "--compression-level" in cmd
        assert cmd[cmd.index("--compression-level") + 1] == "6"
