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

"""Ensure Nomad dispatch payloads stay under the 16 KiB limit after minify+gzip."""

import gzip
import io
import sys

from python_minifier import minify

NOMAD_PAYLOAD_SIZE_LIMIT = 16384


def check_payload(path: str) -> tuple[str, int] | None:
    """Minify and gzip a Python file, returning ``(path, size)`` if it exceeds the Nomad limit.

    The source is minified with ``python_minifier`` (falling back to the
    original text on ``SyntaxError``) then gzip-compressed.  If the
    compressed size is within :data:`NOMAD_PAYLOAD_SIZE_LIMIT`, returns
    ``None``; otherwise returns the path and offending size in bytes.
    """
    with open(path, encoding="utf-8") as f:
        src = f.read()
    try:
        src = minify(
            src,
            remove_annotations=True,
            remove_pass=True,
            remove_literal_statements=True,
            combine_imports=True,
            hoist_literals=True,
            rename_locals=True,
            rename_globals=True,
            remove_object_base=True,
            remove_asserts=True,
            remove_debug=True,
            remove_explicit_return_none=True,
            remove_builtin_exception_brackets=True,
        )
    except SyntaxError:
        pass
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(src.encode("utf-8"))
    sz = len(buf.getvalue())
    if sz > NOMAD_PAYLOAD_SIZE_LIMIT:
        return (path, sz)
    return None


def main() -> int:
    """Check every file path passed as a CLI argument against the Nomad payload limit.

    Returns 0 when all payloads are within the limit, or 1 after printing
    a summary of the offending files.
    """
    failed = []
    for path in sys.argv[1:]:
        result = check_payload(path)
        if result is not None:
            failed.append(result)
    if failed:
        print("ERROR: Payload(s) exceed Nomad 16 KiB dispatch limit:")
        for p, sz in failed:
            print(f"  {p}: {sz:,} bytes (limit: {NOMAD_PAYLOAD_SIZE_LIMIT:,})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
