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

"""Tests for the guards that decide whether a base backup can seed an incremental.

The payload script cannot be imported (it pulls boto3 and other heavy runtime
deps), so the guards are located in the source via AST and exec'd in an isolated
namespace. ``_is_compressed_backup`` keeps no reference to ``self``, so it is
lifted as a plain function; the instance methods are lifted onto the synthetic
class ``payload_instance`` builds. Real files under ``tmp_path`` back the ``os``
and ``rglob`` calls, so an encrypted base is represented the way a real one is:
renamed data files beside plaintext metadata.
"""

import ast
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.app.sep.apps.mysql_backups.conftest import (
    XTRABACKUP_PAYLOAD_PATH,
    xtrabackup_payload_tree,
)
from tests.app.sep.apps.mysql_backups.payload_harness import (
    base_namespace as _base_namespace,
)
from tests.app.sep.apps.mysql_backups.payload_harness import (
    const_nodes as _const_nodes,
)
from tests.app.sep.apps.mysql_backups.payload_harness import (
    payload_instance as _payload_instance,
)

CHECKPOINTS = "xtrabackup_checkpoints"
BASE_LSN = 4242
UNPREPARED = f"backup_type = full-backuped\nto_lsn = {BASE_LSN}\n"
PREPARED = f"backup_type = full-prepared\nto_lsn = {BASE_LSN}\n"
ENCRYPTED_SUFFIXES = (".xbcrypt", ".gpg")


def _lift_plain(name: str) -> Callable[..., Any]:
    """Exec a payload method that takes no ``self`` as a module-level function.

    ``payload_instance`` copies the ``FunctionDef`` node without its
    ``@staticmethod`` decorator, so an instance call would bind the instance to
    the method's first parameter. Lifting it flat keeps the real signature.

    :param name: Method name to lift out of the payload source.
    :return: The lifted callable.
    """
    tree = xtrabackup_payload_tree()
    nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if not nodes:
        raise RuntimeError(f"{name} not found in {XTRABACKUP_PAYLOAD_PATH}.")

    namespace = _base_namespace()
    exec(
        compile(
            ast.Module(body=_const_nodes(tree) + nodes, type_ignores=[]),
            str(XTRABACKUP_PAYLOAD_PATH),
            "exec",
        ),
        namespace,
    )
    return namespace[name]


class _Recorder:
    """Collect the messages a payload method logs, in order."""

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.infos: list[str] = []
        self.errors: list[str] = []

    def warn(self, msg: str, *args: object) -> None:
        """Record a warning."""
        self.warnings.append(msg % args if args else msg)

    warning = warn

    def info(self, msg: str, *args: object) -> None:
        """Record an informational message."""
        self.infos.append(msg % args if args else msg)

    def debug(self, msg: str, *args: object) -> None:
        """Discard a debug message."""

    def error(self, msg: str, *args: object) -> None:
        """Record an error."""
        self.errors.append(msg % args if args else msg)


def _lift_guards(
    method_names: tuple[str, ...],
) -> tuple[Any, _Recorder, list[list[str]]]:
    """Build a payload instance carrying the named methods.

    :param method_names: Payload methods to lift onto the synthetic class.
    :return: The instance, the logger recording its messages, and the list of
        argv lists the guards handed to ``subprocess``, which stays empty for as
        long as encryption detection needs no external binary.
    """
    instance, _, calls = _payload_instance(method_names)
    recorder = _Recorder()
    instance.logger = recorder
    return instance, recorder, calls


def _guard(
    *, method: str | None = "fast_restore"
) -> tuple[Any, _Recorder, list[list[str]]]:
    """Build a payload instance carrying only the base-backup guards.

    :param method: Value for ``incremental_method``.
    :return: The instance, its logger, and the recorded subprocess calls.
    """
    instance, recorder, calls = _lift_guards(
        ("_is_good_base_backup", "_is_encrypted_base")
    )
    instance.incremental_method = method
    return instance, recorder, calls


def _write_base(
    path: Path, contents: str = UNPREPARED, *, data: str = "ibdata1"
) -> str:
    """Lay out a base backup directory on disk.

    :param path: Directory the backup is written into.
    :param contents: Body of the plaintext ``xtrabackup_checkpoints`` file.
    :param data: Name of the single InnoDB data file.
    :return: The directory as a string, ready to pass to a guard.
    """
    (path / CHECKPOINTS).write_text(contents)
    (path / "xtrabackup_info").write_text("meta")
    if data:
        (path / data).write_text("x")
    return str(path)


def _write_nested(path: Path, name: str) -> None:
    """Add a table file inside a schema subdirectory of a base backup.

    :param path: Base backup directory.
    :param name: File name to create under the schema directory.
    """
    schema = path / "sakila"
    schema.mkdir(exist_ok=True)
    (schema / name).write_text("x")


class TestIsCompressedBackup:
    """Assert the compression guard reads the base directory's data-file names."""

    def _compression_guard(self) -> Callable[[str], bool]:
        return _lift_plain("_is_compressed_backup")

    def test_missing_checkpoints_returns_false(self, tmp_path: Path) -> None:
        """Assert a directory that is not a backup at all is not called compressed."""
        (tmp_path / "ibdata1").write_text("x")
        assert self._compression_guard()(str(tmp_path)) is False

    @pytest.mark.parametrize("ext", ["qp", "zst", "lz4"])
    def test_compressed_data_file_returns_true(self, tmp_path: Path, ext: str) -> None:
        """Assert each supported compression suffix is recognized."""
        base = _write_base(tmp_path, data=f"ibdata1.{ext}")
        assert self._compression_guard()(base) is True

    def test_plaintext_uncompressed_returns_false(self, tmp_path: Path) -> None:
        """Assert a plain base backup is the one case that can be merged as-is."""
        assert self._compression_guard()(_write_base(tmp_path)) is False

    def test_no_ibdata_at_all_returns_true(self, tmp_path: Path) -> None:
        """Assert the existence fallback rejects a base whose ``ibdata1`` is renamed."""
        assert self._compression_guard()(_write_base(tmp_path, data="")) is True

    def test_encrypted_data_file_returns_true_via_fallback(
        self, tmp_path: Path
    ) -> None:
        """Assert a base whose ``ibdata1`` carries an encrypted rename is rejected.

        The encrypted suffixes are no longer named here, so this pins the
        existence fallback as the only thing standing between such a base and a
        merge that cannot work.
        """
        base = _write_base(tmp_path, data="ibdata1.xbcrypt")
        assert self._compression_guard()(base) is True


class TestIsGoodBaseBackup:
    """Assert the base-backup guard rejects prepared and encrypted bases."""

    def test_missing_checkpoints_returns_false(self, tmp_path: Path) -> None:
        """Assert a directory with no checkpoints file cannot seed an incremental."""
        instance, _, _ = _guard()
        assert instance._is_good_base_backup(str(tmp_path)) is False

    def test_fully_prepared_base_returns_false(self, tmp_path: Path) -> None:
        """Assert a fully prepared base cannot seed an incremental."""
        instance, _, _ = _guard()
        assert instance._is_good_base_backup(_write_base(tmp_path, PREPARED)) is False

    def test_plaintext_base_returns_true(self, tmp_path: Path) -> None:
        """Assert an unprepared plaintext base is accepted."""
        instance, _, _ = _guard()
        assert instance._is_good_base_backup(_write_base(tmp_path)) is True

    @pytest.mark.parametrize("suffix", ENCRYPTED_SUFFIXES)
    def test_encrypted_base_rejected_for_fast_restore(
        self, tmp_path: Path, suffix: str
    ) -> None:
        """Assert either encryption format stops a base from seeding a merge.

        Neither probe may be conditioned on what the job now encrypts with: a
        base encrypted by an earlier run stays encrypted after the setting is
        switched off.
        """
        instance, _, _ = _guard()
        base = _write_base(tmp_path, data=f"ibdata1{suffix}")
        assert instance._is_good_base_backup(base) is False

    @pytest.mark.parametrize("suffix", ENCRYPTED_SUFFIXES)
    def test_encrypted_base_accepted_for_less_space(
        self, tmp_path: Path, suffix: str
    ) -> None:
        """Assert ``less_space`` still chains against an encrypted base.

        That method takes its LSN from the plaintext checkpoints and never feeds
        the encrypted InnoDB files to ``--prepare``, and restore decrypts the
        whole chain first, so rejecting the base would force a needless full
        backup.
        """
        instance, _, _ = _guard(method="less_space")
        base = _write_base(tmp_path, data=f"ibdata1{suffix}")
        assert instance._is_good_base_backup(base) is True

    @pytest.mark.parametrize("suffix", ENCRYPTED_SUFFIXES)
    def test_detection_spawns_no_process(self, tmp_path: Path, suffix: str) -> None:
        """Assert the verdict is reached from file names alone.

        Reading file contents would put the guard behind ``gpg`` being installed,
        which a host that only ever encrypted with xbcrypt has no reason to have.
        """
        instance, _, calls = _guard()
        base = _write_base(tmp_path, data=f"ibdata1{suffix}")
        assert instance._is_good_base_backup(base) is False
        assert calls == []

    @pytest.mark.parametrize("suffix", ENCRYPTED_SUFFIXES)
    def test_nested_encrypted_data_file_is_detected(
        self, tmp_path: Path, suffix: str
    ) -> None:
        """Assert encryption is detected in the schema subdirectories, not just the root."""
        instance, _, _ = _guard()
        base = _write_base(tmp_path, data="")
        _write_nested(tmp_path, f"film.ibd{suffix}")
        assert instance._is_good_base_backup(base) is False

    @pytest.mark.parametrize("suffix", ENCRYPTED_SUFFIXES)
    def test_partially_encrypted_base_is_rejected(
        self, tmp_path: Path, suffix: str
    ) -> None:
        """Assert a base only partly encrypted cannot seed a merge either.

        An encryption pass that dies part-way leaves this state behind after the
        backup has already been moved into the retained directory, and a single
        renamed table is enough to break ``--prepare``. The plaintext ``ibdata1``
        also defeats the compression guard's existence fallback, so this is the
        one thing standing between such a base and a merge that cannot work.
        """
        instance, _, _ = _guard()
        base = _write_base(tmp_path)
        _write_nested(tmp_path, f"film.ibd{suffix}")
        assert instance._is_good_base_backup(base) is False

    def test_plaintext_metadata_does_not_hide_encryption(self, tmp_path: Path) -> None:
        """Assert the metadata SEP leaves in plaintext does not mask an encrypted base."""
        instance, _, _ = _guard()
        base = _write_base(tmp_path, data="ibdata1.xbcrypt")
        (tmp_path / "md5sum").write_text("checksums")
        (tmp_path / ".uploadme").write_text("")
        assert instance._is_good_base_backup(base) is False

    def test_empty_checkpoints_file_is_read_as_unprepared(self, tmp_path: Path) -> None:
        """Assert a truncated checkpoints file leaves the base's own state deciding."""
        instance, _, _ = _guard()
        assert instance._is_good_base_backup(_write_base(tmp_path, "")) is True

    def test_prepared_marker_past_the_first_line_is_not_read(
        self, tmp_path: Path
    ) -> None:
        """Assert only the first line marks a base as prepared, as xtrabackup writes it."""
        instance, _, _ = _guard()
        contents = f"to_lsn = {BASE_LSN}\nbackup_type = full-prepared\n"
        assert instance._is_good_base_backup(_write_base(tmp_path, contents)) is True

    def test_base_holding_no_data_files_is_not_called_encrypted(
        self, tmp_path: Path
    ) -> None:
        """Assert a base with only metadata left is passed on, not blamed on encryption.

        Nothing in it is encrypted, so this guard has no verdict to give; the
        compression guard's existence fallback is what stops the merge.
        """
        instance, _, _ = _guard()
        assert instance._is_good_base_backup(_write_base(tmp_path, data="")) is True

    def test_accepted_base_logs_nothing(self, tmp_path: Path) -> None:
        """Assert deciding on a plaintext base leaks no file names into the log."""
        instance, recorder, _ = _guard()
        assert instance._is_good_base_backup(_write_base(tmp_path)) is True
        assert recorder.errors == []

    def test_unset_incremental_method_returns_true(self, tmp_path: Path) -> None:
        """Assert a job with no incremental method is answered, not crashed on."""
        instance, _, _ = _guard(method=None)
        assert instance._is_good_base_backup(_write_base(tmp_path)) is True


class TestDefineIncrementalOptions:
    """Assert the incremental decision reports the reason it fell back to full."""

    def _decide(
        self,
        tmp_path: Path,
        *,
        backup: str,
        method: str | None = "fast_restore",
        checkpoints: str = UNPREPARED,
        found: bool = True,
    ) -> tuple[Any, _Recorder]:
        """Drive ``_define_incremental_options`` over a single base backup.

        :param tmp_path: Root standing in for the server's backup directory.
        :param backup: Name of the data file the base backup holds.
        :param method: Value for ``incremental_method``.
        :param checkpoints: Body of the base's ``xtrabackup_checkpoints`` file.
        :param found: Whether the backup directory listing reports the base at all.
        :return: The instance after the decision and its logger.
        """
        base_dir = tmp_path / "2026-08-20_00-00-00"
        base_dir.mkdir()
        _write_base(base_dir, checkpoints, data=backup)

        instance, recorder, _ = _lift_guards(
            (
                "_define_incremental_options",
                "_is_good_base_backup",
                "_is_encrypted_base",
            )
        )
        instance.incremental_method = method
        instance.incremental_cycle = "daily"
        instance.backup_server_dir = str(tmp_path)
        instance.prepare_backup = True
        instance.incremental = False
        instance.hardlink = True
        instance.to_lsn = 0
        instance._list_backups = lambda _path: [base_dir.name] if found else []
        instance._is_ongoing_incremental_cycle = lambda *_args: True
        instance._is_compressed_backup = _lift_plain("_is_compressed_backup")
        instance._get_incremental_lsn = _lift_plain("_get_incremental_lsn")

        instance._define_incremental_options()
        return instance, recorder

    @pytest.mark.parametrize("suffix", ENCRYPTED_SUFFIXES)
    def test_encrypted_base_blames_encryption_not_compression(
        self, tmp_path: Path, suffix: str
    ) -> None:
        """Assert an encrypted base falls back to full naming encryption as the cause."""
        instance, recorder = self._decide(tmp_path, backup=f"ibdata1{suffix}")
        assert instance.incremental is False
        assert any("encrypted base" in msg for msg in recorder.warnings)
        assert not any("compressed base" in msg for msg in recorder.warnings)

    def test_compressed_base_still_blames_compression(self, tmp_path: Path) -> None:
        """Assert a plaintext compressed base keeps its own fallback message."""
        instance, recorder = self._decide(tmp_path, backup="ibdata1.zst")
        assert instance.incremental is False
        assert any("compressed base" in msg for msg in recorder.warnings)

    def test_base_with_no_data_files_falls_back_to_full(self, tmp_path: Path) -> None:
        """Assert a base stripped of its data files cannot seed an incremental."""
        instance, recorder = self._decide(tmp_path, backup="")
        assert instance.incremental is False
        assert recorder.warnings

    def test_plaintext_base_runs_incremental(self, tmp_path: Path) -> None:
        """Assert a plaintext uncompressed base still produces an incremental."""
        instance, _ = self._decide(tmp_path, backup="ibdata1")
        assert instance.incremental is True
        assert instance.to_lsn == BASE_LSN

    def test_less_space_chains_onto_an_encrypted_base(self, tmp_path: Path) -> None:
        """Assert an encrypted base still starts an incremental under ``less_space``.

        The chain reads its LSN from the plaintext checkpoints, so rejecting the
        base here would turn every scheduled run into a full backup.
        """
        instance, recorder = self._decide(
            tmp_path, backup="ibdata1.xbcrypt", method="less_space"
        )
        assert instance.incremental is True
        assert instance.to_lsn == BASE_LSN
        assert recorder.warnings == []

    def test_missing_to_lsn_falls_back_to_full(self, tmp_path: Path) -> None:
        """Assert a base whose checkpoints carry no LSN cannot seed an incremental."""
        instance, recorder = self._decide(
            tmp_path, backup="ibdata1", checkpoints="backup_type = full-backuped\n"
        )
        assert instance.incremental is False
        assert any("to_lsn was not found" in msg for msg in recorder.warnings)

    def test_no_previous_backup_starts_a_base(self, tmp_path: Path) -> None:
        """Assert the first run of a schedule reports it is creating the base."""
        instance, recorder = self._decide(tmp_path, backup="ibdata1", found=False)
        assert instance.incremental is False
        assert any("initial full backup" in msg for msg in recorder.infos)

    def test_non_incremental_job_never_consults_the_guards(
        self, tmp_path: Path
    ) -> None:
        """Assert a job with no incremental method leaves the backup plan untouched."""
        instance, recorder = self._decide(tmp_path, backup="ibdata1", method=None)
        assert instance.incremental is False
        assert instance.prepare_backup is True
        assert recorder.warnings == []
