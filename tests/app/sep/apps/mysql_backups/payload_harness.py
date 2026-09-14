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

"""Share the AST-extraction harness for exercising mysql_backups payload methods.

The payload cannot be imported directly (it pulls boto3 and other heavy
runtime deps), so callers locate the relevant symbols in the source via AST
and exec them in an isolated namespace. This module holds the shared pieces
so every test module that reaches into a payload — encryption, restore, the
incremental base guards — builds on one harness instead of re-exporting private
helpers from each other.

Helpers default to the XtraBackup payload for backwards compatibility; pass
``payload_path`` to target Mydumper or Binlog.
"""

import ast
import logging
import multiprocessing.pool
import os
import pathlib
import re
import subprocess
import types
from collections.abc import Callable
from typing import Any

from tests.app.sep.apps.mysql_backups.conftest import (
    XTRABACKUP_PAYLOAD_PATH,
    xtrabackup_payload_tree,
)

# Module-level constants the extracted symbols read (default args / bodies).
_CONST_NAMES = frozenset(
    {
        "MD5SUM_FILE",
        "UPLOADME_FILE",
        "MYDUMPER_METADATA",
        "XTRABACKUP_INFO",
        "XTRABACKUP_CHECKPOINTS",
        "EXCLUDE_FILES",
        "PLAINTEXT_METADATA_FILES",
        "ENCRYPTION_FORMATS",
        "BACKUP_TYPES",
        "XBCRYPT_BIN",
        "GPG_BIN",
        "XTRABACKUP_BIN",
        "XTRABACKUP_BIN_REAL",
        "XTRABACKUP_BIN_MARIADB",
    }
)


def _payload_path(payload_path: pathlib.Path | None = None) -> pathlib.Path:
    """Return ``payload_path``, defaulting to the XtraBackup payload."""
    return payload_path or XTRABACKUP_PAYLOAD_PATH


def _payload_tree(payload_path: pathlib.Path | None = None) -> ast.Module:
    """Parse and return the chosen payload's AST."""
    path = _payload_path(payload_path)
    if path == XTRABACKUP_PAYLOAD_PATH:
        return xtrabackup_payload_tree()
    return ast.parse(path.read_text())


def const_nodes(
    tree: ast.Module | None = None, *, payload_path: pathlib.Path | None = None
) -> list[ast.stmt]:
    """Return the whitelisted module-level constant assignments from the payload AST."""
    tree = tree if tree is not None else _payload_tree(payload_path)
    return [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in _CONST_NAMES
    ]


def base_namespace() -> dict:
    """Return an exec namespace seeded with real modules and a stub ``BackupError``."""
    namespace: dict = {
        "os": os,
        "subprocess": subprocess,
        "logging": logging,
        "re": re,
        "Path": pathlib.Path,
        "Any": object,
        "thread_pool": multiprocessing.pool,
    }
    exec("class BackupError(Exception):\n    pass", namespace)  # noqa: S102
    return namespace


def load_constant(name: str, *, payload_path: pathlib.Path | None = None) -> object:
    """Return a whitelisted module-level constant's value from the payload source."""
    path = _payload_path(payload_path)
    namespace = base_namespace()
    exec(  # noqa: S102
        compile(
            ast.Module(body=const_nodes(payload_path=path), type_ignores=[]),
            str(path),
            "exec",
        ),
        namespace,
    )
    return namespace[name]


XBCRYPT_BIN = load_constant("XBCRYPT_BIN")


def load_function(
    name: str, *, payload_path: pathlib.Path | None = None
) -> Callable[..., Any]:
    """Extract a single module-level payload function with its constants seeded.

    :raises TypeError: If the extracted name is not callable.
    """
    path = _payload_path(payload_path)
    tree = _payload_tree(path)
    namespace = base_namespace()
    body = const_nodes(tree)
    fn_nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if not fn_nodes:
        raise RuntimeError(f"{name} not found in {path}. Renamed or removed?")
    body = body + fn_nodes
    exec(  # noqa: S102
        compile(ast.Module(body=body, type_ignores=[]), str(path), "exec"),
        namespace,
    )
    extracted = namespace[name]
    if not callable(extracted):
        raise TypeError(f"{name} in {path} is not callable.")
    return extracted


def payload_method(
    class_name: str,
    method_name: str,
    *,
    extra_namespace: dict[str, object] | None = None,
    payload_path: pathlib.Path | None = None,
) -> Callable[..., object]:
    """Return one payload method lifted out of its class as a plain function.

    ``payload_instance`` cannot run an ``__init__``: it builds a bases-less class,
    so ``super().__init__(...)`` has nothing to reach. Lifting the method to module
    level drops the ``__class__`` cell the compiler adds inside a class body, which
    leaves zero-arg ``super()`` an ordinary global lookup — so a caller can stub it
    and drive the rest of the method for real, passing its own object as ``self``.

    :param class_name: The payload class owning the method.
    :param method_name: The method to lift.
    :param extra_namespace: Globals the method body reads that are not whitelisted
        constants — module-level payload functions, or stand-ins for them.
    :param payload_path: Payload source to read; defaults to XtraBackup.
    :return: The lifted method, called as ``fn(self, ...)``.
    """
    path = _payload_path(payload_path)
    tree = _payload_tree(path)
    class_nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == class_name
    ]
    if not class_nodes:
        raise RuntimeError(f"{class_name} not found in {path}. Renamed or removed?")
    method_nodes = [
        node
        for node in class_nodes[0].body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    ]
    if not method_nodes:
        raise RuntimeError(
            f"{class_name}.{method_name} not found in {path}. Renamed or removed?"
        )
    namespace = base_namespace()
    module = ast.fix_missing_locations(
        ast.Module(body=const_nodes(tree) + method_nodes, type_ignores=[])
    )
    exec(compile(module, str(path), "exec"), namespace)  # noqa: S102
    namespace.update(extra_namespace or {})
    return namespace[method_name]


def gpg_probe(
    *,
    returncode: int = 0,
    payload_path: pathlib.Path | None = None,
) -> tuple[Callable[..., bool], list[list[str]]]:
    """Return the payload's ``is_encrypted_dir`` wired to a faked ``gpg`` binary.

    :param returncode: Exit status every faked ``gpg`` run reports.
    :param payload_path: Payload source to read; defaults to XtraBackup.
    :return: The lifted function and the list its ``Popen`` calls append to.
    """
    path = _payload_path(payload_path)
    tree = _payload_tree(path)
    namespace = base_namespace()
    calls: list[list[str]] = []

    class _Popen:
        def __init__(self, cmd: list[str], **_kwargs: object) -> None:
            calls.append(list(cmd))
            self.returncode = returncode

        def communicate(self) -> tuple[bytes, bytes]:
            return b"", b"err"

    namespace["subprocess"] = types.SimpleNamespace(Popen=_Popen, PIPE=-1)
    fn_nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "is_encrypted_dir"
    ]
    exec(  # noqa: S102
        compile(
            ast.Module(body=const_nodes(tree) + fn_nodes, type_ignores=[]),
            str(path),
            "exec",
        ),
        namespace,
    )
    return namespace["is_encrypted_dir"], calls


class FakeProc:
    """Stand in for a ``Popen`` result with a fixed return code and canned stderr."""

    def __init__(self, returncode: int) -> None:
        self.returncode = returncode

    def communicate(self) -> tuple[bytes, bytes]:
        """Return ``(stdout, stderr)`` -- stderr is non-empty so error paths format it."""
        return b"", b"boom"


def payload_instance(
    method_names: tuple[str, ...],
    *,
    returncode: int = 0,
    extra_namespace: dict[str, object] | None = None,
    real_subprocess: bool = False,
    payload_path: pathlib.Path | None = None,
) -> tuple[object, type[Exception], list[list[str]]]:
    """Build an instance of a synthetic class carrying the named payload methods.

    The methods are lifted verbatim from the payload and exec'd into a class over
    a namespace whose ``subprocess`` is faked (recording every command and
    returning ``returncode``). Returns ``(instance, BackupError, calls)`` where
    ``calls`` is the list of xbcrypt argv lists the code tried to run.

    :param method_names: The payload method names to lift into the synthetic class.
    :param returncode: The return code the faked ``subprocess.Popen`` reports.
    :param extra_namespace: Extra globals (e.g. a fake module-level function, or a
        payload constant override such as ``XBCRYPT_BIN``) merged into the exec
        namespace after the payload's own constants are loaded (so this wins),
        before the class is compiled.
    :param real_subprocess: When True, keep the real ``subprocess`` module instead
        of faking ``Popen`` -- for integration tests that need a real process (e.g.
        a stand-in ``xbcrypt`` executable) to actually run. ``calls`` is unused
        (always ``[]``) in this mode.
    :param payload_path: Payload source to read; defaults to XtraBackup.
    """
    path = _payload_path(payload_path)
    tree = _payload_tree(path)
    method_nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in method_names
    ]
    missing = set(method_names) - {node.name for node in method_nodes}
    if missing:
        raise RuntimeError(f"{sorted(missing)} not found in {path}.")

    calls: list[list[str]] = []

    class _FakeSubprocess:
        PIPE = -1

        # N802: signature mirrors ``subprocess.Popen`` verbatim so the payload's
        # real call site binds unchanged. ``list.append`` is GIL-atomic, so this
        # stays safe when ``encrypt_files_aes256`` calls it from pool threads.
        @staticmethod
        def Popen(cmd: list[str], **_kwargs: object) -> FakeProc:  # noqa: N802
            calls.append(list(cmd))
            return FakeProc(returncode)

    namespace = base_namespace()
    if not real_subprocess:
        namespace["subprocess"] = _FakeSubprocess
    exec(  # noqa: S102
        compile(
            ast.Module(body=const_nodes(tree), type_ignores=[]),
            str(path),
            "exec",
        ),
        namespace,
    )
    namespace.update(extra_namespace or {})
    cls = ast.ClassDef(
        name="_Payload",
        bases=[],
        keywords=[],
        body=list(method_nodes),
        decorator_list=[],
    )
    module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    exec(compile(module, str(path), "exec"), namespace)  # noqa: S102

    inst = namespace["_Payload"]()
    inst.logger = types.SimpleNamespace(
        info=lambda *_a, **_k: None,
        debug=lambda *_a, **_k: None,
        error=lambda *_a, **_k: None,
    )
    inst._clean_after_error = lambda: None  # noqa: SLF001
    inst.aes_keyfile = "/keys/aes.key"
    # Binlog upload keeps the historical attribute name for the same key path.
    inst.xtrabackup_aes256 = "/keys/aes.key"
    inst.enc_aes = True
    inst.enc_gpg = False
    inst.compress = False
    inst.get_compression_ext = lambda: ""
    return inst, namespace["BackupError"], calls
