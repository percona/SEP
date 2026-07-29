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

"""Sync the ``[sep] version_locations`` value in ``alembic.ini`` from disk.

Keeps a static ``version_locations`` line so bare ``alembic --name sep ...``
keeps working (``ScriptDirectory.from_config`` reads it before ``env.py``),
but regenerates the value from the migrations-first filesystem walk so new
apps under ``app/sep/apps/<name>/migrations/versions`` need no hand edit.

Run without arguments to rewrite in place; run with ``--check`` to fail
without writing when the committed value has drifted.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INI = REPO_ROOT / "alembic.ini"
DEFAULT_APPS_ROOT = REPO_ROOT / "app" / "sep" / "apps"
MAIN_VERSIONS_ENTRY = "%(here)s/app/sep/migrations/versions"

GENERATED_COMMENT = """\
# GENERATED — do not hand-edit. Rewritten by
# ``scripts/sync_alembic_version_locations.py`` from a deterministic
# filesystem walk of ``app/sep/apps/*/migrations/versions`` (main chain
# first, then plugin dirs sorted). Entries are joined with ``:``
# (matching ``version_path_separator = :`` above). Bare ``alembic``
# reads this before ``env.py``, so the list must stay here; regenerate
# via the sync script, pre-commit, or Make migration targets.
"""

_SECTION_HEADER = re.compile(r"^\[(?P<name>[^]]+)]\s*$")
_VERSION_LOCATIONS = re.compile(r"^version_locations\s*=")


def compute_version_locations(apps_root: Path) -> str:
    """Build the ``version_locations`` value for the ``[sep]`` section.

    :param apps_root: Directory of plugin packages to scan.
    :return: Colon-joined ``%(here)s/...`` entries, main chain first.
    """
    sys.path.insert(0, str(REPO_ROOT))
    from app.sep.migrations._discovery import discover_plugin_version_dirs

    entries = [MAIN_VERSIONS_ENTRY]
    for versions_dir in discover_plugin_version_dirs(apps_root):
        plugin_name = Path(versions_dir).parent.parent.name
        entries.append(f"%(here)s/app/sep/apps/{plugin_name}/migrations/versions")
    return ":".join(entries)


def _sep_section_bounds(lines: list[str]) -> tuple[int, int]:
    """Return ``(start, end)`` line indices for the ``[sep]`` section body.

    ``start`` is the first line after ``[sep]``; ``end`` is the index of the
    next section header (or ``len(lines)``).
    """
    sep_header: int | None = None
    for index, line in enumerate(lines):
        match = _SECTION_HEADER.match(line)
        if match is None:
            continue
        if match.group("name") == "sep":
            sep_header = index
            continue
        if sep_header is not None:
            return sep_header + 1, index
    if sep_header is None:
        msg = "alembic.ini has no [sep] section"
        raise ValueError(msg)
    return sep_header + 1, len(lines)


def _reject_multiline_version_locations(
    lines: list[str], assignment_idx: int, body_end: int
) -> None:
    """Require a single-line ``version_locations`` assignment.

    Raises ``ValueError`` if an indented ConfigParser continuation follows
    the assignment inside the ``[sep]`` section. Continuations are not
    rewritten, so leaving them would let a later sync falsely report
    the file as in sync.
    """
    for index in range(assignment_idx + 1, body_end):
        content = lines[index].rstrip("\r\n")
        # Mirror ConfigParser: blank lines and full-line comments are skipped
        # without ending the current option, so an indented line after them
        # is still a continuation.
        if content.strip() == "" or content[0] in "#;":
            continue
        if content[0].isspace():
            msg = (
                "[sep] version_locations must be a single line; "
                "indented continuation lines are not supported"
            )
            raise ValueError(msg)
        return


def render_sep_version_locations(text: str, value: str) -> str:
    """Return ``text`` with the ``[sep] version_locations`` block rewritten.

    Replaces the contiguous comment lines immediately above
    ``version_locations =`` (and that assignment line) inside ``[sep]``.
    Leaves every other section and line untouched. Re-emits the same
    line ending style present in ``text`` (``LF`` or ``CRLF``).
    Raises ``ValueError`` if the existing value uses indented continuations.

    :param text: Full ``alembic.ini`` contents with original line endings
        preserved (not universal-newline-normalized).
    :param value: The computed ``version_locations`` value.
    :return: Updated file contents.
    """
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    body_start, body_end = _sep_section_bounds(lines)

    assignment_idx: int | None = None
    for index in range(body_start, body_end):
        if _VERSION_LOCATIONS.match(lines[index]):
            assignment_idx = index
            break
    if assignment_idx is None:
        msg = "[sep] section has no version_locations assignment"
        raise ValueError(msg)
    _reject_multiline_version_locations(lines, assignment_idx, body_end)

    comment_start = assignment_idx
    while comment_start > body_start and lines[comment_start - 1].lstrip().startswith(
        "#"
    ):
        comment_start -= 1

    comment_block = GENERATED_COMMENT.replace("\n", newline)
    if not comment_block.endswith(newline):
        comment_block += newline
    assignment = f"version_locations = {value}{newline}"
    new_lines = (
        lines[:comment_start]
        + [comment_block, assignment]
        + lines[assignment_idx + 1 :]
    )
    # comment_block is a multi-line string inserted as one list element;
    # flatten so callers comparing line-oriented edits stay simple.
    return "".join(new_lines)


def sync_alembic_ini(
    ini_path: Path,
    apps_root: Path,
    *,
    check: bool = False,
) -> bool:
    """Rewrite or check ``ini_path`` against discovery.

    Preserves the file's existing line endings (``LF`` or ``CRLF``).
    Raises ``ValueError`` when ``version_locations`` spans multiple lines.

    :param ini_path: Path to ``alembic.ini``.
    :param apps_root: Plugin packages directory to scan.
    :param check: When true, report drift without writing.
    :return: ``True`` when the file already matched (or was rewritten);
        ``False`` when ``check`` found drift.
    """
    value = compute_version_locations(apps_root)
    # newline="" disables universal-newline translation so a CRLF file still
    # contains "\r\n" for render_sep_version_locations to detect and re-emit.
    with ini_path.open(encoding="utf-8", newline="") as handle:
        original = handle.read()
    updated = render_sep_version_locations(original, value)
    if original == updated:
        return True
    if check:
        return False
    with ini_path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(updated)
    return True


def main(argv: list[str] | None = None) -> int:
    """Sync or check ``[sep] version_locations`` in ``alembic.ini``.

    :param argv: CLI arguments (defaults to ``sys.argv[1:]``).
    :return: ``0`` on success / in sync; ``1`` when ``--check`` finds drift.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail without writing when version_locations has drifted",
    )
    parser.add_argument(
        "--ini",
        type=Path,
        default=DEFAULT_INI,
        help="path to alembic.ini (default: repo-root alembic.ini)",
    )
    parser.add_argument(
        "--apps-root",
        type=Path,
        default=DEFAULT_APPS_ROOT,
        help="plugin packages directory to scan",
    )
    args = parser.parse_args(argv)

    matched = sync_alembic_ini(args.ini, args.apps_root, check=args.check)
    if args.check:
        if not matched:
            print(
                f"{args.ini}: [sep] version_locations is out of date; "
                "regenerate with `python scripts/sync_alembic_version_locations.py`",
                file=sys.stderr,
            )
            return 1
        print(f"{args.ini}: [sep] version_locations is in sync.")
        return 0

    print(f"Synced [sep] version_locations in {args.ini}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
