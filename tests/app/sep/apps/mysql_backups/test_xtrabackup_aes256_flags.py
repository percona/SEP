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
the module-level ``_should_inline_encrypt`` pure function, extracted from
``_run_backup_cmd`` via AST and exec'd in isolation (the payload cannot be
imported directly -- see ``test_xtrabackup_replica_flags.py``). Exercising the
real function, rather than asserting on the shape of the guarding ``if``,
means a behavior-preserving rewrite of the guard still passes these tests.
"""

import ast

import pytest

from tests.app.sep.apps.mysql_backups.conftest import (
    XTRABACKUP_PAYLOAD_PATH,
    xtrabackup_payload_tree,
)


def _load_should_inline_encrypt():
    """Extract and exec ``_should_inline_encrypt`` from the payload source via AST.

    Locates the module-level ``def _should_inline_encrypt`` and compiles it in
    isolation so the payload's heavy imports never run. Raises loudly if the
    function has been renamed or removed, rather than silently passing.
    """
    for node in xtrabackup_payload_tree().body:
        if isinstance(node, ast.FunctionDef) and node.name == "_should_inline_encrypt":
            module = ast.Module(body=[node], type_ignores=[])
            namespace: dict[str, object] = {}
            exec(compile(module, str(XTRABACKUP_PAYLOAD_PATH), "exec"), namespace)
            return namespace["_should_inline_encrypt"]
    raise RuntimeError(
        f"_should_inline_encrypt not found in {XTRABACKUP_PAYLOAD_PATH}. "
        "Has the function been renamed or removed?"
    )


_should_inline_encrypt = _load_should_inline_encrypt()


class TestShouldInlineEncrypt:
    """Assert the inline-flag gate is keyed on binary and keyfile presence."""

    @pytest.mark.parametrize(
        ("bin_cmd", "keyfile", "expected"),
        [
            ("xtrabackup", "/keys/aes.key", True),
            ("innobackupex", "/keys/aes.key", True),
            ("mariadb-backup", "/keys/aes.key", False),
            ("xtrabackup", None, False),
            ("xtrabackup", "", False),
        ],
    )
    def test_gate_per_binary_and_keyfile(
        self, bin_cmd: str, keyfile: str | None, expected: bool | None
    ) -> None:
        """Assert each (bin_cmd, keyfile) combination yields the expected gate result."""
        assert bool(_should_inline_encrypt(bin_cmd, keyfile)) is expected

    def test_mariadb_backup_excluded_even_with_keyfile(self) -> None:
        """Assert mariadb-backup never gates the inline flag on, keyfile or not."""
        assert not _should_inline_encrypt("mariadb-backup", "/keys/aes.key")

    def test_xtrabackup_with_keyfile_gates_flag_on(self) -> None:
        """Assert xtrabackup with a keyfile still emits the inline flag (no regression)."""
        assert _should_inline_encrypt("xtrabackup", "/keys/aes.key")


def _run_backup_cmd_node() -> ast.FunctionDef:
    """Return the ``_run_backup_cmd`` FunctionDef, raising if renamed/removed."""
    for node in ast.walk(xtrabackup_payload_tree()):
        if isinstance(node, ast.FunctionDef) and node.name == "_run_backup_cmd":
            return node
    raise RuntimeError(f"_run_backup_cmd not found in {XTRABACKUP_PAYLOAD_PATH}.")


class TestInlineEncryptWiredIntoCommand:
    """Assert ``_run_backup_cmd`` actually feeds the gate into the command.

    The behavioral tests above exercise ``_should_inline_encrypt`` in isolation,
    so they stay green even if the call site is deleted. These structural
    assertions pin the integration, so dropping or corrupting the wiring fails
    a test.
    """

    def _gate_if(self) -> ast.If:
        """Return the single ``if _should_inline_encrypt(...):`` node."""
        ifs = [
            node
            for node in ast.walk(_run_backup_cmd_node())
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Call)
            and isinstance(node.test.func, ast.Name)
            and node.test.func.id == "_should_inline_encrypt"
        ]
        assert len(ifs) == 1, (
            "expected exactly one `if _should_inline_encrypt(...):` in "
            f"_run_backup_cmd, found {len(ifs)}"
        )
        return ifs[0]

    def test_gate_called_with_bin_cmd_then_keyfile(self) -> None:
        """Assert the call passes the binary then the keyfile, in that order.

        Guards against passing constants, only one option, or the two
        swapped -- any of which would silently change the gate's behavior.
        """
        attrs = [
            arg.attr
            for arg in self._gate_if().test.args
            if isinstance(arg, ast.Attribute)
            and isinstance(arg.value, ast.Name)
            and arg.value.id == "self"
        ]
        assert attrs == ["xtrabackup_bin_cmd", "xtrabackup_aes256_keyfile"]

    def test_gate_body_appends_both_flags_once(self) -> None:
        """Assert the guarded body appends both AES-256 flags exactly once."""
        appended = [
            c.value
            for stmt in self._gate_if().body
            for c in ast.walk(stmt)
            if isinstance(c, ast.Constant)
            and isinstance(c.value, str)
            and c.value.startswith("--encrypt")
        ]
        assert appended == ["--encrypt=AES256", "--encrypt-key-file=%s"]
