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

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTAINERFILE = REPO_ROOT / "sidecar" / "Containerfile.sidecar"

PURGE_FLAG = "--force-remove-essential"
PURGE_MARKER = f"dpkg --purge {PURGE_FLAG}"

#: Program-name stems whose family breaks once debconf is gone. A token counts as
#: an invocation when its name is one of these or begins with one plus a hyphen,
#: so ``apt-get``, ``apt-cache``, ``dpkg-query`` and ``dpkg-reconfigure`` are all
#: covered. Which tokens are eligible at all is decided by ``_BIN_DIRS`` below.
PACKAGE_MANAGER_STEMS = ("apt", "dpkg")

#: Split an instruction body on whitespace, the shell operators that separate
#: commands, and the quoting and bracket punctuation of Dockerfile exec form, so
#: an operator butted against a program name still isolates it and
#: ``RUN ["apt-get", "update"]`` yields a bare ``apt-get``.
_TOKEN_RE = re.compile(r"[^\s;&|()<>\[\],\"'`]+")

#: Directories a package-manager binary is invoked from. A token carrying a path
#: names an invocation only when it lives in one, which keeps ``/usr/bin/apt-get``
#: a hit while leaving data paths such as ``/var/lib/apt`` and ``/etc/apt`` alone.
_BIN_DIRS = frozenset(
    {"/bin", "/sbin", "/usr/bin", "/usr/sbin", "/usr/local/bin", "/usr/local/sbin"}
)

#: A Debian package name is lowercase alphanumerics plus ``+``, ``-`` and ``.``,
#: opening on an alphanumeric. Anything else in the purge tail means the
#: instruction is not a bare dpkg invocation, so its tail is not a package list.
_PACKAGE_NAME_RE = re.compile(r"[a-z0-9][a-z0-9+.-]+")


def parse_instructions(path: Path) -> list[tuple[int, str]]:
    """Return one ``(line_number, joined_body)`` pair per Dockerfile instruction.

    Blank and comment lines are dropped wherever they fall, and backslash
    continuations are folded into the instruction they belong to, so a comment
    naming ``apt`` or ``dpkg`` cannot be mistaken for an instruction, a blank line
    cannot cut a continuation short, and a continuation carrying either is still
    seen whole. The line number is where the instruction starts.

    :param path: Containerfile to parse.
    :return: ``(line_number, body)`` per instruction, in file order.
    :raises SystemExit: When ``path`` does not exist.
    """
    if not path.is_file():
        raise SystemExit(
            f"No Containerfile at {path}. Run this from a checkout where "
            "sidecar/Containerfile.sidecar exists."
        )

    instructions: list[tuple[int, str]] = []
    start_line = 0
    parts: list[str] = []

    for lineno, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
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
    :raises SystemExit: When the purge instruction is absent or appears more
        than once.
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

    Every remaining token must look like a package name. Chaining a second
    command onto the purge would otherwise put shell words in this list, and the
    CI presence check reads it as the set of packages to look for.

    :param instructions: Parsed instructions from :func:`parse_instructions`.
    :return: Package names following ``--force-remove-essential``.
    :raises SystemExit: When the purge instruction is absent, appears more than
        once, or carries a tail that is not a bare package list.
    """
    lineno, body = instructions[purge_index(instructions)]
    _, _, tail = body.partition(PURGE_FLAG)
    names = [token for token in tail.split() if not token.startswith("-")]
    unexpected = [name for name in names if not _PACKAGE_NAME_RE.fullmatch(name)]
    if unexpected:
        raise SystemExit(
            f"Purge instruction at line {lineno} lists non-package tokens "
            f"{unexpected}. Keep it a bare dpkg invocation, so the package list "
            "it names stays the one the presence check looks for."
        )
    return names


def _invokes_package_manager(body: str) -> bool:
    """Report whether ``body`` invokes a program from the apt or dpkg families.

    :param body: A joined instruction body.
    :return: ``True`` when a token names a package-manager program.
    """
    for token in _TOKEN_RE.findall(body):
        parent, separator, name = token.rpartition("/")
        if separator and parent not in _BIN_DIRS:
            continue
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
    :raises SystemExit: When the purge instruction is absent or appears more
        than once.
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
    :raises SystemExit: When the Containerfile is absent, or its purge
        instruction is missing or duplicated.
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
        rel = CONTAINERFILE.relative_to(REPO_ROOT)
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
