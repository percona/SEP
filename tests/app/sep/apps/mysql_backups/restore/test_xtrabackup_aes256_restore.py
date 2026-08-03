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

"""Tests for the AES-256 encrypt -> verify -> restore round trip.

The backup and restore payloads are independent Nomad scripts with no shared
import, so this exercises both sides for real: the backup payload's
``encrypt_files_aes256`` and the restore payload's ``is_encrypted``/
``decrypt_aes`` are lifted via AST (same technique as
``test_xtrabackup_aes256_encrypt.py``) and run with a real subprocess against
a stand-in ``xbcrypt`` executable, rather than a faked ``Popen`` -- proving
actual file *content* survives the boundary between the two payloads, not
just that the right argv was built.
"""

import ast
import os
import stat
import subprocess
import types

import pytest

from tests.app.sep.apps.mysql_backups.payload_harness import (
    load_function as _load_backup_function,
)
from tests.app.sep.apps.mysql_backups.payload_harness import (
    payload_instance as _payload_instance,
)
from tests.app.sep.apps.mysql_backups.restore.conftest import (
    RESTORE_PAYLOAD_PATH,
    restore_payload_tree,
)

_FAKE_XBCRYPT_SCRIPT = """\
#!/bin/sh
input=""
output=""
for arg in "$@"; do
    case "$arg" in
        --input=*) input="${arg#--input=}" ;;
        --output=*) output="${arg#--output=}" ;;
    esac
done
if grep -q CORRUPT_MARKER "$input" 2>/dev/null; then
    echo "corrupt xbcrypt input" >&2
    exit 1
fi
rev "$input" > "$output"
"""


def _write_fake_xbcrypt(tmp_path) -> str:
    """Write a reversing stand-in ``xbcrypt`` executable and return its path.

    Byte-reversal is its own inverse, so encrypting then decrypting through
    this double is a genuine round trip, not a no-op -- proving content
    actually survives the real subprocess boundary between the two payloads.
    A file containing ``CORRUPT_MARKER`` makes the double fail, standing in
    for a corrupted/garbage ``.xbcrypt`` input.
    """
    script = tmp_path / "fake_xbcrypt.sh"
    script.write_text(_FAKE_XBCRYPT_SCRIPT)
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(script)


def _restore_method_nodes(method_names: tuple[str, ...]) -> list[ast.FunctionDef]:
    """Return the named restore-payload ``FunctionDef`` nodes, raising if missing."""
    tree = restore_payload_tree()
    nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in method_names
    ]
    missing = set(method_names) - {node.name for node in nodes}
    if missing:
        raise RuntimeError(f"{sorted(missing)} not found in {RESTORE_PAYLOAD_PATH}.")
    return nodes


class _FakeRestoreProc:
    """Stand in for a ``Popen`` result with a fixed return code."""

    def __init__(self, returncode: int) -> None:
        self.returncode = returncode

    def communicate(self):
        """Return ``(stdout, stderr)`` -- unused by ``decrypt_aes``."""
        return b"", b""


def _restore_instance(
    method_names: tuple[str, ...],
    *,
    real_subprocess: bool,
    returncode: int = 0,
    extra_namespace: dict[str, object] | None = None,
):
    """Build a restore-payload instance carrying the named methods.

    Mirrors ``test_xtrabackup_aes256_encrypt._payload_instance`` for the
    restore payload: methods are lifted verbatim via AST into a synthetic
    class over a controlled namespace. ``real_subprocess=True`` keeps the
    real ``subprocess`` module so a stand-in ``xbcrypt`` executable actually
    runs; ``real_subprocess=False`` fakes ``Popen`` and records the shell
    command string it was given (``calls``), for cheap command-shape
    assertions that don't need a real process.

    :param method_names: The restore payload method names to lift.
    :param real_subprocess: Whether to keep the real ``subprocess`` module.
    :param returncode: Return code the faked ``Popen`` reports (ignored when
        ``real_subprocess`` is True).
    :param extra_namespace: Extra globals (e.g. ``XBCRYPT_BIN``) merged into
        the exec namespace before the class is compiled.
    :return: A ``(instance, BackupError, calls)`` tuple; ``calls`` is the
        list of shell command strings the faked ``Popen`` was given (always
        ``[]`` when ``real_subprocess`` is True).
    """
    calls: list[str] = []

    class _FakeSubprocess:
        PIPE = -1

        @staticmethod
        def Popen(cmd, **_kwargs):  # noqa: N802
            calls.append(cmd)
            return _FakeRestoreProc(returncode)

    namespace: dict[str, object] = {
        "os": os,
        "subprocess": subprocess if real_subprocess else _FakeSubprocess,
    }
    exec("class BackupError(Exception):\n    pass", namespace)
    namespace["XBCRYPT_BIN"] = "/usr/bin/xbcrypt"
    namespace.update(extra_namespace or {})

    cls = ast.ClassDef(
        name="_RestorePayload",
        bases=[],
        keywords=[],
        body=_restore_method_nodes(method_names),
        decorator_list=[],
    )
    module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    exec(compile(module, str(RESTORE_PAYLOAD_PATH), "exec"), namespace)

    inst = namespace["_RestorePayload"]()
    inst.logger = types.SimpleNamespace(
        info=lambda *_a, **_k: None,
        debug=lambda *_a, **_k: None,
        error=lambda *_a, **_k: None,
    )
    inst.xtrabackup_aes256_keyfile = "/keys/aes.key"
    inst.xb_parallel = 2
    return inst, namespace["BackupError"], calls


class TestAes256RoundTrip:
    """Assert an AES-256 backup survives a real encrypt -> verify -> restore pass."""

    def test_mariadb_backup_encrypt_verify_restore_round_trip(self, tmp_path) -> None:
        """Assert file content -- not just command shape -- survives the round trip."""
        fake_bin = _write_fake_xbcrypt(tmp_path)
        backup_dir = tmp_path / "backup"
        backup_dir.mkdir()
        original = "top-secret-backup-content\n"
        (backup_dir / "ibdata1").write_text(original)

        backup_inst, _, _ = _payload_instance(
            ("encrypt_files_aes256", "_run_encrypt_file_aes256", "_run_xbcrypt"),
            extra_namespace={"XBCRYPT_BIN": fake_bin},
            real_subprocess=True,
        )
        backup_inst.encrypt_files_aes256(str(backup_dir))

        is_encrypted_dir = _load_backup_function("is_encrypted_dir")
        assert is_encrypted_dir(str(backup_dir), method="aes256") is True

        restore_inst, _, _ = _restore_instance(
            ("is_encrypted", "decrypt_aes"),
            real_subprocess=True,
            extra_namespace={"XBCRYPT_BIN": fake_bin},
        )
        assert restore_inst.is_encrypted(str(backup_dir)) == "aes"

        restore_inst.decrypt_aes(str(backup_dir))

        restored = backup_dir / "ibdata1"
        assert restored.exists()
        assert not (backup_dir / "ibdata1.xbcrypt").exists()
        assert restored.read_text() == original

    def test_corrupt_xbcrypt_input_raises_backuperror(self, tmp_path) -> None:
        """Assert a corrupted ``.xbcrypt`` file fails restore, not silently drops data."""
        fake_bin = _write_fake_xbcrypt(tmp_path)
        backup_dir = tmp_path / "backup"
        backup_dir.mkdir()
        (backup_dir / "ibdata1.xbcrypt").write_text("CORRUPT_MARKER\n")

        restore_inst, backup_error, _ = _restore_instance(
            ("decrypt_aes",),
            real_subprocess=True,
            extra_namespace={"XBCRYPT_BIN": fake_bin},
        )
        with pytest.raises(backup_error):
            restore_inst.decrypt_aes(str(backup_dir))


class TestDecryptAesParallelism:
    """Assert restore's xbcrypt parallelism is bounded, not the legacy ``-P 0``."""

    def _decrypt_command(self, xb_parallel: int) -> str:
        inst, _, calls = _restore_instance(("decrypt_aes",), real_subprocess=False)
        inst.xb_parallel = xb_parallel
        inst.decrypt_aes("/backups/host1")
        assert len(calls) == 1
        return calls[0]

    def test_legacy_missing_xb_parallel_is_bounded_not_unlimited(self) -> None:
        """Assert ``xb_parallel=0`` (legacy task default) never becomes ``xargs -P 0``.

        GNU ``xargs -P 0`` means "run as many processes as possible" -- the
        exact CPU-starvation risk SEP-565 calls out. Legacy task data with no
        ``XB_PARALLEL`` key resolves ``xb_parallel`` to ``0``; falling back to
        ``4`` (the same default new tasks get) keeps it bounded.
        """
        cmd = self._decrypt_command(xb_parallel=0)
        assert "-P 0 " not in cmd
        assert "-P 4 " in cmd

    def test_configured_value_passes_through(self) -> None:
        """Assert an explicit operator-configured value is used as-is."""
        cmd = self._decrypt_command(xb_parallel=2)
        assert "-P 2 " in cmd
