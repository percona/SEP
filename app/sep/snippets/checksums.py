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

"""Hash snippet files and derive checksum-manifest keys.

Deliberately free of settings imports so the manifest generator script, which
runs from a pre-commit hook, can reuse these helpers without building the
snippets app. The sibling ``utils.py`` imports ``snippets_settings`` and the
app package's ``__init__`` constructs the app object, so neither is a home for
code the script needs.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import aiofiles

if TYPE_CHECKING:
    from pathlib import Path

# Built-in snippet checksum manifest (sha256sum two-space format under SNIPPETS_DIR).
# Shared by the generator script and the in-app verifier so the name cannot drift.
BUILTIN_CHECKSUM_MANIFEST = "builtin-snippets.sha256"

_CHUNK_SIZE = 8192


async def digest_file(
    path: Path, algorithm: str, *, usedforsecurity: bool = True
) -> str:
    """Return the hex digest of a file for the given hash algorithm.

    Read through ``aiofiles`` so hashing does not block the event loop on disk I/O.

    :param path: The file to hash.
    :param algorithm: A ``hashlib`` algorithm name, such as ``sha256`` or ``md5``.
    :param usedforsecurity: Whether the digest is used in a security context. Pass
        ``False`` for non-security digests such as the MD5 used to detect snippet
        file changes. Defaults to True.
    :return: The hex-encoded digest of the file contents.
    :raises OSError: If the file cannot be opened or read.
    :raises ValueError: If ``algorithm`` is not available in ``hashlib``.
    """
    digest = hashlib.new(algorithm, usedforsecurity=usedforsecurity)
    async with aiofiles.open(path, "rb") as handle:
        while chunk := await handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


async def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file.

    :param path: The file to hash.
    :return: The hex-encoded SHA-256 digest of the file contents.
    :raises OSError: If the file cannot be opened or read.
    """
    return await digest_file(path, "sha256")


def manifest_relative_path(path: Path, snippets_dir: Path) -> str:
    """Return the checksum-manifest key for a file under ``snippets_dir``.

    Use POSIX separators so generator and verifier keys match across platforms.

    :param path: A file path under ``snippets_dir``.
    :param snippets_dir: The snippets directory root.
    :return: ``path`` relative to ``snippets_dir`` with POSIX separators.
    :raises ValueError: If ``path`` is not located under ``snippets_dir``.
    """
    return path.relative_to(snippets_dir).as_posix()
