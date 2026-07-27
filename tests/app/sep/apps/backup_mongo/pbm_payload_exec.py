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

"""Share the ``subprocess.Popen`` stub and exec harness used to test PBM payloads.

The ``backup_mongo`` payload scripts are shipped by ``file://`` reference and read
directly from disk, so tests exercise the real production code by exec'ing the
script's source with ``subprocess.Popen`` stubbed out. This module is not itself a
test module (no ``test_`` prefix, so pytest never collects it); it just factors out
the ``FakePopen`` stub and the exec-and-cleanup steps that were duplicated across
``test_pbm_storage_apply.py``, ``test_pbm_compression_flags.py``, and the restore
payload normalization tests.
"""

import os
import pathlib
from collections.abc import Callable


class FakePopen:
    """Configurable stub for ``subprocess.Popen`` shared across PBM payload tests.

    Records every command it is constructed with (via the optional ``captured``
    out-list) and derives its ``poll()`` / ``communicate()`` results either from a
    fixed value or from a callable of the command, so a single stub can cover the
    success path, a rejected ``pbm config``, an unreadable ``pbm`` binary, and a
    malformed ``pbm config`` readback without a bespoke class per test module.
    """

    def __init__(
        self,
        cmd: list[str],
        *args: object,  # noqa: ARG002
        captured: list[list[str]] | None = None,
        returncode: int | Callable[[list[str]], int] = 0,
        communicate_result: (
            tuple[bytes, bytes] | Callable[[list[str]], tuple[bytes, bytes]]
        ) = (b"", b""),
        construction_error: Exception | None = None,
        **kwargs: object,  # noqa: ARG002
    ) -> None:
        """Record ``cmd`` and stash the behavior this instance should report.

        :param cmd: The command list the real code passed to ``Popen``.
        :param args: Ignored positional arguments accepted for call-site compatibility.
        :param captured: Out-list every constructed command is appended to. None skips
            recording (the command is still available via ``self.cmd`` if needed).
        :param returncode: The fixed exit code, or a callable of ``cmd`` returning one,
            reported by :meth:`poll`.
        :param communicate_result: The fixed ``(stdout, stderr)`` bytes pair, or a
            callable of ``cmd`` returning one, reported by :meth:`communicate`.
        :param construction_error: An exception to raise instead of constructing,
            simulating a ``pbm`` binary that cannot be run at all.
        :param kwargs: Ignored keyword arguments (e.g. ``stdout=subprocess.PIPE``)
            accepted for call-site compatibility.
        :raises Exception: ``construction_error``, when supplied.
        """
        if construction_error is not None:
            raise construction_error
        self.cmd = cmd
        self._returncode = returncode
        self._communicate_result = communicate_result
        if captured is not None:
            captured.append(cmd)

    def wait(self) -> None:
        """No-op, matching the real ``Popen.wait()`` call sites make."""
        return

    def poll(self) -> int:
        """Return the configured exit code (fixed or derived from ``self.cmd``).

        :return: The exit code the payload's ``proc.poll()`` call observes.
        """
        return self.returncode

    @property
    def returncode(self) -> int:
        """Return the configured exit code (fixed or derived from ``self.cmd``).

        Mirrors the real ``Popen.returncode`` attribute some payloads read
        directly (after ``wait()``/``communicate()``) instead of calling ``poll()``.

        :return: The exit code the payload's ``proc.returncode`` access observes.
        """
        if callable(self._returncode):
            return self._returncode(self.cmd)
        return self._returncode

    def communicate(self) -> tuple[bytes, bytes]:
        """Return the configured ``(stdout, stderr)`` pair.

        :return: The bytes pair the payload's ``proc.communicate()`` call observes.
        """
        if callable(self._communicate_result):
            return self._communicate_result(self.cmd)
        return self._communicate_result


def run_payload(path: pathlib.Path) -> dict[str, object]:
    """Exec a payload script's source and return the resulting namespace.

    Every payload calls its module-level ``pbm()`` unconditionally at the bottom of
    the file, which may raise ``SystemExit``; wrap the call in ``pytest.raises`` at
    the call site to assert on that. ``PBM_MONGODB_URI`` is always cleaned up
    afterward regardless of how execution ends, since the payload sets it directly
    in ``os.environ`` (outside ``monkeypatch``) and it would otherwise leak into
    later tests in the same process.

    :param path: The payload script path to exec.
    :return: The namespace populated by the payload's module-level execution
        (function definitions, module-level variables) up to wherever it stopped.
    """
    namespace: dict[str, object] = {}
    try:
        exec(compile(path.read_text(), str(path), "exec"), namespace)  # noqa: S102
    finally:
        os.environ.pop("PBM_MONGODB_URI", None)
    return namespace
