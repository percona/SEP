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

"""Tests for the payload's xbcrypt/AES-256 encryption, decryption and verification.

The payload script cannot be imported (it pulls boto3 and other heavy runtime
deps), so the relevant symbols are located in the source via AST and exec'd in an
isolated namespace: module-level ``is_encrypted_dir`` on its own, and the xbcrypt
methods gathered into a synthetic class exec'd over a namespace seeded with the
module constants, a fake ``subprocess`` recording commands, and a stub
``BackupError``. Real files under ``tmp_path`` back the ``os`` calls so the
"plaintext removed on success" behaviour is observed for real.
"""

import os
import shutil
import subprocess
import types
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.app.sep.apps.mysql_backups.payload_harness import (
    gpg_probe as _gpg_probe,
)
from tests.app.sep.apps.mysql_backups.payload_harness import (
    load_function as _load_function,
)
from tests.app.sep.apps.mysql_backups.payload_harness import (
    payload_instance as _payload_instance,
)
from tests.app.sep.apps.mysql_backups.payload_harness import (
    XBCRYPT_BIN as _XBCRYPT_BIN,
)

GPG_BIN = shutil.which("gpg")
needs_gpg = pytest.mark.skipif(GPG_BIN is None, reason="gpg is not installed")


class TestIsEncryptedDirAes256:
    """Assert ``is_encrypted_dir(method='aes256')`` verifies by ``.xbcrypt`` extension."""

    def _fn(self):
        return _load_function("is_encrypted_dir")

    def test_all_files_encrypted_returns_true(self, tmp_path) -> None:
        """Assert a directory where every data file ends in ``.xbcrypt`` verifies True."""
        (tmp_path / "ibdata1.xbcrypt").write_text("x")
        (tmp_path / "db").mkdir()
        (tmp_path / "db" / "t.ibd.xbcrypt").write_text("x")
        assert self._fn()(str(tmp_path), method="aes256") is True

    def test_plaintext_straggler_returns_false(self, tmp_path) -> None:
        """Assert a single plaintext non-excluded file (e.g. copied my.cnf) fails."""
        (tmp_path / "ibdata1.xbcrypt").write_text("x")
        (tmp_path / "_etc_my.cnf").write_text("plaintext")
        assert self._fn()(str(tmp_path), method="aes256") is False

    def test_unknown_method_raises(self, tmp_path) -> None:
        """Assert an unrecognized method fails fast instead of silently using gpg."""
        with pytest.raises(Exception, match="Unknown encryption method"):
            self._fn()(str(tmp_path), method="AES256")

    def test_excluded_metadata_left_plaintext_still_true(self, tmp_path) -> None:
        """Assert plaintext metadata files SEP reads post-backup do not fail verification."""
        (tmp_path / "ibdata1.xbcrypt").write_text("x")
        for name in (
            "xtrabackup_checkpoints",
            "xtrabackup_info",
            "md5sum",
            ".uploadme",
        ):
            (tmp_path / name).write_text("meta")
        assert self._fn()(str(tmp_path), method="aes256") is True

    def test_empty_dir_returns_true(self, tmp_path) -> None:
        """Assert an empty directory vacuously verifies True."""
        assert self._fn()(str(tmp_path), method="aes256") is True


class TestIsEncryptedDirGpgUnchanged:
    """Assert the gpg path keeps its per-file ``gpg --decrypt`` return-code check."""

    def _fn_with_proc(
        self, returncode: int
    ) -> tuple[Callable[..., bool], list[list[str]]]:
        return _gpg_probe(returncode=returncode)

    def test_gpg_zero_return_is_true(self, tmp_path) -> None:
        """Assert gpg return-code 0 for every file means encrypted (True)."""
        (tmp_path / "ibdata1.gpg").write_text("x")
        fn, calls = self._fn_with_proc(0)
        assert fn(str(tmp_path)) is True
        assert calls
        assert calls[0][0].endswith("gpg")

    def test_gpg_nonzero_return_is_false(self, tmp_path) -> None:
        """Assert a nonzero gpg return-code marks the directory unencrypted (False)."""
        (tmp_path / "plain.txt").write_text("x")
        fn, _ = self._fn_with_proc(2)
        assert fn(str(tmp_path)) is False


@needs_gpg
class TestIsEncryptedDirAgainstRealGpg:
    """Assert the gpg verification runs a real ``gpg``, not only a faked one."""

    def _fn(self, monkeypatch: pytest.MonkeyPatch) -> Callable[..., bool]:
        """Return ``is_encrypted_dir`` bound to the installed ``gpg`` binary."""
        monkeypatch.setenv("PERCONA_BACKUP_GPG_BIN", str(GPG_BIN))
        return _load_function("is_encrypted_dir")

    def _encrypt(self, path: Path) -> None:
        """Encrypt ``path`` in place with a passphrase, the way a backup leaves it.

        Symmetric encryption keeps the test off the machine's keyring while still
        producing a file only a real ``gpg`` recognizes.
        """
        subprocess.run(
            [
                str(GPG_BIN),
                "--batch",
                "--yes",
                "--passphrase",
                "backup",
                "--symmetric",
                "--output",
                f"{path}.gpg",
                str(path),
            ],
            check=True,
            capture_output=True,
        )
        path.unlink()

    def test_real_encrypted_file_is_recognized(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Assert a genuinely gpg-encrypted directory verifies as encrypted."""
        (tmp_path / "ibdata1").write_text("x")
        self._encrypt(tmp_path / "ibdata1")
        assert self._fn(monkeypatch)(str(tmp_path)) is True

    def test_real_plaintext_file_is_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Assert a plaintext file the real ``gpg`` cannot decrypt fails verification."""
        (tmp_path / "ibdata1").write_text("x")
        assert self._fn(monkeypatch)(str(tmp_path)) is False


_ENCRYPT_METHODS = ("encrypt_files_aes256", "_run_encrypt_file_aes256", "_run_xbcrypt")


class TestEncryptFilesAes256:
    """Assert the recursive xbcrypt encrypt pass targets the right files/commands."""

    def test_builds_expected_xbcrypt_command(self, tmp_path) -> None:
        """Assert each file is encrypted with the AES256 flags and ``.xbcrypt`` output."""
        target = tmp_path / "ibdata1"
        target.write_text("data")
        inst, _, calls = _payload_instance(_ENCRYPT_METHODS)
        inst.encrypt_files_aes256(str(tmp_path))
        assert calls == [
            [
                _XBCRYPT_BIN,
                "--encrypt-algo=AES256",
                "--encrypt-key-file=/keys/aes.key",
                f"--input={target}",
                f"--output={target}.xbcrypt",
            ]
        ]

    def test_recurses_into_subdirectories(self, tmp_path) -> None:
        """Assert nested data files (per-database dirs) are encrypted too."""
        (tmp_path / "db").mkdir()
        (tmp_path / "db" / "t.ibd").write_text("data")
        inst, _, calls = _payload_instance(_ENCRYPT_METHODS)
        inst.encrypt_files_aes256(str(tmp_path))
        inputs = [a for cmd in calls for a in cmd if a.startswith("--input=")]
        assert inputs == [f"--input={tmp_path / 'db' / 't.ibd'}"]

    def test_skips_already_encrypted_and_excluded(self, tmp_path) -> None:
        """Assert ``.xbcrypt`` files and excluded metadata are not (re-)encrypted."""
        (tmp_path / "cert.pem.xbcrypt").write_text("enc")
        (tmp_path / "xtrabackup_checkpoints").write_text("meta")
        (tmp_path / "md5sum").write_text("meta")
        (tmp_path / "my.cnf").write_text("plain")
        inst, _, calls = _payload_instance(_ENCRYPT_METHODS)
        inst.encrypt_files_aes256(str(tmp_path))
        inputs = [a for cmd in calls for a in cmd if a.startswith("--input=")]
        assert inputs == [f"--input={tmp_path / 'my.cnf'}"]

    def test_removes_plaintext_on_success(self, tmp_path) -> None:
        """Assert the plaintext source is unlinked after a successful encrypt."""
        target = tmp_path / "ibdata1"
        target.write_text("data")
        inst, _, _ = _payload_instance(_ENCRYPT_METHODS, returncode=0)
        inst.encrypt_files_aes256(str(tmp_path))
        assert not target.exists()

    def test_raises_backuperror_on_nonzero(self, tmp_path) -> None:
        """Assert a failed xbcrypt run raises ``BackupError`` (unhappy path)."""
        (tmp_path / "ibdata1").write_text("data")
        inst, backup_error, _ = _payload_instance(_ENCRYPT_METHODS, returncode=1)
        with pytest.raises(backup_error):
            inst.encrypt_files_aes256(str(tmp_path))

    def test_empty_dir_is_noop(self, tmp_path) -> None:
        """Assert an empty directory triggers no xbcrypt invocations."""
        inst, _, calls = _payload_instance(_ENCRYPT_METHODS)
        inst.encrypt_files_aes256(str(tmp_path))
        assert calls == []


class _RecordingThreadPool:
    """Stand in for ``multiprocessing.pool.ThreadPool`` that runs synchronously.

    Records the requested ``processes`` count instead of actually pooling, so
    tests can assert on the size the real call site requested.
    """

    def __init__(self, processes: int) -> None:
        self.processes = processes

    def map(self, func, iterable):
        """Apply ``func`` to each item synchronously, mirroring ``ThreadPool.map``."""
        return [func(item) for item in iterable]


class TestEncryptFilesAes256WorkerCount:
    """Assert the encrypt pass bounds its ``ThreadPool`` size by CPU cores."""

    @pytest.mark.parametrize(
        ("cpu_count", "expected"),
        [(8, 5), (2, 2), (None, 5)],
    )
    def test_pool_size_bounded_by_cpu_count(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
        cpu_count: int | None,
        expected: int,
    ) -> None:
        """Assert the pool never exceeds available cores, capped at 5 by default."""
        monkeypatch.setattr(os, "cpu_count", lambda: cpu_count)
        (tmp_path / "ibdata1").write_text("data")
        pool_sizes: list[int] = []

        class _CapturingThreadPool(_RecordingThreadPool):
            def __init__(self, processes: int) -> None:
                pool_sizes.append(processes)
                super().__init__(processes)

        inst, _, _ = _payload_instance(
            _ENCRYPT_METHODS,
            extra_namespace={
                "thread_pool": types.SimpleNamespace(ThreadPool=_CapturingThreadPool)
            },
        )
        inst.encrypt_files_aes256(str(tmp_path))
        assert pool_sizes == [expected]


_DECRYPT_METHODS = (
    "_decrypt_file_aes256",
    "_decrypt_metadata_file",
    "_run_xbcrypt",
)


class TestDecryptFileAes256:
    """Assert the shared xbcrypt decrypt helper and its metadata callers."""

    def test_missing_input_is_noop(self, tmp_path) -> None:
        """Assert decrypting a non-existent input does nothing (no shell-out)."""
        inst, _, calls = _payload_instance(_DECRYPT_METHODS)
        inst._decrypt_file_aes256(
            "/keys/aes.key", str(tmp_path / "absent.xbcrypt"), "out"
        )
        assert calls == []

    def test_checkpoint_decrypt_command_and_removal(self, tmp_path) -> None:
        """Assert checkpoints are decrypted with ``-d`` and the ``.xbcrypt`` removed."""
        enc = tmp_path / "xtrabackup_checkpoints.xbcrypt"
        enc.write_text("enc")
        inst, _, calls = _payload_instance(_DECRYPT_METHODS)
        inst._decrypt_metadata_file(
            "/keys/aes.key", str(tmp_path), "xtrabackup_checkpoints"
        )
        assert calls == [
            [
                _XBCRYPT_BIN,
                "-d",
                "--encrypt-algo=AES256",
                "--encrypt-key-file=/keys/aes.key",
                f"--input={tmp_path}/xtrabackup_checkpoints.xbcrypt",
                f"--output={tmp_path}/xtrabackup_checkpoints",
            ]
        ]
        assert not enc.exists()

    def test_compressible_decrypt_honors_the_compression_ext(self, tmp_path) -> None:
        """Assert a compressible file is decrypted under its compressed name.

        The AES-256 pass runs after compression, so on disk the info file is
        ``xtrabackup_info.zst.xbcrypt``. A name composed without the extension
        misses it, and the decrypt no-ops on the absent path rather than failing,
        leaving the file encrypted with nothing said.
        """
        (tmp_path / "xtrabackup_info.zst.xbcrypt").write_text("enc")
        inst, _, calls = _payload_instance(_DECRYPT_METHODS)
        inst.compress = True
        inst.get_compression_ext = lambda: ".zst"
        inst._decrypt_metadata_file(
            "/keys/aes.key", str(tmp_path), "xtrabackup_info", compressible=True
        )
        io_args = [a for a in calls[0] if a.startswith(("--input=", "--output="))]
        assert io_args == [
            f"--input={tmp_path}/xtrabackup_info.zst.xbcrypt",
            f"--output={tmp_path}/xtrabackup_info.zst",
        ]

    def test_non_compressible_decrypt_ignores_the_compression_ext(
        self, tmp_path
    ) -> None:
        """Assert the checkpoints file keeps its plain name in a compressed backup.

        Only the info file is compressed, so composing the extension onto every
        metadata file would miss the one that is not.
        """
        (tmp_path / "xtrabackup_checkpoints.xbcrypt").write_text("enc")
        inst, _, calls = _payload_instance(_DECRYPT_METHODS)
        inst.compress = True
        inst.get_compression_ext = lambda: ".zst"
        inst._decrypt_metadata_file(
            "/keys/aes.key", str(tmp_path), "xtrabackup_checkpoints"
        )
        io_args = [a for a in calls[0] if a.startswith(("--input=", "--output="))]
        assert io_args == [
            f"--input={tmp_path}/xtrabackup_checkpoints.xbcrypt",
            f"--output={tmp_path}/xtrabackup_checkpoints",
        ]

    def test_decrypt_failure_raises_and_cleans(self, tmp_path) -> None:
        """Assert a nonzero decrypt raises ``BackupError`` and triggers cleanup."""
        (tmp_path / "xtrabackup_checkpoints.xbcrypt").write_text("enc")
        inst, backup_error, _ = _payload_instance(_DECRYPT_METHODS, returncode=1)
        cleaned = {"n": 0}
        inst._clean_after_error = lambda: cleaned.__setitem__("n", cleaned["n"] + 1)
        with pytest.raises(backup_error):
            inst._decrypt_metadata_file(
                "/keys/aes.key", str(tmp_path), "xtrabackup_checkpoints"
            )
        assert cleaned["n"] == 1
