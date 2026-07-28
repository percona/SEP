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

import ast
import logging
import os
import pathlib
import subprocess
import types

import pytest

_PAYLOAD_PATH = (
    pathlib.Path(__file__).parents[5] / "app/sep/apps/mysql_backups/xtrabackup_payload"
)
_XBCRYPT_BIN = os.getenv("PERCONA_BACKUP_XBCRYPT_BIN", "/usr/bin/xbcrypt")

# Module-level constants the extracted symbols read (default args / bodies).
_CONST_NAMES = frozenset(
    {
        "MD5SUM_FILE",
        "UPLOADME_FILE",
        "XTRABACKUP_INFO",
        "XTRABACKUP_CHECKPOINTS",
        "XBCRYPT_BIN",
        "GPG_BIN",
    }
)


def _const_nodes(tree: ast.Module) -> list[ast.stmt]:
    """Return the whitelisted module-level constant assignments from the payload AST."""
    return [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in _CONST_NAMES
    ]


def _base_namespace() -> dict:
    """Return an exec namespace seeded with real modules and a stub ``BackupError``."""
    namespace: dict = {
        "os": os,
        "subprocess": subprocess,
        "logging": logging,
        "Path": pathlib.Path,
        "Any": object,
    }
    exec("class BackupError(Exception):\n    pass", namespace)
    return namespace


def _load_function(name: str) -> object:
    """Exec a single module-level payload function with its constants seeded."""
    tree = ast.parse(_PAYLOAD_PATH.read_text())
    namespace = _base_namespace()
    body = _const_nodes(tree)
    fn_nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if not fn_nodes:
        raise RuntimeError(f"{name} not found in {_PAYLOAD_PATH}. Renamed or removed?")
    body = body + fn_nodes
    exec(
        compile(ast.Module(body=body, type_ignores=[]), str(_PAYLOAD_PATH), "exec"),
        namespace,
    )
    return namespace[name]


class _FakeProc:
    """A ``Popen`` result with a fixed return code and canned stderr."""

    def __init__(self, returncode: int) -> None:
        self.returncode = returncode

    def communicate(self):
        """Return ``(stdout, stderr)`` -- stderr is non-empty so error paths format it."""
        return b"", b"boom"


def _payload_instance(method_names: tuple[str, ...], returncode: int = 0):
    """Build an instance of a synthetic class carrying the named payload methods.

    The methods are lifted verbatim from the payload and exec'd into a class over
    a namespace whose ``subprocess`` is faked (recording every command and
    returning ``returncode``). Returns ``(instance, BackupError, calls)`` where
    ``calls`` is the list of xbcrypt argv lists the code tried to run.
    """
    tree = ast.parse(_PAYLOAD_PATH.read_text())
    method_nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in method_names
    ]
    missing = set(method_names) - {node.name for node in method_nodes}
    if missing:
        raise RuntimeError(f"{sorted(missing)} not found in {_PAYLOAD_PATH}.")

    calls: list[list[str]] = []

    class _FakeSubprocess:
        PIPE = -1

        # N802/ARG004: signature mirrors ``subprocess.Popen`` verbatim so the
        # payload's real call site binds unchanged; stdout/stderr are accepted
        # and ignored on purpose.
        @staticmethod
        def Popen(cmd, stdout=None, stderr=None):  # noqa: N802, ARG004
            calls.append(list(cmd))
            return _FakeProc(returncode)

    namespace = _base_namespace()
    namespace["subprocess"] = _FakeSubprocess
    exec(
        compile(
            ast.Module(body=_const_nodes(tree), type_ignores=[]),
            str(_PAYLOAD_PATH),
            "exec",
        ),
        namespace,
    )
    cls = ast.ClassDef(
        name="_Payload",
        bases=[],
        keywords=[],
        body=list(method_nodes),
        decorator_list=[],
    )
    module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    exec(compile(module, str(_PAYLOAD_PATH), "exec"), namespace)

    inst = namespace["_Payload"]()
    inst.logger = types.SimpleNamespace(
        info=lambda *_a, **_k: None,
        debug=lambda *_a, **_k: None,
        error=lambda *_a, **_k: None,
    )
    inst._clean_after_error = lambda: None
    inst.xtrabackup_aes256_keyfile = "/keys/aes.key"
    inst.compress = False
    inst.get_compression_ext = lambda: ""
    return inst, namespace["BackupError"], calls


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

    def _fn_with_proc(self, returncode: int):
        namespace = _base_namespace()
        tree = ast.parse(_PAYLOAD_PATH.read_text())
        calls: list[list[str]] = []

        class _Popen:
            def __init__(self, cmd, stdout=None, stderr=None):
                calls.append(cmd)
                self.returncode = returncode

            def communicate(self):
                return b"", b"err"

        namespace["subprocess"] = types.SimpleNamespace(Popen=_Popen, PIPE=-1)
        fn_nodes = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "is_encrypted_dir"
        ]
        exec(
            compile(
                ast.Module(body=_const_nodes(tree) + fn_nodes, type_ignores=[]),
                str(_PAYLOAD_PATH),
                "exec",
            ),
            namespace,
        )
        return namespace["is_encrypted_dir"], calls

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

    def test_default_method_is_gpg(self, tmp_path) -> None:
        """Assert the default method stays gpg so existing call sites are unaffected."""
        (tmp_path / "plain.txt").write_text("x")
        fn, calls = self._fn_with_proc(0)
        assert fn(str(tmp_path)) is True
        assert calls, "gpg was not shelled out to under the default method"


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


_DECRYPT_METHODS = (
    "_decrypt_file_aes256",
    "_decrypt_checkpoint_file",
    "_decrypt_info_file",
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
        inst._decrypt_checkpoint_file("/keys/aes.key", str(tmp_path))
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

    def test_info_decrypt_honors_compression_ext(self, tmp_path) -> None:
        """Assert the info file input/output names carry the compression extension."""
        (tmp_path / "xtrabackup_info.zst.xbcrypt").write_text("enc")
        inst, _, calls = _payload_instance(_DECRYPT_METHODS)
        inst.compress = True
        inst.get_compression_ext = lambda: ".zst"
        inst._decrypt_info_file("/keys/aes.key", str(tmp_path))
        io_args = [a for a in calls[0] if a.startswith(("--input=", "--output="))]
        assert io_args == [
            f"--input={tmp_path}/xtrabackup_info.zst.xbcrypt",
            f"--output={tmp_path}/xtrabackup_info.zst",
        ]

    def test_decrypt_failure_raises_and_cleans(self, tmp_path) -> None:
        """Assert a nonzero decrypt raises ``BackupError`` and triggers cleanup."""
        (tmp_path / "xtrabackup_checkpoints.xbcrypt").write_text("enc")
        inst, backup_error, _ = _payload_instance(_DECRYPT_METHODS, returncode=1)
        cleaned = {"n": 0}
        inst._clean_after_error = lambda: cleaned.__setitem__("n", cleaned["n"] + 1)
        with pytest.raises(backup_error):
            inst._decrypt_checkpoint_file("/keys/aes.key", str(tmp_path))
        assert cleaned["n"] == 1
