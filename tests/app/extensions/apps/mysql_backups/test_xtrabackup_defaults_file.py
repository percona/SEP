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

"""Cover how the xtrabackup payload resolves and validates its defaults files.

The default path is built at import time from the environment, so the constant is
re-exec'd per test through the harness rather than read once: that is the only way
to render it with ``HOME`` absent, which is the state an executor can hand the
payload.

PyMySQL ignores an option file it cannot read and connects with no credentials, so
an unusable path costs a failed backup reported as an authentication error naming no
file. The guard tests below pin the opposite: the run stops on the file, naming it.
"""

import ast
import os
import pathlib

import pytest

from tests.app.extensions.apps.mysql_backups.conftest import (
    XTRABACKUP_PAYLOAD_PATH,
    xtrabackup_payload_tree,
)
from tests.app.extensions.apps.mysql_backups.payload_harness import (
    load_constant,
    seeded_instance,
    STUB_HOME,
)

_CHECK_CONFIG = ("_check_config",)


class TestDefaultMycnfResolution:
    """Assert the default option-file path resolves to a usable path in any environment."""

    def test_home_unset_resolves_the_account_home(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Assert an absent ``HOME`` falls back to the running account's home.

        ``os.environ.get`` returns ``None`` rather than raising, and formatting that
        renders the word, producing the relative path ``None/.my.cnf``.
        """
        monkeypatch.delenv("HOME", raising=False)
        assert load_constant("DEFAULT_MYCNF") == f"{STUB_HOME}/.my.cnf"

    def test_home_set_is_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Assert a set ``HOME`` still wins, so hosts that have one resolve as before."""
        monkeypatch.setenv("HOME", "/var/lib/percona-backup")
        assert load_constant("DEFAULT_MYCNF") == "/var/lib/percona-backup/.my.cnf"

    def test_empty_home_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Assert an empty ``HOME`` falls back instead of resolving to ``/.my.cnf``."""
        monkeypatch.setenv("HOME", "")
        assert load_constant("DEFAULT_MYCNF") == f"{STUB_HOME}/.my.cnf"


class TestDefaultsFileGuard:
    """Assert an unusable defaults file fails the run on the file, before connecting."""

    def test_readable_file_passes(self, readable_cnf: pathlib.Path) -> None:
        """Assert a readable option file is accepted."""
        inst, _ = seeded_instance(
            _CHECK_CONFIG,
            server_data={"DEFAULTS_FILE": str(readable_cnf)},
            defaults_cnf_file=str(readable_cnf),
        )
        assert inst._check_config() is None

    def test_explicit_unreadable_file_names_the_field(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Assert an explicit missing path names both the path and the field that set it."""
        missing = str(tmp_path / "absent.cnf")
        inst, backup_error = seeded_instance(
            _CHECK_CONFIG,
            server_data={"DEFAULTS_FILE": missing},
            defaults_cnf_file=missing,
        )
        with pytest.raises(backup_error) as excinfo:
            inst._check_config()
        assert str(excinfo.value) == (
            f"cannot read defaults file {missing} from DEFAULTS_FILE"
        )

    def test_defaulted_missing_file_is_marked_as_the_default(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Assert a path nobody set says so, rather than blaming an untouched field.

        The operator's fix differs: one is a wrong value, the other a value they
        never chose.
        """
        missing = str(tmp_path / "absent.cnf")
        inst, backup_error = seeded_instance(_CHECK_CONFIG, defaults_cnf_file=missing)
        with pytest.raises(backup_error) as excinfo:
            inst._check_config()
        assert str(excinfo.value) == (
            f"cannot read defaults file {missing} from DEFAULTS_FILE default"
        )

    def test_failure_does_not_read_as_an_authentication_error(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Assert the message points at the file rather than at the credentials."""
        inst, backup_error = seeded_instance(
            _CHECK_CONFIG, defaults_cnf_file=str(tmp_path / "absent.cnf")
        )
        with pytest.raises(backup_error) as excinfo:
            inst._check_config()
        message = str(excinfo.value).lower()
        assert "defaults file" in message
        assert "auth" not in message
        assert "denied" not in message

    def test_directory_is_rejected(self, tmp_path: pathlib.Path) -> None:
        """Assert a directory fails as a file problem rather than later as a bad login."""
        inst, backup_error = seeded_instance(
            _CHECK_CONFIG, defaults_cnf_file=str(tmp_path)
        )
        with pytest.raises(backup_error):
            inst._check_config()

    def test_blank_path_is_rejected(self) -> None:
        """Assert a hand-authored empty ``DEFAULTS_FILE`` fails here, not on login.

        The message is pinned because a blank leaves nothing to name beside the
        field: the key is the only thing that points an operator at the config they
        wrote, and the field carries a default, so a blank is a choice of nothing
        rather than an absent key.
        """
        inst, backup_error = seeded_instance(
            _CHECK_CONFIG, server_data={"DEFAULTS_FILE": ""}, defaults_cnf_file=""
        )
        with pytest.raises(backup_error) as excinfo:
            inst._check_config()
        assert str(excinfo.value) == "cannot read defaults file  from DEFAULTS_FILE"

    def test_dangling_symlink_is_rejected(self, tmp_path: pathlib.Path) -> None:
        """Assert a link whose target is gone fails as an unreadable file."""
        link = tmp_path / "my.cnf"
        link.symlink_to(tmp_path / "absent.cnf")
        inst, backup_error = seeded_instance(_CHECK_CONFIG, defaults_cnf_file=str(link))
        with pytest.raises(backup_error):
            inst._check_config()

    @pytest.mark.skipif(
        os.geteuid() == 0, reason="root bypasses the permission bits being asserted"
    )
    def test_unreadable_permissions_are_rejected(
        self, readable_cnf: pathlib.Path
    ) -> None:
        """Assert a file the account cannot read fails, not only a missing one."""
        readable_cnf.chmod(0o000)
        inst, backup_error = seeded_instance(
            _CHECK_CONFIG, defaults_cnf_file=str(readable_cnf)
        )
        with pytest.raises(backup_error):
            inst._check_config()


class TestBinaryDefaultsFileGuard:
    """Assert the binary's own option file is guarded too, and named as itself.

    ``--defaults-file`` is a second field with its own key, so a failure has to name
    which of the two an operator should look at.
    """

    def test_unreadable_binary_file_names_its_own_field(
        self, tmp_path: pathlib.Path, readable_cnf: pathlib.Path
    ) -> None:
        """Assert the binary's unreadable option file fails naming its own key."""
        missing = str(tmp_path / "absent.cnf")
        inst, backup_error = seeded_instance(
            _CHECK_CONFIG,
            server_data={"XTRABACKUP_DEFAULTS_FILE": missing},
            defaults_cnf_file=str(readable_cnf),
            defaults_file=missing,
        )
        with pytest.raises(backup_error) as excinfo:
            inst._check_config()
        assert str(excinfo.value) == (
            f"cannot read defaults file {missing} from XTRABACKUP_DEFAULTS_FILE"
        )

    def test_unset_binary_file_is_not_checked(self, readable_cnf: pathlib.Path) -> None:
        """Assert an unset key leaves the binary's own option-file discovery alone.

        The field has no default, so there is no path to check and nothing to
        second-guess.
        """
        inst, _ = seeded_instance(
            _CHECK_CONFIG, defaults_cnf_file=str(readable_cnf), defaults_file=None
        )
        assert inst._check_config() is None

    def test_client_file_is_reported_before_the_binary_file(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Assert the silent failure is reported first when both files are unusable.

        Only the client side fails without naming a file, so it is the one an
        operator cannot diagnose from the backup log.
        """
        inst, backup_error = seeded_instance(
            _CHECK_CONFIG,
            defaults_cnf_file=str(tmp_path / "client.cnf"),
            defaults_file=str(tmp_path / "binary.cnf"),
        )
        with pytest.raises(backup_error) as excinfo:
            inst._check_config()
        assert "client.cnf" in str(excinfo.value)


class TestBlankBinaryFileReadsAsUnset:
    """Assert a blank ``XTRABACKUP_DEFAULTS_FILE`` is normalised where it is read.

    ``_run_backup_cmd`` omits ``--defaults-file`` for a blank value, so a guard that
    rejected one would fail a config the backup would otherwise run. The
    normalisation sits at the read site rather than in the guard, whose loop body is
    shared with ``DEFAULTS_FILE``, where a blank stays rejected on purpose.

    Asserted against the source: the initializer calls ``super().__init__``, which
    the synthetic-instance harness cannot drive.
    """

    def test_the_read_site_normalises_a_blank_to_none(self) -> None:
        """Assert the binary's option file is read with a fallback to ``None``."""
        assignments = [
            node
            for owner in ast.walk(xtrabackup_payload_tree())
            if isinstance(owner, ast.ClassDef) and owner.name == "Xtrabackup"
            for node in ast.walk(owner)
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Attribute)
            and node.targets[0].attr == "defaults_file"
        ]
        assert len(assignments) == 1, "Xtrabackup no longer reads its own option file"
        value = assignments[0].value
        assert isinstance(value, ast.BoolOp), (
            "XTRABACKUP_DEFAULTS_FILE is read without a fallback, so a blank reaches "
            "the guard as a path it cannot name and the command builder skips"
        )
        assert isinstance(value.op, ast.Or)
        fallback = value.values[-1]
        assert isinstance(fallback, ast.Constant)
        assert fallback.value is None


class TestCompressionCheckedInTheSameGuard:
    """Assert the pairing check shares the guard's call site, so neither can be skipped.

    Both answer one question — is this config runnable on this host — and both
    used to be reachable only from places that lost the message.
    """

    def test_unsupported_pairing_fails_the_config_check(
        self, readable_cnf: pathlib.Path
    ) -> None:
        """Assert a pairing the binary cannot run fails before the host is touched."""
        inst, backup_error = seeded_instance(
            _CHECK_CONFIG,
            defaults_cnf_file=str(readable_cnf),
            xtrabackup_bin_cmd="innobackupex",
            compression_algorithm="zstd",
        )
        with pytest.raises(backup_error) as excinfo:
            inst._check_config()
        assert "innobackupex" in str(excinfo.value)


class TestSiblingPayloadsResolveTheSameWay:
    """Assert every payload with a default option file derives it from the account.

    The generated variants come from the canonical payload, but the restore payloads
    are maintained by hand — so a restore could read a different option file than
    the backup that wrote it, which is the divergence the shared binary default
    already had to fix once.
    """

    PAYLOADS = sorted(
        path
        for path in XTRABACKUP_PAYLOAD_PATH.parent.glob("**/*payload")
        if "DEFAULT_MYCNF = " in path.read_text()
    )

    def test_the_payload_set_covers_both_sides(self) -> None:
        """Assert the filter still collects the backup and restore payloads.

        Renaming the constant would empty the parametrize table below and leave
        every payload unchecked with the suite still green.
        """
        assert XTRABACKUP_PAYLOAD_PATH in self.PAYLOADS
        assert XTRABACKUP_PAYLOAD_PATH.parent / "restore" / "xtrabackup_payload" in (
            self.PAYLOADS
        )

    @pytest.mark.parametrize(
        "payload",
        PAYLOADS,
        ids=lambda path: str(path.relative_to(XTRABACKUP_PAYLOAD_PATH.parent)),
    )
    def test_default_never_rests_on_home_alone(self, payload: pathlib.Path) -> None:
        """Assert the default path falls back to the account's own home directory.

        Where ``HOME`` is read at all, the operands are asserted in order as well as
        present: an inversion that reads the account home first and falls back to
        ``HOME`` carries both names, so a token check alone passes for it while every
        host that sets ``HOME`` stops resolving the path it resolves today. The
        payloads that never read ``HOME`` cannot invert, and are asserted only for
        the account home they always use.
        """
        source = payload.read_text()
        assignment = next(
            node
            for node in ast.parse(source).body
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "DEFAULT_MYCNF"
        )
        segment = ast.get_source_segment(source, assignment)
        assert segment, f"{payload} carries no source for its DEFAULT_MYCNF assignment"
        assert "CURRENT_USER_HOME_DIR" in segment
        if "environ" in segment:
            assert segment.index("environ") < segment.index("CURRENT_USER_HOME_DIR"), (
                f"{payload} reads the account home before HOME, so a host that sets "
                "HOME no longer resolves the path it resolves today"
            )


class TestGuardWiredIntoRun:
    """Assert the guard runs where its failure is reported, and before any connection.

    The behavioral tests above stay green if the call site disappears, and the
    payload builds each server object outside the loop's ``try``, so a guard raised
    from ``__init__`` would surface as an unhandled traceback with no message,
    no notification and no collector status.
    """

    @staticmethod
    def _run_body() -> list[ast.stmt]:
        """Return the statements of ``Xtrabackup.run``, docstring included."""
        for node in ast.walk(xtrabackup_payload_tree()):
            if isinstance(node, ast.ClassDef) and node.name == "Xtrabackup":
                for child in node.body:
                    if isinstance(child, ast.FunctionDef) and child.name == "run":
                        return child.body
        raise AssertionError("Xtrabackup.run no longer exists")

    def test_the_guard_is_the_first_method_run_calls(self) -> None:
        """Assert nothing that can reach the host runs before the guard."""
        called = [
            node.func.attr
            for statement in self._run_body()
            for node in ast.walk(statement)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
        ]
        assert called[:1] == ["_check_config"]

    def test_the_guard_is_not_raised_from_construction(self) -> None:
        """Assert no ``__init__`` calls the guard, where its message would be lost.

        The initializers are collected first and asserted non-empty: a walk that
        matched nothing would satisfy the claim below without checking anything.
        """
        initializers = [
            (owner.name, node)
            for owner in ast.walk(xtrabackup_payload_tree())
            if isinstance(owner, ast.ClassDef)
            for node in owner.body
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        ]
        assert initializers, "no payload class defines an initializer"
        offenders = [
            owner
            for owner, node in initializers
            if any(
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "_check_config"
                for call in ast.walk(node)
            )
        ]
        assert not offenders
