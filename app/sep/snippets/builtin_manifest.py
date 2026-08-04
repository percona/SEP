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

"""Load the built-in snippet checksum manifest."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import aiofiles

from app.sep.snippets.checksums import BUILTIN_CHECKSUM_MANIFEST

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["load_builtin_checksum_manifest"]

logger = logging.getLogger(__name__)


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
