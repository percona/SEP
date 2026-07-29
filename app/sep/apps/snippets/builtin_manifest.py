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

"""Hash snippet files, derive checksum-manifest keys, and load the manifest."""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

import aiofiles

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# Built-in snippet checksum manifest (sha256sum two-space format under SNIPPETS_DIR).
# Shared by the generator script and the in-app verifier so the name cannot drift.
BUILTIN_CHECKSUM_MANIFEST = "builtin-snippets.sha256"

_CHUNK_SIZE = 8192


async def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file.

    Read through ``aiofiles`` so async callers (snippet sync) do not block the
    event loop on disk I/O — the same pattern as ``Snippet.from_path``.

    :param path: The file to hash.
    :return: The hex-encoded SHA-256 digest of the file contents.
    :raises OSError: If the file cannot be opened or read.
    """
    digest = hashlib.sha256()
    async with aiofiles.open(path, "rb") as handle:
        while chunk := await handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_relative_path(path: Path, snippets_dir: Path) -> str:
    """Return the checksum-manifest key for a file under ``snippets_dir``.

    Use POSIX separators so generator and verifier keys match across platforms.

    :param path: A file path under ``snippets_dir``.
    :param snippets_dir: The snippets directory root.
    :return: ``path`` relative to ``snippets_dir`` with POSIX separators.
    :raises ValueError: If ``path`` is not located under ``snippets_dir``.
    """
    return path.relative_to(snippets_dir).as_posix()


async def load_builtin_checksum_manifest(snippets_dir: Path) -> dict[str, str]:
    """Load the built-in snippet checksum manifest from ``snippets_dir``.

    Parse ``sha256sum`` two-space lines into a mapping of relative filename to
    SHA-256 digest. Skip blank lines, comments, and malformed lines. Return an
    empty mapping when the manifest is missing, unreadable, or has no valid
    entries. Read through ``aiofiles`` so async callers do not block the event
    loop — the same pattern as ``Snippet.from_path``.

    :param snippets_dir: The snippets directory that may contain the manifest.
    :return: A mapping of relative snippet filename to SHA-256 hex digest.
    """
    manifest_path = snippets_dir / BUILTIN_CHECKSUM_MANIFEST
    try:
        async with aiofiles.open(manifest_path, encoding="utf-8") as handle:
            text = await handle.read()
    except OSError:
        logger.warning(
            "Built-in snippet checksum manifest unavailable at %s; "
            "skipping auto-approval",
            manifest_path,
        )
        return {}

    entries: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        digest, separator, filename = line.partition("  ")
        if not separator or not digest or not filename:
            logger.warning(
                "Ignoring malformed checksum manifest line %s in %s",
                line_number,
                manifest_path,
            )
            continue
        entries[filename] = digest
    return entries
