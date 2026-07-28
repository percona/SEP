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
emitted only for ``xtrabackup``/``innobackupex``. ``_run_backup_cmd`` is far too
coupled to run in isolation, so these are structural (AST) assertions on the
single ``if`` in ``_run_backup_cmd`` that appends ``--encrypt=AES256``: they pin
that the append is guarded by both the AES-256 keyfile and a
``!= 'mariadb-backup'`` check, so the gating cannot be silently dropped or the
flag emitted unconditionally (which would re-break the mariadb-backup path).
"""

import ast
import pathlib

_PAYLOAD_PATH = (
    pathlib.Path(__file__).parents[5] / "app/sep/apps/mysql_backups/xtrabackup_payload"
)


def _run_backup_cmd_node() -> ast.FunctionDef:
    """Return the ``_run_backup_cmd`` FunctionDef, raising if renamed/removed."""
    tree = ast.parse(_PAYLOAD_PATH.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_run_backup_cmd":
            return node
    raise RuntimeError(f"_run_backup_cmd not found in {_PAYLOAD_PATH}.")


def _inline_encrypt_ifs() -> list[ast.If]:
    """Return every ``if`` in ``_run_backup_cmd`` that appends ``--encrypt=AES256``."""
    return [
        node
        for node in ast.walk(_run_backup_cmd_node())
        if isinstance(node, ast.If)
        and any(
            isinstance(c, ast.Constant) and c.value == "--encrypt=AES256"
            for stmt in node.body
            for c in ast.walk(stmt)
        )
    ]


class TestInlineEncryptFlagGatedByBinary:
    """Assert the inline AES-256 append exists exactly once and is properly gated."""

    def _gate(self) -> ast.If:
        """Return the single guarding ``if`` node, failing if absent or duplicated."""
        ifs = _inline_encrypt_ifs()
        assert len(ifs) == 1, (
            "expected exactly one `--encrypt=AES256` append site in _run_backup_cmd, "
            f"found {len(ifs)}"
        )
        return ifs[0]

    def _test_constants(self) -> list[str]:
        """Return the string constants referenced in the gate's condition."""
        return [
            c.value for c in ast.walk(self._gate().test) if isinstance(c, ast.Constant)
        ]

    def _test_attrs(self) -> list[str]:
        """Return the ``self.*`` attribute names referenced in the gate's condition."""
        return [
            a.attr
            for a in ast.walk(self._gate().test)
            if isinstance(a, ast.Attribute)
            and isinstance(a.value, ast.Name)
            and a.value.id == "self"
        ]

    def _mariadb_compare_ops(self) -> list[type]:
        """Return the operator node types of the comparison against ``'mariadb-backup'``."""
        for cmp in ast.walk(self._gate().test):
            if isinstance(cmp, ast.Compare) and any(
                isinstance(c, ast.Constant) and c.value == "mariadb-backup"
                for c in cmp.comparators
            ):
                return [type(op) for op in cmp.ops]
        return []

    def test_flag_still_emitted_for_xtrabackup(self) -> None:
        """Assert the inline flag path survives (xtrabackup must not regress)."""
        assert len(_inline_encrypt_ifs()) == 1

    def test_gate_excludes_mariadb_backup(self) -> None:
        """Assert the append is guarded by a ``!= 'mariadb-backup'`` comparison."""
        assert "mariadb-backup" in self._test_constants()

    def test_gate_uses_not_equal(self) -> None:
        """Assert the binary check is ``!=`` — flipping it to ``==`` must fail here."""
        assert self._mariadb_compare_ops() == [ast.NotEq]

    def test_gate_requires_keyfile(self) -> None:
        """Assert the append is guarded by the AES-256 keyfile being set."""
        assert "xtrabackup_aes256_keyfile" in self._test_attrs()

    def test_gate_reads_selected_binary(self) -> None:
        """Assert the gate keys off the selected backup binary."""
        assert "xtrabackup_bin_cmd" in self._test_attrs()
