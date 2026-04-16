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

"""Manage changelog fragments for the SEP project.

Each PR with a user-facing change drops one or more small fragment files under
``changelog.d/`` instead of appending entries to ``CHANGELOG.md`` directly. This
avoids per-PR merge conflicts on the ``[Unreleased]`` section.

Subcommands:

- ``add``: create a new fragment file under ``changelog.d/``.
- ``check``: validate all fragments (filename, section, content).
- ``list``: render a CHANGELOG-style preview of all fragments.
- ``assemble``: move fragments for a Jira fix version into a new
  ``[vX.Y.Z]`` section of ``CHANGELOG.md`` and delete the consumed files.

Fragment filename: ``<TICKET>.<section>.md`` where ``section`` is one of
``added``, ``changed``, ``breaking``, ``config``, ``fixed``, ``security``.
Fragment content: one or more single-line entries; the assembler prepends
``- <TICKET>: `` to each line at render time.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

SECTION_MAP: dict[str, str] = {
    "added": "Added",
    "changed": "Changed",
    "breaking": "Breaking Changes",
    "config": "Configuration Changes",
    "fixed": "Fixed",
    "security": "Security",
}
SECTION_ORDER: list[str] = [
    "Added",
    "Changed",
    "Breaking Changes",
    "Configuration Changes",
    "Fixed",
    "Security",
]
VALID_SECTIONS: frozenset[str] = frozenset(SECTION_MAP)
FRAGMENT_RE: re.Pattern[str] = re.compile(
    r"^(SEP-\d+)\.(added|changed|breaking|config|fixed|security)\.md$",
)
TICKET_RE: re.Pattern[str] = re.compile(r"^SEP-(\d+)$")
UNRELEASED_COMPARE_RE: re.Pattern[str] = re.compile(
    r"^\[Unreleased\]: (?P<url>https://github\.com/percona/SEP/compare/"
    r"v(?P<previous>[\w.\-]+)\.\.\.HEAD)$",
)
RESERVED_FILENAMES: frozenset[str] = frozenset({"README.md", ".gitkeep"})
CHANGELOG_D: Path = Path("changelog.d")
CHANGELOG_MD: Path = Path("CHANGELOG.md")
REPO_COMPARE_URL: str = "https://github.com/percona/SEP/compare"


class FragmentError(Exception):
    """Indicate an invalid changelog fragment or CHANGELOG.md state."""


def _ticket_sort_key(ticket: str) -> int:
    """Return the numeric sort key for a ticket like ``SEP-503``.

    :param ticket: The ticket key.
    :type ticket: str
    :return: The integer portion of the ticket key.
    :rtype: int
    """
    match = TICKET_RE.match(ticket)
    if match is None:
        raise FragmentError(f"invalid ticket key: {ticket}")
    return int(match.group(1))


def load_fragments(
    changelog_d: Path = CHANGELOG_D,
) -> dict[str, list[tuple[str, list[str], Path]]]:
    """Load and validate all fragments under ``changelog_d``.

    :param changelog_d: The fragments directory.
    :type changelog_d: Path
    :return: A mapping of display section name to ``(ticket, lines, path)``
        triples sorted by numeric ticket ID.
    :rtype: dict[str, list[tuple[str, list[str], Path]]]
    :raises FragmentError: If any fragment has an invalid filename, an unknown
        section, or empty/malformed content.
    """
    grouped = defaultdict(list)
    errors = []
    if not changelog_d.exists():
        return {}
    for path in sorted(changelog_d.iterdir()):
        if path.name in RESERVED_FILENAMES or not path.is_file():
            continue
        match = FRAGMENT_RE.match(path.name)
        if match is None:
            errors.append(
                f"{path.name}: invalid filename (expected "
                f"``SEP-<n>.<section>.md`` where section is one of "
                f"{', '.join(sorted(VALID_SECTIONS))})",
            )
            continue
        ticket = match.group(1)
        section_display = SECTION_MAP[match.group(2)]
        raw = path.read_text(encoding="utf-8")
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if not lines:
            errors.append(f"{path.name}: file is empty")
            continue
        bad_prefix = next((line for line in lines if line.startswith("- ")), None)
        if bad_prefix is not None:
            errors.append(
                f"{path.name}: content must not start with ``- `` (the bullet "
                "and ``SEP-XXX:`` prefix are added at assembly time)",
            )
            continue
        grouped[section_display].append((ticket, lines, path))

    if errors:
        raise FragmentError("\n".join(errors))

    for section_display in grouped:
        grouped[section_display].sort(key=lambda item: _ticket_sort_key(item[0]))

    return dict(grouped)


def render_section_body(
    grouped: dict[str, list[tuple[str, list[str], Path]]],
) -> str:
    """Render the grouped fragments as a CHANGELOG ``[vX.Y.Z]``-style block body.

    :param grouped: The output of :func:`load_fragments`, optionally filtered.
    :type grouped: dict[str, list[tuple[str, list[str], Path]]]
    :return: The rendered body with ``### Section`` subheaders and
        ``- SEP-XXX: ...`` bullets, separated by blank lines, with a trailing
        newline.
    :rtype: str
    """
    blocks = []
    for section_display in SECTION_ORDER:
        entries = grouped.get(section_display)
        if not entries:
            continue
        lines = [f"### {section_display}", ""]
        lines.extend(
            f"- {ticket}: {line}"
            for ticket, entry_lines, _ in entries
            for line in entry_lines
        )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n" if blocks else ""


def _parse_tickets(tickets_csv: str) -> set[str]:
    """Parse a comma-separated list of ticket keys into a set.

    :param tickets_csv: The raw CSV string from ``--tickets``.
    :type tickets_csv: str
    :return: The set of trimmed, non-empty ticket keys.
    :rtype: set[str]
    """
    return {t.strip() for t in tickets_csv.split(",") if t.strip()}


def _filter_by_tickets(
    grouped: dict[str, list[tuple[str, list[str], Path]]],
    tickets: set[str],
) -> dict[str, list[tuple[str, list[str], Path]]]:
    """Return a new grouping limited to entries whose ticket is in ``tickets``.

    :param grouped: The full grouped fragments.
    :type grouped: dict[str, list[tuple[str, list[str], Path]]]
    :param tickets: The set of ticket keys to keep.
    :type tickets: set[str]
    :return: The filtered grouping.
    :rtype: dict[str, list[tuple[str, list[str], Path]]]
    """
    filtered = {}
    for section_display, entries in grouped.items():
        kept = [entry for entry in entries if entry[0] in tickets]
        if kept:
            filtered[section_display] = kept
    return filtered


def _splice_version_section(
    changelog_text: str,
    version: str,
    date: str,
    body: str,
) -> str:
    """Insert a new ``## [vX.Y.Z] - YYYY-MM-DD`` block after ``## [Unreleased]``.

    :param changelog_text: The current ``CHANGELOG.md`` contents.
    :type changelog_text: str
    :param version: The new version (without the ``v`` prefix).
    :type version: str
    :param date: The release date in ``YYYY-MM-DD``.
    :type date: str
    :param body: The rendered section body from :func:`render_section_body`.
    :type body: str
    :return: The updated ``CHANGELOG.md`` contents.
    :rtype: str
    :raises FragmentError: If the ``[Unreleased]`` heading or a following
        ``[vX.Y.Z]`` heading cannot be located.
    """
    lines = changelog_text.splitlines()
    try:
        unreleased_idx = lines.index("## [Unreleased]")
    except ValueError as exc:
        raise FragmentError(
            "CHANGELOG.md: missing ``## [Unreleased]`` heading",
        ) from exc
    next_version_idx = None
    for idx in range(unreleased_idx + 1, len(lines)):
        if lines[idx].startswith("## [v"):
            next_version_idx = idx
            break
    if next_version_idx is None:
        raise FragmentError(
            "CHANGELOG.md: no existing ``## [v...]`` section found after [Unreleased]",
        )
    new_block = [f"## [v{version}] - {date}", ""]
    new_block.extend(body.rstrip().splitlines())
    new_block.append("")
    new_lines = lines[:next_version_idx] + new_block + lines[next_version_idx:]
    # preserve the file's original trailing newline, if any
    suffix = "\n" if changelog_text.endswith("\n") else ""
    return "\n".join(new_lines) + suffix


def _update_compare_links(changelog_text: str, version: str) -> str:
    """Rewrite the ``[Unreleased]`` compare link and insert a new ``[vX.Y.Z]`` link.

    :param changelog_text: The current ``CHANGELOG.md`` contents.
    :type changelog_text: str
    :param version: The new version (without the ``v`` prefix).
    :type version: str
    :return: The updated ``CHANGELOG.md`` contents.
    :rtype: str
    :raises FragmentError: If the ``[Unreleased]`` compare link is missing.
    """
    lines = changelog_text.splitlines()
    for idx, line in enumerate(lines):
        match = UNRELEASED_COMPARE_RE.match(line)
        if match is None:
            continue
        previous = match.group("previous")
        lines[idx] = f"[Unreleased]: {REPO_COMPARE_URL}/v{version}...HEAD"
        new_link = f"[v{version}]: {REPO_COMPARE_URL}/v{previous}...v{version}"
        lines.insert(idx + 1, new_link)
        suffix = "\n" if changelog_text.endswith("\n") else ""
        return "\n".join(lines) + suffix
    raise FragmentError("CHANGELOG.md: missing ``[Unreleased]`` compare link")


def cmd_add(ticket: str, section: str, message: str, *, force: bool) -> int:
    """Handle the ``add`` subcommand.

    :param ticket: The ticket key, e.g. ``SEP-503``.
    :type ticket: str
    :param section: The short section name, e.g. ``added``.
    :type section: str
    :param message: The single-line description for the fragment.
    :type message: str
    :param force: Overwrite an existing fragment when ``True``.
    :type force: bool
    :return: Process exit code (``0`` on success, ``1`` on error).
    :rtype: int
    """
    ticket = ticket.strip()
    section = section.strip().lower()
    message = message.strip()

    if TICKET_RE.match(ticket) is None:
        print(
            f"error: invalid ticket key {ticket!r} (expected ``SEP-<n>``)",
            file=sys.stderr,
        )
        return 1
    if section not in VALID_SECTIONS:
        print(
            f"error: invalid section {section!r} (expected one of "
            f"{', '.join(sorted(VALID_SECTIONS))})",
            file=sys.stderr,
        )
        return 1
    if not message:
        print("error: message is empty", file=sys.stderr)
        return 1
    if "\n" in message:
        print("error: message must be a single line", file=sys.stderr)
        return 1

    CHANGELOG_D.mkdir(exist_ok=True)
    fragment_path = CHANGELOG_D / f"{ticket}.{section}.md"
    if fragment_path.exists() and not force:
        print(
            f"error: {fragment_path} already exists (use --force to overwrite "
            "or edit the file directly to add more entries)",
            file=sys.stderr,
        )
        return 1
    fragment_path.write_text(message + "\n", encoding="utf-8")
    print(f"Created {fragment_path}")
    return 0


def cmd_check() -> int:
    """Handle the ``check`` subcommand.

    :return: ``0`` if all fragments are valid, ``1`` otherwise.
    :rtype: int
    """
    try:
        load_fragments()
    except FragmentError as exc:
        print("error: invalid changelog fragments:", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1
    print(f"OK: {CHANGELOG_D}/ fragments pass all checks")
    return 0


def cmd_list() -> int:
    """Handle the ``list`` subcommand.

    :return: ``0`` on success, ``1`` if fragments are invalid.
    :rtype: int
    """
    try:
        grouped = load_fragments()
    except FragmentError as exc:
        print("error: invalid changelog fragments:", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1
    body = render_section_body(grouped)
    if not body:
        print(f"(no fragments under {CHANGELOG_D}/)")
        return 0
    sys.stdout.write(body)
    return 0


def _prepare_assemble(
    version: str,
    tickets_csv: str,
) -> tuple[
    dict[str, list[tuple[str, list[str], Path]]],
    dict[str, list[tuple[str, list[str], Path]]],
    str,
]:
    """Validate inputs and return the data needed by :func:`cmd_assemble`.

    :param version: The release version (without the ``v`` prefix).
    :type version: str
    :param tickets_csv: Comma-separated ticket keys that belong to this release.
    :type tickets_csv: str
    :return: A tuple of ``(grouped, filtered, original_changelog_text)``.
    :rtype: tuple[dict[str, list[tuple[str, list[str], Path]]], dict[str, list[tuple[str, list[str], Path]]], str]
    :raises FragmentError: If ``--tickets`` is empty, no fragments match,
        ``CHANGELOG.md`` is missing, or ``CHANGELOG.md`` already contains a
        ``## [v<version>]`` section or a ``[v<version>]:`` compare link.
    """
    tickets = _parse_tickets(tickets_csv)
    if not tickets:
        msg = "--tickets is empty"
        raise FragmentError(msg)
    grouped = load_fragments()
    filtered = _filter_by_tickets(grouped, tickets)
    if not filtered:
        msg = f"none of the given tickets have fragments under {CHANGELOG_D}/"
        raise FragmentError(msg)
    if not CHANGELOG_MD.exists():
        msg = f"{CHANGELOG_MD} does not exist"
        raise FragmentError(msg)
    changelog_text = CHANGELOG_MD.read_text(encoding="utf-8")
    version_heading = f"## [v{version}]"
    version_link_prefix = f"[v{version}]:"
    for line in changelog_text.splitlines():
        if line.startswith(version_heading):
            msg = f"{CHANGELOG_MD} already contains a ``## [v{version}]`` section"
            raise FragmentError(msg)
        if line.startswith(version_link_prefix):
            msg = f"{CHANGELOG_MD} already contains a ``[v{version}]:`` compare link"
            raise FragmentError(msg)
    return grouped, filtered, changelog_text


def cmd_assemble(
    version: str,
    date: str,
    tickets_csv: str,
    *,
    dry_run: bool,
) -> int:
    """Handle the ``assemble`` subcommand.

    :param version: The release version (without the ``v`` prefix).
    :type version: str
    :param date: The release date in ``YYYY-MM-DD``.
    :type date: str
    :param tickets_csv: Comma-separated ticket keys that belong to this release.
    :type tickets_csv: str
    :param dry_run: If ``True``, print the rendered block but do not modify files.
    :type dry_run: bool
    :return: ``0`` on success, ``1`` on error.
    :rtype: int
    """
    try:
        grouped, filtered, original = _prepare_assemble(version, tickets_csv)
        body = render_section_body(filtered)
        with_section = _splice_version_section(original, version, date, body)
        with_links = _update_compare_links(with_section, version)
    except FragmentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    consumed_paths = [entry[2] for entries in filtered.values() for entry in entries]

    if dry_run:
        print(f"=== would insert section [v{version}] - {date} ===")
        sys.stdout.write(body)
        print("=== would delete fragment files ===")
        for path in consumed_paths:
            print(f"  - {path}")
        return 0

    CHANGELOG_MD.write_text(with_links, encoding="utf-8")
    for path in consumed_paths:
        path.unlink()
    kept = sum(len(entries) for entries in grouped.values()) - len(consumed_paths)
    print(
        f"Inserted [v{version}] section with "
        f"{len(consumed_paths)} fragment file(s), {kept} fragment(s) remaining.",
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the CLI.

    :return: The top-level parser with all subcommands registered.
    :rtype: argparse.ArgumentParser
    """
    parser = argparse.ArgumentParser(
        prog="changelog",
        description="Manage SEP changelog fragments under changelog.d/.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser(
        "add",
        help="Create a new changelog fragment.",
    )
    add_parser.add_argument("--ticket", required=True, help="Ticket key, e.g. SEP-503.")
    add_parser.add_argument(
        "--section",
        required=True,
        choices=sorted(VALID_SECTIONS),
        help="Section: added, changed, breaking, config, fixed, security.",
    )
    add_parser.add_argument(
        "--message",
        required=True,
        help="Single-line description (no leading ``- SEP-XXX:`` prefix).",
    )
    add_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing fragment.",
    )

    subparsers.add_parser("check", help="Validate all fragments.")
    subparsers.add_parser("list", help="Print a CHANGELOG-style preview of fragments.")

    assemble_parser = subparsers.add_parser(
        "assemble",
        help="Assemble fragments into a new CHANGELOG.md version section.",
    )
    assemble_parser.add_argument("--version", required=True, help="X.Y.Z")
    assemble_parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    assemble_parser.add_argument(
        "--tickets",
        required=True,
        help="Comma-separated ticket keys in the Jira fix version.",
    )
    assemble_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the rendered section and list consumed fragments without writing.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entrypoint for the CLI.

    :param argv: Optional argv override for testing.
    :type argv: list[str] | None
    :return: Process exit code.
    :rtype: int
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "add":
        return cmd_add(args.ticket, args.section, args.message, force=args.force)
    if args.command == "check":
        return cmd_check()
    if args.command == "list":
        return cmd_list()
    return cmd_assemble(
        args.version,
        args.date,
        args.tickets,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
