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

"""Merge forked Alembic revision heads within each branch, per track.

Groups each track's heads by the root revision they descend from and creates
one merge revision inside every group that has more than one head. Heads that
belong to different branches are never merged together, so a multi-branch
track such as ``sep`` stays at one head per root rather than collapsing to a
single chain.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.alembic_tracks import add_ini_argument, list_track_names  # noqa: E402

# A branch is forked when more than one head shares the same root.
_MIN_FORK_HEADS = 2


@dataclass(frozen=True)
class MergeAction:
    """Describe one merge revision that was (or would be) created.

    :param track: Alembic config section name.
    :param root: Branch root revision id the forked heads share.
    :param heads: Forked head revision ids that become the merge parents.
    :param message: Revision message passed to ``alembic.command.merge``.
    :param revision: New merge revision id, or ``None`` before creation.
    """

    track: str
    root: str
    heads: tuple[str, ...]
    message: str
    revision: str | None = None


class PartialMergeError(Exception):
    """Signal that some merge files were written before a later failure.

    :param cause: The exception that stopped the remaining merges.
    :param applied: Merge actions already written to disk.
    """

    def __init__(self, cause: BaseException, applied: tuple[MergeAction, ...]) -> None:
        self.cause = cause
        self.applied = applied
        super().__init__(str(cause))


def map_head_to_root(script: ScriptDirectory, head: str) -> str:
    """Return the root revision id that ``head`` descends from.

    Walks ancestors via ``iterate_revisions`` until the revision whose
    ``down_revision`` is ``None``.

    :param script: Loaded revision map for one track.
    :param head: Head revision id.
    :return: Root revision id.
    :raises ValueError: If no base revision is found for ``head``.
    """
    for rev in script.iterate_revisions(head, "base"):
        if rev.down_revision is None:
            return rev.revision
    msg = f"no root revision found for head {head!r}"
    raise ValueError(msg)


def group_heads_by_root(script: ScriptDirectory) -> dict[str, tuple[str, ...]]:
    """Group every head revision by the root it descends from.

    :param script: Loaded revision map for one track.
    :return: Mapping of root revision id to sorted head revision ids.
    """
    groups: dict[str, list[str]] = defaultdict(list)
    for head in script.get_heads():
        root = map_head_to_root(script, head)
        groups[root].append(head)
    return {root: tuple(sorted(heads)) for root, heads in groups.items()}


def _merge_message(track: str, heads: tuple[str, ...], script: ScriptDirectory) -> str:
    """Build a non-interactive merge message from the branch, when known.

    Prefer a single inherited branch label shared by the forked heads; fall
    back to the track name when heads carry no labels.

    :param track: Alembic config section name.
    :param heads: Forked head revision ids.
    :param script: Loaded revision map for the track.
    :return: Message string for ``alembic.command.merge``.
    """
    labels: set[str] = set()
    for head in heads:
        rev = script.get_revision(head)
        if rev.branch_labels:
            labels.update(rev.branch_labels)
    if len(labels) == 1:
        return f"merge {next(iter(labels))} migration heads"
    return f"merge {track} migration heads"


def plan_merges(ini_path: Path, track: str) -> tuple[MergeAction, ...]:
    """Return merge actions for every forked branch on ``track``.

    Groups with a single head are skipped (already converged). A new root
    revision that also introduces a new head is therefore not treated as a
    fork.

    :param ini_path: Path to ``alembic.ini``.
    :param track: Alembic config section name.
    :return: One ``MergeAction`` per forked branch, in root-id order.
    """
    cfg = Config(str(ini_path), ini_section=track)
    script = ScriptDirectory.from_config(cfg)
    actions: list[MergeAction] = []
    for root, heads in sorted(group_heads_by_root(script).items()):
        if len(heads) < _MIN_FORK_HEADS:
            continue
        actions.append(
            MergeAction(
                track=track,
                root=root,
                heads=heads,
                message=_merge_message(track, heads, script),
            )
        )
    return tuple(actions)


def apply_merges(
    ini_path: Path, actions: tuple[MergeAction, ...]
) -> tuple[MergeAction, ...]:
    """Create merge revision files for each planned action.

    :param ini_path: Path to ``alembic.ini``.
    :param actions: Planned merges from :func:`plan_merges`.
    :return: The same actions with ``revision`` filled in from Alembic.
    :raises ValueError: When a track section is misconfigured.
    :raises OSError: When writing a merge revision file fails.
    :raises CommandError: When Alembic rejects resolving or writing a merge.
    """
    applied: list[MergeAction] = []
    for action in actions:
        cfg = Config(str(ini_path), ini_section=action.track)
        script = command.merge(
            cfg,
            revisions=list(action.heads),
            message=action.message,
        )
        revision = script.revision if script is not None else None
        applied.append(
            MergeAction(
                track=action.track,
                root=action.root,
                heads=action.heads,
                message=action.message,
                revision=revision,
            )
        )
    return tuple(applied)


def _format_merge_line(action: MergeAction) -> str:
    """Format one merge action for stdout or stderr.

    :param action: A completed (or partially recorded) merge action.
    :return: A single human-readable line.
    """
    parents = ", ".join(action.heads)
    rev = action.revision or "?"
    return (
        f"Merged {action.track!r} branch rooted at {action.root}: "
        f"created {rev} from parents [{parents}] ({action.message!r})."
    )


def merge_forked_heads(
    ini_path: Path,
    tracks: tuple[str, ...] | None = None,
) -> tuple[MergeAction, ...]:
    """Merge forked heads on every track listed in ``ini_path``.

    A fork in one track does not prevent merges on the others: each track is
    planned and applied independently. Merges are applied one action at a
    time so that if a later action fails — including a second forked root on
    the same track — earlier merge files are still reported via
    :class:`PartialMergeError`.

    :param ini_path: Path to ``alembic.ini``.
    :param tracks: Track names to process; defaults to ``[alembic] databases``.
    :return: Every merge revision that was created.
    :raises PartialMergeError: When at least one merge file was written before
        a subsequent action failed.
    :raises ValueError: When the ini cannot be read or a track is misconfigured
        and no merge files have been written yet.
    :raises OSError: When a filesystem error occurs before any merge is written.
    :raises CommandError: When Alembic rejects a merge and nothing was applied
        yet.
    """
    if tracks is None:
        tracks = list_track_names(ini_path)
    applied: list[MergeAction] = []
    try:
        for track in tracks:
            for action in plan_merges(ini_path, track):
                # Apply one action at a time so a failure mid-track still
                # leaves earlier successful merges in ``applied``.
                applied.extend(apply_merges(ini_path, (action,)))
    except (ValueError, OSError, CommandError) as exc:
        if applied:
            raise PartialMergeError(exc, tuple(applied)) from exc
        raise
    return tuple(applied)


def main(argv: list[str] | None = None) -> int:
    """Merge forked Alembic heads per branch across every track.

    :param argv: CLI arguments (defaults to ``sys.argv[1:]``).
    :return: ``0`` on success (including when nothing needed merging);
        ``1`` when the ini cannot be read, a track is misconfigured, or
        merge generation fails (including after a partial write).
    """
    parser = argparse.ArgumentParser(description=__doc__)
    add_ini_argument(parser)
    args = parser.parse_args(argv)
    try:
        tracks = list_track_names(args.ini)
        applied = merge_forked_heads(args.ini, tracks=tracks)
    except PartialMergeError as exc:
        print(
            f"Error after creating {len(exc.applied)} merge revision(s); "
            f"working tree may contain new migration files: {exc.cause}",
            file=sys.stderr,
        )
        for action in exc.applied:
            print(_format_merge_line(action), file=sys.stderr)
        return 1
    except (ValueError, OSError, CommandError) as exc:
        print(exc, file=sys.stderr)
        return 1

    if not applied:
        names = ", ".join(tracks)
        print(f"No forked Alembic heads to merge for {names}.")
        return 0

    for action in applied:
        print(_format_merge_line(action))
    return 0


if __name__ == "__main__":
    sys.exit(main())
