#!/usr/bin/env python3
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

"""Regenerate the built-in snippets SHA-256 checksum manifest.

Walk ``snippets/``, hash every file except the manifest itself, and write
``snippets/builtin-snippets.sha256`` in ``sha256sum`` two-space format.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SNIPPETS_DIR = REPO_ROOT / "snippets"
MANIFEST_NAME = "builtin-snippets.sha256"
MANIFEST_PATH = SNIPPETS_DIR / MANIFEST_NAME
CHUNK_SIZE = 8192


def _sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file.

    :param path: The file to hash.
    :return: The hex-encoded SHA-256 digest of the file contents.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def generate_manifest() -> int:
    """Write the built-in snippets checksum manifest under ``snippets/``.

    Skip the manifest file itself. Raise ``SystemExit`` when ``snippets/`` is
    missing.

    :return: The number of snippet files hashed into the manifest.
    :raises SystemExit: If the snippets directory does not exist.
    :raises OSError: If a snippet file or the manifest cannot be read or written.
    """
    if not SNIPPETS_DIR.is_dir():
        raise SystemExit(f"Snippets directory not found: {SNIPPETS_DIR}")

    entries: list[tuple[str, str]] = []
    for path in sorted(SNIPPETS_DIR.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(SNIPPETS_DIR).as_posix()
        if relative == MANIFEST_NAME:
            continue
        entries.append((_sha256_file(path), relative))

    lines = [f"{digest}  {filename}\n" for digest, filename in entries]
    MANIFEST_PATH.write_text("".join(lines), encoding="utf-8")
    return len(entries)


def main() -> None:
    """Regenerate the checksum manifest and print how many files were hashed.

    :raises SystemExit: If the snippets directory is missing.
    :raises OSError: If a snippet file or the manifest cannot be read or written.
    """
    count = generate_manifest()
    print(f"Wrote {count} checksums to {MANIFEST_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
