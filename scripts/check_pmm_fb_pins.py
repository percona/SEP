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

"""Check that every feature-build pin in the sep-mysql compose file names one build."""

import argparse
import re
import sys
from pathlib import Path

import yaml

COMPOSE_PATH = (
    Path(__file__).resolve().parent.parent / "sidecar" / "pmm-fb" / "compose.yaml"
)

ARG_VALUE = "\\$\\{{{name}:-([^}}]*)\\}}"
"""A build arg's whole value: nothing but the expansion it is keyed by.

Two things are being pinned down, and both are matched rather than assumed. The
**name**, because a slot quietly rewired to another variable still agrees on
committed defaults while an exported ``PMM_FB_TAG`` moves only its siblings. And
the **whole value**, because ``prefix-${PMM_FB_TAG:-T}`` resolves to
``prefix-T`` at build time while a substring search reports ``T``: the literal
around the expansion is exactly what a reader comparing defaults would miss.

Reading the committed default is the other half: an ad-hoc repin can move any of
these from the environment, but what a fresh clone builds is what is written
here.
"""

IMAGE_TAG = ".*:\\$\\{{{name}:-([^}}]*)\\}}"
"""The image reference's tag token, likewise the expansion and nothing else.

Anchored through the end so ``pmm-server-fb:${PMM_FB_TAG:-T}-debug`` is refused
rather than read as ``T``.
"""

SERVER_IMAGE = "pmm-server image"
BUILD_TAG = "sep-mysql PMM_FB_TAG"
WITNESS = "sep-mysql NOMAD_VERSION_FB_TAG"

PRINTABLE = ("PMM_FB_TAG", "NOMAD_VERSION", "NOMAD_VERSION_FB_TAG")
"""Build args ``--print`` will resolve, for callers that read rather than parse."""


def committed_default(value: object, where: str, name: str, template: str) -> str:
    """Return the default baked into one ``${NAME:-default}`` compose value.

    :param value: The raw compose value. Typed loosely because YAML decides:
        a key written with no value arrives as ``None`` and a bare numeric tag
        as ``int``, and both have to reach the error below rather than a
        ``TypeError`` from the regex.
    :param where: Where it was read from, for the failure message.
    :param name: The variable this slot must interpolate.
    :param template: :data:`ARG_VALUE` or :data:`IMAGE_TAG`, whichever shape the
        slot is allowed to take.
    :return: The default the expansion falls back to.
    :raises SystemExit: When the value is not exactly that expansion, so a slot
        rewired to another variable, or carrying a literal beside it, stops the
        check rather than passing on a default that happens to match.
    """
    pattern = re.compile(template.format(name=re.escape(name)))
    match = pattern.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise SystemExit(
            f"ERROR: {where} is not exactly ${{{name}:-default}}: {value!r}"
        )
    return match.group(1)


def load_slots(compose_path: Path) -> tuple[object, dict]:
    """Return the ``pmm-server`` image and the ``sep-mysql`` build args.

    Separated from resolving any particular pin so ``--print`` can read one slot
    out of a compose file that does not carry the others, the base revision of a
    branch that has not yet gained the witness being the case that matters.

    :param compose_path: The compose file to read.
    :return: The raw image value and the raw build-arg mapping.
    :raises SystemExit: When the file is not this harness's compose file.
    """
    data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    try:
        services = data["services"]
        return services["pmm-server"]["image"], services["sep-mysql"]["build"]["args"]
    except (KeyError, TypeError) as exc:
        raise SystemExit(
            f"ERROR: {compose_path} is not the sep-mysql harness: {exc}"
        ) from None


def read_arg(args: dict, name: str) -> str:
    """Resolve one build arg's committed default.

    :param args: The raw build-arg mapping.
    :param name: The build arg to resolve.
    :return: Its committed default.
    :raises SystemExit: When the arg is absent, or is not exactly its expansion.
    """
    if name not in args:
        raise SystemExit(f"ERROR: sep-mysql declares no {name} build arg")
    return committed_default(args[name], f"sep-mysql {name}", name, ARG_VALUE)


def main(argv: list[str] | None = None) -> int:
    """Compare the three committed spellings of the feature-build tag.

    A repin has to move all of them: ``pmm-server``'s image and ``sep-mysql``'s
    ``PMM_FB_TAG`` because the client and server ship Nomad builds that must
    speak RPC to each other, and ``NOMAD_VERSION_FB_TAG`` because it is what the
    arm64 build's guard weighs ``PMM_FB_TAG`` against. A witness left behind
    would refuse every arm64 build from a fresh clone.

    :param argv: CLI arguments (defaults to ``sys.argv[1:]``).
    :return: 0 when the tags agree, 1 when they do not.
    :raises SystemExit: When the compose file cannot be read as this harness.
    """
    parser = argparse.ArgumentParser(
        description="Check that the sep-mysql feature-build pins name one build.",
    )
    parser.add_argument(
        "--print",
        dest="name",
        choices=PRINTABLE,
        help="Print one resolved build-arg default and exit, instead of checking.",
    )
    parser.add_argument(
        "compose",
        nargs="?",
        default=COMPOSE_PATH,
        type=Path,
        help=f"Compose file to read (default: {COMPOSE_PATH}).",
    )
    args = parser.parse_args(argv)

    image, build_args = load_slots(args.compose)

    if args.name:
        print(read_arg(build_args, args.name))
        return 0

    tags = {
        SERVER_IMAGE: committed_default(image, SERVER_IMAGE, "PMM_FB_TAG", IMAGE_TAG),
        BUILD_TAG: read_arg(build_args, "PMM_FB_TAG"),
        WITNESS: read_arg(build_args, "NOMAD_VERSION_FB_TAG"),
    }
    if len(set(tags.values())) > 1:
        print(
            "ERROR: the feature-build tag disagrees across the compose file:",
            file=sys.stderr,
        )
        for where, tag in tags.items():
            print(f"  {where}: {tag}", file=sys.stderr)
        print(
            "A repin moves all three together; see sidecar/pmm-fb/mysql-target.md.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
