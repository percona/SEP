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

"""Tests that the inline ``--encrypt=AES256`` flag is gated by backup binary.

``mariadb-backup`` has no ``--encrypt`` option, so the inline flag must be
emitted only for ``xtrabackup``/``innobackupex``. The gating decision lives in
the module-level ``_should_inline_encrypt`` pure function; ``_run_backup_cmd``
and ``run`` are exercised for real too (lifted via AST, real methods, no
extraction) rather than asserting on the shape of a guarding ``if`` -- a
behavior-preserving rewrite of either method still passes these tests, and a
dead/misplaced guard would not.

``_run_backup_cmd``/``run`` are too large and side-effecting (real subprocess
dispatch, file moves, uploads) to run to completion in a test, so each test
below runs the *real*, unmodified method and trips a controlled exception
right at the point that would otherwise shell out or touch the filesystem
further -- everything up to that point, including the encrypt-flag wiring,
still executes for real.
"""

import ast
import time

import pytest

from tests.app.sep.apps.mysql_backups.conftest import (
    XTRABACKUP_PAYLOAD_PATH,
    xtrabackup_payload_tree,
)
from tests.app.sep.apps.mysql_backups.test_xtrabackup_aes256_encrypt import (
    _payload_instance,
)


def _load_function(name: str, namespace: dict[str, object]) -> object:
    """Extract and exec a module-level payload function from the payload source via AST.

    Locates ``def <name>`` and compiles it into ``namespace``, so a function
    that calls another already-loaded function in the same ``namespace``
    resolves it correctly (both share the compiled function's ``__globals__``).
    Raises loudly if the function has been renamed or removed, rather than
    silently passing.

    :param name: The module-level function name to extract.
    :param namespace: The exec namespace to compile into and read the result from.
    :return: The extracted, callable function.
    :raises RuntimeError: If no module-level function named ``name`` is found.
    """
    for node in xtrabackup_payload_tree().body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            module = ast.Module(body=[node], type_ignores=[])
            exec(compile(module, str(XTRABACKUP_PAYLOAD_PATH), "exec"), namespace)
            return namespace[name]
    raise RuntimeError(
        f"{name} not found in {XTRABACKUP_PAYLOAD_PATH}. Renamed or removed?"
    )


_should_inline_encrypt = _load_function("_should_inline_encrypt", {})


class TestShouldInlineEncrypt:
    """Assert the inline-flag gate is keyed on the binary and the resolved format."""

    @pytest.mark.parametrize(
        ("bin_cmd", "aes256", "expected"),
        [
            ("xtrabackup", True, True),
            ("innobackupex", True, True),
            ("mariadb-backup", True, False),
            ("xtrabackup", False, False),
            ("mariadb-backup", False, False),
        ],
    )
    def test_gate_per_binary_and_format(
        self, bin_cmd: str, *, aes256: bool, expected: bool
    ) -> None:
        """Assert each (bin_cmd, aes256) combination yields the expected gate result."""
        assert _should_inline_encrypt(bin_cmd, aes256) is expected


class _StoppedAtDispatchError(Exception):
    """Raised by the tripwire ``Popen`` fake to abort a real method mid-run."""


class TestInlineEncryptWiredIntoCommand:
    """Assert ``_run_backup_cmd`` actually feeds the gate into the command.

    Runs the real, unmodified method with just enough instance state to reach
    its ``subprocess.Popen`` dispatch, where a tripwire fake records the
    command and aborts -- so the real flag-building logic executes, but the
    method never shells out or touches the filesystem beyond that point.
    """

    def _run(
        self, tmp_path, *, bin_cmd: str, keyfile: str | None, aes256: bool = True
    ) -> list[str]:
        calls: list[list[str]] = []

        class _TripwireSubprocess:
            PIPE = -1
            STDOUT = -2

            @staticmethod
            def Popen(cmd, **_kwargs):  # noqa: N802
                calls.append(list(cmd) if isinstance(cmd, list) else [cmd])
                raise _StoppedAtDispatchError

        inst, _, _ = _payload_instance(
            ("_run_backup_cmd",),
            extra_namespace={
                "subprocess": _TripwireSubprocess,
                "time": time,
                "_replica_backup_flags": _load_function("_replica_backup_flags", {}),
                "_should_inline_encrypt": _should_inline_encrypt,
            },
        )
        inst._get_version = lambda: "8.0"
        inst._define_incremental_options = lambda: None
        inst.xtrabackup_bin_cmd = bin_cmd
        inst.defaults_file = None
        inst.xtrabackup_lock_ddl = False
        inst.xtrabackup_rsync = False
        inst.is_pxc = False
        inst.backup_dir = "/backups/host1"
        inst.xtrabackup_replica_info = False
        inst.xtrabackup_stop_replica = False
        inst.builtin_kill = False
        inst.incremental = False
        inst.prepare_backup = False
        inst.aes_keyfile = keyfile
        inst.enc_aes = aes256
        inst.xtrabackup_extra_args = None
        inst.host = "localhost"
        inst.cmd_shell = False
        inst.xb_log_file = str(tmp_path / "xb.log")

        with pytest.raises(_StoppedAtDispatchError):
            inst._run_backup_cmd()
        return calls[0]

    def test_encrypt_flags_reach_the_dispatched_command(self, tmp_path) -> None:
        """Assert the real command sent to ``Popen`` carries both AES-256 flags."""
        cmd = self._run(tmp_path, bin_cmd="xtrabackup", keyfile="/keys/aes.key")
        assert "--encrypt=AES256" in cmd
        assert "--encrypt-key-file=/keys/aes.key" in cmd

    def test_mariadb_backup_omits_encrypt_flags(self, tmp_path) -> None:
        """Assert ``mariadb-backup`` never reaches the dispatched command with them."""
        cmd = self._run(tmp_path, bin_cmd="mariadb-backup", keyfile="/keys/aes.key")
        assert "--encrypt=AES256" not in cmd

    def test_stale_key_file_omits_encrypt_flags(self, tmp_path) -> None:
        """Assert a key file the selected format excludes never reaches the command.

        A stored config can still carry ``XTRABACKUP_AES256_KEYFILE`` after the
        operator selected a GPG-only format; the resolved format, not the leftover
        field, must decide.
        """
        cmd = self._run(
            tmp_path, bin_cmd="xtrabackup", keyfile="/keys/aes.key", aes256=False
        )
        assert "--encrypt=AES256" not in cmd
        assert "--encrypt-key-file=/keys/aes.key" not in cmd


class TestAes256VerifyWiredIntoRun:
    """Assert ``run`` still encrypts stragglers then verifies the AES-256 dir.

    Runs the real, unmodified ``run`` with a fake, failing ``is_encrypted_dir``
    -- everything up to and including the encrypt-then-verify block executes
    for real, and the resulting ``BackupError`` is the real exception ``run``
    raises, not an assertion on ``run``'s AST shape.
    """

    def test_verification_failure_propagates_out_of_run(self, tmp_path) -> None:
        """Assert a failed AES-256 verification aborts ``run`` with ``BackupError``."""

        def fake_is_encrypted_dir(*_args: object, **kwargs: object) -> bool:
            assert kwargs.get("method") == "aes256"
            return False

        inst, backup_error, _ = _payload_instance(
            ("run",),
            extra_namespace={"is_encrypted_dir": fake_is_encrypted_dir, "time": time},
        )
        inst.only_if_running_replica = False
        inst.only_if_read_only = False
        inst.backup_dir = str(tmp_path / "xtrabackup_tmpdir")
        inst.check_disk_space = False
        inst.is_pxc = False
        inst._run_backup_cmd = lambda: None
        inst._is_track_changed_pages = lambda: False
        inst._purge_old_backups = lambda: None
        inst.host = "localhost"
        inst.incremental = True
        inst.last_backup_dir = str(tmp_path / "backups" / "host1")
        inst.encrypt_files_aes256 = lambda _dir_path: None

        with pytest.raises(backup_error) as exc_info:
            inst.run()
        assert inst.last_backup_dir in str(exc_info.value)
