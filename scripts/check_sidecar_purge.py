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

"""Guard the side-car recipe's forced-purge layer and name the packages it removes.

The purge breaks debconf, so every ``apt``/``dpkg`` operation must precede it.
``--check-ordering`` asserts that; ``--print-packages`` makes the recipe the
single source of truth for which packages the CI presence check looks for.
"""

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTAINERFILE = PROJECT_ROOT / "sidecar" / "Containerfile.sidecar"

PURGE_MARKER = "dpkg --purge --force-remove-essential"

#: Program-name stems whose family breaks once debconf is gone. A token counts as
#: an invocation when its basename is one of these or begins with one plus a
#: hyphen, so ``apt-get``, ``apt-cache``, ``dpkg-query`` and ``dpkg-reconfigure``
#: are all covered, and matching the basename keeps ``/usr/bin/apt-get`` a hit
#: while leaving a path such as ``/etc/apt/apt.conf.d/99x`` alone.
PACKAGE_MANAGER_STEMS = ("apt", "dpkg")

#: Split an instruction body on whitespace and the shell operators that separate
#: commands, so an operator butted against a program name still isolates it.
_TOKEN_RE = re.compile(r"[^\s;&|()<>]+")


def parse_instructions(path: Path) -> list[tuple[int, str]]:
    """Return one ``(line_number, joined_body)`` pair per Dockerfile instruction.

    Comment lines are dropped and backslash continuations are folded into the
    instruction they belong to, so a comment naming ``apt`` or ``dpkg`` cannot be
    mistaken for an instruction and a continuation carrying one is still seen.
    The line number is where the instruction starts.

    :param path: Containerfile to parse.
    :return: ``(line_number, body)`` per instruction, in file order.
    """
    instructions: list[tuple[int, str]] = []
    start_line = 0
    parts: list[str] = []

    for lineno, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        stripped = raw.strip()
        if not parts and (not stripped or stripped.startswith("#")):
            continue
        if parts and stripped.startswith("#"):
            continue
        if not parts:
            start_line = lineno
        continued = stripped.endswith("\\")
        parts.append(stripped.removesuffix("\\").strip())
        if not continued:
            instructions.append((start_line, " ".join(p for p in parts if p)))
            parts = []

    if parts:
        instructions.append((start_line, " ".join(p for p in parts if p)))
    return instructions


def purge_index(instructions: list[tuple[int, str]]) -> int:
    """Return the index of the sole purge instruction.

    A missing or duplicated anchor is a hard failure: a check that silently
    passes when it cannot find what it guards is worse than no check.

    :param instructions: Parsed instructions from :func:`parse_instructions`.
    :return: Index of the purge instruction.
    :raises SystemExit: When the purge instruction is absent or appears twice.
    """
    matches = [i for i, (_, body) in enumerate(instructions) if PURGE_MARKER in body]
    if not matches:
        raise SystemExit(
            "No purge instruction found: expected an instruction containing "
            f"{PURGE_MARKER!r}."
        )
    if len(matches) > 1:
        lines = ", ".join(str(instructions[i][0]) for i in matches)
        raise SystemExit(
            f"Expected exactly one purge instruction, found {len(matches)} (lines {lines})."
        )
    return matches[0]


def purged_packages(instructions: list[tuple[int, str]]) -> list[str]:
    """Return the package names the purge instruction removes, in recipe order.

    :param instructions: Parsed instructions from :func:`parse_instructions`.
    :return: Package names following ``--force-remove-essential``.
    :raises SystemExit: When the purge instruction is absent or appears twice.
    """
    _, body = instructions[purge_index(instructions)]
    _, _, tail = body.partition("--force-remove-essential")
    return [token for token in tail.split() if not token.startswith("-")]


def _invokes_package_manager(body: str) -> bool:
    """Report whether ``body`` invokes a program from the apt or dpkg families.

    :param body: A joined instruction body.
    :return: ``True`` when a token's basename names a package-manager program.
    """
    for token in _TOKEN_RE.findall(body):
        name = token.rsplit("/", 1)[-1]
        if any(
            name == stem or name.startswith(f"{stem}-")
            for stem in PACKAGE_MANAGER_STEMS
        ):
            return True
    return False


def check_ordering(instructions: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Return the instructions after the purge that invoke a package manager.

    The scan starts strictly after the purge instruction, so the purge's own
    ``dpkg`` invocation never reports itself.

    :param instructions: Parsed instructions from :func:`parse_instructions`.
    :return: ``(line_number, body)`` per offending instruction.
    :raises SystemExit: When the purge instruction is absent or appears twice.
    """
    offenders: list[tuple[int, str]] = []
    for lineno, body in instructions[purge_index(instructions) + 1 :]:
        if _invokes_package_manager(body):
            offenders.append((lineno, body))
    return offenders


def main(argv: list[str] | None = None) -> int:
    """Run the ordering check, or print the purged package names.

    :param argv: CLI arguments (defaults to ``sys.argv[1:]``).
    :return: Process exit code.
    """
    parser = argparse.ArgumentParser(
        description="Check the side-car purge layer's ordering invariant.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--check-ordering",
        action="store_true",
        help="Fail if any apt/dpkg instruction follows the purge layer (the default).",
    )
    group.add_argument(
        "--print-packages",
        action="store_true",
        help="Print the purged package names, one per line.",
    )
    args = parser.parse_args(argv)

    instructions = parse_instructions(CONTAINERFILE)

    if args.print_packages:
        for package in purged_packages(instructions):
            print(package)
        return 0

    offenders = check_ordering(instructions)
    if offenders:
        rel = CONTAINERFILE.relative_to(PROJECT_ROOT)
        print(
            "ERROR: package-manager instruction(s) follow the forced-purge layer, "
            "which breaks debconf and leaves apt/dpkg unusable:"
        )
        for lineno, body in offenders:
            print(f"  {rel}:{lineno}: {body}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
