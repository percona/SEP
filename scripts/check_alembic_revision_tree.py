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

"""Fail when an Alembic track's revision tree has more heads than roots."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INI = REPO_ROOT / "alembic.ini"


@dataclass(frozen=True)
class TrackTree:
    """Hold root and head revision ids for one named Alembic config.

    :param name: Alembic config section name (a value from ``databases``).
    :param heads: Head revision ids from the loaded revision map.
    :param roots: Base revision ids (``down_revision`` of ``None``).
    """

    name: str
    heads: tuple[str, ...]
    roots: tuple[str, ...]

    @property
    def is_forked(self) -> bool:
        """Return whether head count exceeds root count.

        :return: ``True`` when the tree has more heads than roots.
        """
        return len(self.heads) > len(self.roots)


def list_track_names(ini_path: Path) -> tuple[str, ...]:
    """Return named Alembic configs listed in ``[alembic] databases``.

    :param ini_path: Path to ``alembic.ini``.
    :return: Track names in declaration order.
    :raises ValueError: If ``databases`` is missing or empty.
    """
    cfg = Config(str(ini_path))
    databases = cfg.get_main_option("databases") or ""
    names = tuple(part.strip() for part in databases.split(",") if part.strip())
    if not names:
        msg = f"{ini_path}: [alembic] databases is missing or empty"
        raise ValueError(msg)
    return names


def inspect_track(ini_path: Path, name: str) -> TrackTree:
    """Load one named config and read its revision-map roots and heads.

    :param ini_path: Path to ``alembic.ini``.
    :param name: Section name (a value from ``databases``).
    :return: The track's heads and roots.
    """
    cfg = Config(str(ini_path), ini_section=name)
    script = ScriptDirectory.from_config(cfg)
    return TrackTree(
        name=name,
        heads=tuple(script.get_heads()),
        roots=tuple(script.get_bases()),
    )


def inspect_revision_trees(ini_path: Path) -> tuple[TrackTree, ...]:
    """Inspect every named track in ``ini_path``.

    :param ini_path: Path to ``alembic.ini``.
    :return: One ``TrackTree`` per discovered track, in declaration order.
    """
    return tuple(inspect_track(ini_path, name) for name in list_track_names(ini_path))


def format_fork_error(tree: TrackTree) -> str:
    """Build the gate failure line for a forked track.

    :param tree: A track whose head count exceeds its root count.
    :return: A message naming the track and every head revision id.
    """
    heads = ", ".join(tree.heads)
    return (
        f"Alembic track {tree.name!r} has a forked revision tree: "
        f"{len(tree.heads)} heads exceed {len(tree.roots)} root(s). "
        f"Heads: {heads}."
    )


def main(argv: list[str] | None = None) -> int:
    """Check every Alembic track for a forked revision tree.

    :param argv: CLI arguments (defaults to ``sys.argv[1:]``).
    :return: ``0`` when every track is converged; ``1`` when any is forked
        or the ini cannot be read or a track section is misconfigured.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ini",
        type=Path,
        default=DEFAULT_INI,
        help="path to alembic.ini (default: repo-root alembic.ini). "
        "Must be run from the repository root so relative script_location "
        "paths in the ini resolve correctly.",
    )
    args = parser.parse_args(argv)
    try:
        trees = inspect_revision_trees(args.ini)
    except (ValueError, OSError, CommandError) as exc:
        print(exc, file=sys.stderr)
        return 1
    failed = [tree for tree in trees if tree.is_forked]
    if not failed:
        names = ", ".join(tree.name for tree in trees)
        print(f"Revision trees converged for {names}.")
        return 0
    print("Error: one or more Alembic revision trees are forked.", file=sys.stderr)
    for tree in failed:
        print(format_fork_error(tree), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
