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

"""Sync the canonical PBM creds preamble into each backup_mongo payload.

Payloads are shipped by ``file://`` and can't import shared code, so this
rewrites the block between each payload's ``# --- BEGIN/END GENERATED PBM CREDS
PREAMBLE ---`` markers with the canonical region from
``app/sep/apps/framework/pbm_creds_common.py``. Any file under the search root
carrying the BEGIN marker opts in; markerless files (e.g. ``pbm_snapshot_payload``)
are left untouched.

Run without arguments to rewrite in place; run with ``--check`` (the CI guard) to
fail without writing when a payload has drifted.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEARCH_ROOT = REPO_ROOT / "app" / "sep" / "apps" / "backup_mongo"
CANONICAL_SOURCE = (
    REPO_ROOT / "app" / "sep" / "apps" / "framework" / "pbm_creds_common.py"
)


def find_payloads(search_root: Path, begin_marker: str) -> list[Path]:
    """Return the payload files that opt into the shared preamble via the marker.

    A file opts in by carrying ``begin_marker`` as a full line (not merely as a
    substring, so the marker-defining constants in the canonical source do not
    match). The canonical source itself is skipped.

    :param search_root: The directory tree scanned for opted-in payloads.
    :type search_root: Path
    :param begin_marker: The BEGIN marker line a payload must contain.
    :type begin_marker: str
    :return: The opted-in payload paths, sorted for deterministic output.
    :rtype: list[Path]
    """
    found = []
    for path in sorted(search_root.rglob("*")):
        if not path.is_file() or path.resolve() == CANONICAL_SOURCE.resolve():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        if begin_marker in lines:
            found.append(path)
    return found


def render(text: str, region: str, begin_marker: str, end_marker: str) -> str:
    """Return ``text`` with its marked region replaced by ``region``.

    Splitting on the newline character (rather than :meth:`str.splitlines`)
    preserves the file's trailing newline through the round-trip.

    :param text: The payload's current source text.
    :type text: str
    :param region: The canonical preamble body to place between the markers.
    :type region: str
    :param begin_marker: The BEGIN marker line.
    :type begin_marker: str
    :param end_marker: The END marker line.
    :type end_marker: str
    :return: The rewritten payload source.
    :rtype: str
    :raises ValueError: When either marker line is absent or out of order.
    """
    lines = text.split("\n")
    try:
        begin = lines.index(begin_marker)
        end = lines.index(end_marker, begin + 1)
    except ValueError as exc:
        raise ValueError("payload is missing a PBM CREDS PREAMBLE marker line") from exc
    rebuilt = (
        lines[:begin]
        + [begin_marker, *region.split("\n"), end_marker]
        + lines[end + 1 :]
    )
    return "\n".join(rebuilt)


def main(argv: list[str] | None = None) -> int:
    """Rewrite or check the payload preambles against the canonical region.

    :param argv: The CLI arguments (defaults to ``sys.argv``).
    :type argv: list[str] | None
    :return: ``0`` when every payload is in sync (or was rewritten); ``1`` when
        ``--check`` finds drift or no opted-in payload exists.
    :rtype: int
    """
    sys.path.insert(0, str(REPO_ROOT))
    from app.sep.apps.framework.pbm_creds_common import (
        PREAMBLE_BEGIN,
        PREAMBLE_END,
        preamble_source,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail without writing when any payload has drifted from the canonical region",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_SEARCH_ROOT,
        help="directory tree scanned for opted-in payloads (default: the backup_mongo app)",
    )
    args = parser.parse_args(argv)

    region = preamble_source()
    payloads = find_payloads(args.root, PREAMBLE_BEGIN)
    if not payloads:
        print(
            f"No payloads carry a PBM CREDS PREAMBLE marker under {args.root}",
            file=sys.stderr,
        )
        return 1

    drift = []
    rewritten = []
    for path in payloads:
        rel = path.relative_to(REPO_ROOT)
        current = path.read_text(encoding="utf-8")
        updated = render(current, region, PREAMBLE_BEGIN, PREAMBLE_END)
        if updated == current:
            print(f"unchanged  {rel}")
            continue
        if args.check:
            drift.append(path)
            print(f"drifted    {rel}")
        else:
            path.write_text(updated, encoding="utf-8")
            rewritten.append(path)
            print(f"rewrote    {rel}")

    if args.check:
        if drift:
            rels = [str(path.relative_to(REPO_ROOT)) for path in drift]
            print(
                f"PBM creds preamble drift: {rels}; regenerate with "
                "`python scripts/gen_pbm_payloads.py`",
                file=sys.stderr,
            )
            return 1
        print(
            f"All {len(payloads)} PBM payloads are in sync with the canonical region."
        )
        return 0

    print(
        f"Synced {len(payloads)} PBM payloads: "
        f"{len(rewritten)} rewritten, {len(payloads) - len(rewritten)} already in sync."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
