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

"""Tests for the xtrabackup replica-flag helper (``--slave-info`` / ``--safe-slave-backup``).

The payload script cannot be exec'd in the test environment (it imports boto3
and other heavy runtime deps), so ``_replica_backup_flags`` is located in the
source via AST and exec'd on its own in a clean namespace -- giving us the
actual production function without pulling in the full dependency tree.
"""

import ast
import pathlib

import pytest

_PAYLOAD_PATH = (
    pathlib.Path(__file__).parents[5] / "app/sep/apps/mysql_backups/xtrabackup_payload"
)


def _load_replica_backup_flags():
    """Extract and exec ``_replica_backup_flags`` from the payload source via AST.

    Locates the module-level ``def _replica_backup_flags`` and compiles it in
    isolation so the payload's heavy imports never run. Raises loudly if the
    function has been renamed or removed, rather than silently passing.
    """
    source = _PAYLOAD_PATH.read_text()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_replica_backup_flags":
            module = ast.Module(body=[node], type_ignores=[])
            namespace: dict[str, object] = {}
            exec(compile(module, str(_PAYLOAD_PATH), "exec"), namespace)
            return namespace["_replica_backup_flags"]
    raise RuntimeError(
        f"_replica_backup_flags not found in {_PAYLOAD_PATH}. "
        "Has the function been renamed or removed?"
    )


_replica_backup_flags = _load_replica_backup_flags()


class TestReplicaBackupFlags:
    """Assert the replica-flag helper emits the right xtrabackup flags per option."""

    @pytest.mark.parametrize(
        ("replica_info", "stop_replica", "expected"),
        [
            (True, False, ["--slave-info"]),
            (False, True, ["--safe-slave-backup"]),
            (True, True, ["--slave-info", "--safe-slave-backup"]),
            (False, False, []),
        ],
    )
    def test_flags_for_option_combinations(
        self, replica_info, stop_replica, expected: list[str]
    ) -> None:
        """Assert each (replica_info, stop_replica) combination yields the expected flags.

        ``--slave-info`` must lead ``--safe-slave-backup`` so the option order
        (and thus the generated command) stays deterministic.
        """
        assert _replica_backup_flags(replica_info, stop_replica) == expected

    def test_slave_info_alone_is_unchanged(self) -> None:
        """Assert replica-info-only behavior is byte-identical to the pre-fix command."""
        assert _replica_backup_flags(replica_info=True, stop_replica=False) == [
            "--slave-info"
        ]

    def test_stop_replica_adds_safe_slave_backup(self) -> None:
        """Assert enabling stop-replica emits ``--safe-slave-backup``."""
        assert "--safe-slave-backup" in _replica_backup_flags(
            replica_info=True, stop_replica=True
        )


class TestReplicaPauseOwnedByXtrabackup:
    """Assert SEP no longer runs its own STOP/START REPLICA; xtrabackup owns the pause."""

    def _source(self) -> str:
        """Return the payload source text."""
        return _PAYLOAD_PATH.read_text()

    def test_stop_start_replica_method_removed(self) -> None:
        """Assert the manual ``_stop_start_replica`` method no longer exists."""
        tree = ast.parse(self._source())
        method_names = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        }
        assert "_stop_start_replica" not in method_names

    def test_no_calls_to_stop_start_replica(self) -> None:
        """Assert nothing in the payload still invokes ``_stop_start_replica``."""
        assert "_stop_start_replica" not in self._source()

    def test_safe_slave_backup_present_in_source(self) -> None:
        """Assert ``--safe-slave-backup`` is emitted somewhere in the payload.

        Fails loudly if the flag is dropped rather than letting the AST-exec
        helper silently return an empty list.
        """
        assert "--safe-slave-backup" in self._source()


def _run_backup_cmd_node() -> ast.FunctionDef:
    """Return the ``_run_backup_cmd`` FunctionDef parsed from the payload source.

    Raises loudly if the method is renamed or removed, so the wiring assertions
    below fail rather than silently vacuously passing.
    """
    tree = ast.parse(_PAYLOAD_PATH.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_run_backup_cmd":
            return node
    raise RuntimeError(
        f"_run_backup_cmd not found in {_PAYLOAD_PATH}. "
        "Has the method been renamed or removed?"
    )


class TestFlagsWiredIntoCommand:
    """Assert ``_run_backup_cmd`` actually feeds the helper output into the command.

    The behavioral tests above exercise ``_replica_backup_flags`` in isolation, so
    they stay green even if the call site is deleted. These structural assertions
    pin the integration at ``xtrabackup_payload`` (the ``xtrabackup_cmd.extend(
    _replica_backup_flags(self.xtrabackup_replica_info, self.xtrabackup_stop_replica))``
    line), so dropping or corrupting the wiring fails a test.
    """

    def _extend_calls(self) -> list[ast.Call]:
        """Return every ``xtrabackup_cmd.extend(...)`` call in ``_run_backup_cmd``."""
        return [
            node
            for node in ast.walk(_run_backup_cmd_node())
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "extend"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "xtrabackup_cmd"
        ]

    def _replica_flags_extend_call(self) -> ast.Call:
        """Return the ``xtrabackup_cmd.extend(_replica_backup_flags(...))`` call.

        Fails if no ``extend`` call wraps ``_replica_backup_flags`` -- i.e. the
        helper is computed but never spliced into the command.
        """
        for call in self._extend_calls():
            if (
                len(call.args) == 1
                and isinstance(call.args[0], ast.Call)
                and isinstance(call.args[0].func, ast.Name)
                and call.args[0].func.id == "_replica_backup_flags"
            ):
                return call
        raise AssertionError(
            "no `xtrabackup_cmd.extend(_replica_backup_flags(...))` call found in "
            "_run_backup_cmd; the replica flags are no longer wired into the command"
        )

    def test_extend_call_wraps_replica_backup_flags(self) -> None:
        """Assert the command list is extended with ``_replica_backup_flags(...)`` output."""
        assert self._replica_flags_extend_call() is not None

    def test_replica_flags_called_with_the_two_options_in_order(self) -> None:
        """Assert the helper is called with replica-info then stop-replica ``self`` attrs.

        Guards against passing constants, only one option, or the two swapped --
        any of which would silently change which flag gets emitted.
        """
        helper_call = self._replica_flags_extend_call().args[0]
        attrs = [
            arg.attr
            for arg in helper_call.args
            if isinstance(arg, ast.Attribute)
            and isinstance(arg.value, ast.Name)
            and arg.value.id == "self"
        ]
        assert attrs == ["xtrabackup_replica_info", "xtrabackup_stop_replica"]
