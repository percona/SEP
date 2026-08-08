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

"""Sync the generated ``app:<name>`` block in ``.github/labeler.yml`` from disk.

``actions/labeler`` has no templated label names, so every ``app:<name>`` rule
must be enumerated explicitly. Hand-maintaining 15 entries means a newly added
app silently gets no label, so this script regenerates the block from a
deterministic filesystem walk of ``app/sep/apps/*`` (mirroring
``scripts/sync_alembic_version_locations.py``).

An app slice is the full-stack vertical for one app: ``app/sep/apps/<name>/``,
``frontend/packages/apps/<name>/``, ``tests/app/sep/apps/<name>/``,
``templates/<name>/``, and ``frontend/packages/e2e/tests/<name>*.spec.ts``. Only
surfaces that exist on disk are emitted. Three name mismatches are resolved by
explicit alias maps that are asserted against disk, so a stale alias fails the
``--check`` mode instead of silently emitting a dead glob.

Run without arguments to rewrite in place; run with ``--check`` to fail
without writing when the committed block has drifted.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LABELER = REPO_ROOT / ".github" / "labeler.yml"
APPS_SUBDIR = ("app", "sep", "apps")

#: Directories under ``app/sep/apps`` that are framework internals, not apps.
EXCLUDED_APPS = frozenset({"framework", "shared"})

#: App name -> ``templates/<dir>`` name, where the template directory that backs
#: the app does not share its name. Asserted against disk by ``--check``.
TEMPLATE_ALIASES = {"archives": "archiver"}

#: App name -> e2e spec stem, where the Playwright spec uses hyphens while the
#: app directory uses underscores. Asserted against disk by ``--check``.
E2E_ALIASES = {
    "alert_troubleshooting": "alert-troubleshooting",
    "mysql_backups": "mysql-backups",
}

BEGIN_MARKER = "# BEGIN generated app labels — managed by scripts/sync_labeler_apps.py"
END_MARKER = "# END generated app labels"
_REGEN_HINT = (
    "# Regenerate with `python scripts/sync_labeler_apps.py`; `--check` fails on drift."
)


def discover_apps(apps_root: Path) -> list[str]:
    """Return the sorted app-slice names found under ``apps_root``.

    :param apps_root: The ``app/sep/apps`` directory to scan.
    :return: Sorted directory names, excluding framework internals and
        dunder/cache directories.
    """
    names = [
        entry.name
        for entry in apps_root.iterdir()
        if entry.is_dir()
        and entry.name not in EXCLUDED_APPS
        and not entry.name.startswith("__")
    ]
    return sorted(names)


def _e2e_matches(e2e_dir: Path, stem: str) -> bool:
    """Return whether any Playwright spec matches ``<stem>*.spec.ts``.

    :param e2e_dir: The ``frontend/packages/e2e/tests`` directory.
    :param stem: The spec filename stem to match.
    :return: ``True`` when at least one spec matches.
    """
    return any(e2e_dir.glob(f"{stem}*.spec.ts"))


def validate_aliases(apps: list[str], repo_root: Path) -> None:
    """Assert every alias entry points at a real app and a real path.

    Keeps the alias maps from silently rotting: a renamed or deleted target
    fails here rather than emitting a glob that can never match.

    :param apps: Discovered app-slice names.
    :param repo_root: Repository root the surfaces are resolved against.
    :raises ValueError: When an alias key is not a known app, or its target
        directory (templates) or spec (e2e) is missing on disk.
    """
    app_set = set(apps)
    for app, template_dir in TEMPLATE_ALIASES.items():
        if app not in app_set:
            msg = f"template alias references unknown app: {app!r}"
            raise ValueError(msg)
        if not (repo_root / "templates" / template_dir).is_dir():
            msg = (
                f"stale template alias {app!r} -> templates/{template_dir}: "
                "directory does not exist"
            )
            raise ValueError(msg)

    e2e_dir = repo_root / "frontend" / "packages" / "e2e" / "tests"
    for app, stem in E2E_ALIASES.items():
        if app not in app_set:
            msg = f"e2e alias references unknown app: {app!r}"
            raise ValueError(msg)
        if not _e2e_matches(e2e_dir, stem):
            msg = f"stale e2e alias {app!r} -> {stem}: no spec matches {stem}*.spec.ts"
            raise ValueError(msg)


def app_globs(app: str, repo_root: Path) -> list[str]:
    """Return the POSIX globs for one app slice, in deterministic order.

    Only surfaces that exist on disk are emitted, so the config stays truthful
    as apps migrate away from ``templates/`` or gain a React package.

    :param app: The app-slice name.
    :param repo_root: Repository root the surfaces are resolved against.
    :return: Ordered glob strings for the app's changed-file rule.
    """
    globs = [f"app/sep/apps/{app}/**"]

    frontend_dir = repo_root / "frontend" / "packages" / "apps" / app
    if frontend_dir.is_dir():
        globs.append(f"frontend/packages/apps/{app}/**")

    tests_dir = repo_root / "tests" / "app" / "sep" / "apps" / app
    if tests_dir.is_dir():
        globs.append(f"tests/app/sep/apps/{app}/**")

    template_dir = TEMPLATE_ALIASES.get(app, app)
    if (repo_root / "templates" / template_dir).is_dir():
        globs.append(f"templates/{template_dir}/**")

    e2e_stem = E2E_ALIASES.get(app, app)
    if _e2e_matches(repo_root / "frontend" / "packages" / "e2e" / "tests", e2e_stem):
        globs.append(f"frontend/packages/e2e/tests/{e2e_stem}*.spec.ts")

    return globs


def render_app_block(apps_root: Path, repo_root: Path) -> str:
    """Return the marker-delimited ``app:<name>`` YAML block.

    :param apps_root: The ``app/sep/apps`` directory to scan.
    :param repo_root: Repository root the surfaces are resolved against.
    :return: The block text, framed by the BEGIN/END marker comments and
        ending with a trailing newline.
    :raises ValueError: When an alias entry is stale (see :func:`validate_aliases`).
    """
    apps = discover_apps(apps_root)
    validate_aliases(apps, repo_root)

    lines = [BEGIN_MARKER, _REGEN_HINT]
    for app in apps:
        lines.append(f"app:{app}:")
        lines.append("- any:")
        lines.append("  - changed-files:")
        lines.append("    - any-glob-to-any-file:")
        lines.extend(f"      - '{glob}'" for glob in app_globs(app, repo_root))
    lines.append(END_MARKER)
    return "\n".join(lines) + "\n"


def render_labeler(text: str, block: str) -> str:
    """Return ``text`` with the generated app block inserted or replaced.

    Replaces the region between the BEGIN/END markers when present, preserving
    every hand-maintained rule around it. When the markers are absent (first
    run), appends the block after a blank-line separator.

    :param text: Current ``.github/labeler.yml`` contents.
    :param block: Marker-delimited block from :func:`render_app_block`.
    :return: Updated file contents.
    :raises ValueError: When exactly one of the two markers is present, which
        would make replacement ambiguous.
    """
    lines = text.splitlines()
    begin = next((i for i, line in enumerate(lines) if line == BEGIN_MARKER), None)
    end = next((i for i, line in enumerate(lines) if line == END_MARKER), None)

    if (begin is None) != (end is None):
        msg = "labeler.yml has a mismatched generated-block marker"
        raise ValueError(msg)

    if begin is not None and end is not None:
        if end < begin:
            msg = "labeler.yml generated-block markers are out of order"
            raise ValueError(msg)
        head = "".join(f"{line}\n" for line in lines[:begin])
        tail = "".join(f"{line}\n" for line in lines[end + 1 :])
        return head + block + tail

    prefix = text if text.endswith("\n") or text == "" else text + "\n"
    separator = "" if prefix == "" or prefix.endswith("\n\n") else "\n"
    return prefix + separator + block


def sync_labeler(
    labeler_path: Path,
    apps_root: Path,
    repo_root: Path,
    *,
    check: bool = False,
) -> bool:
    """Rewrite or check ``labeler_path`` against the filesystem walk.

    :param labeler_path: Path to ``.github/labeler.yml``.
    :param apps_root: The ``app/sep/apps`` directory to scan.
    :param repo_root: Repository root the surfaces are resolved against.
    :param check: When true, report drift without writing.
    :return: ``True`` when the file already matched (or was rewritten);
        ``False`` when ``check`` found drift.
    :raises ValueError: When an alias entry is stale or markers are malformed.
    """
    block = render_app_block(apps_root, repo_root)
    original = labeler_path.read_text(encoding="utf-8")
    updated = render_labeler(original, block)
    if original == updated:
        return True
    if check:
        return False
    labeler_path.write_text(updated, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    """Sync or check the generated ``app:<name>`` block in ``labeler.yml``.

    :param argv: CLI arguments (defaults to ``sys.argv[1:]``).
    :return: ``0`` on success / in sync; ``1`` when ``--check`` finds drift
        or an alias entry is stale.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail without writing when the app label block has drifted",
    )
    parser.add_argument(
        "--labeler",
        type=Path,
        default=DEFAULT_LABELER,
        help="path to .github/labeler.yml (default: repo-root .github/labeler.yml)",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="repository root the app surfaces are resolved against",
    )
    args = parser.parse_args(argv)
    apps_root = args.repo_root.joinpath(*APPS_SUBDIR)

    try:
        matched = sync_labeler(
            args.labeler, apps_root, args.repo_root, check=args.check
        )
    except (ValueError, OSError) as exc:
        print(f"{args.labeler}: {exc}", file=sys.stderr)
        return 1

    if args.check:
        if not matched:
            print(
                f"{args.labeler}: generated app labels are out of date; "
                "regenerate with `python scripts/sync_labeler_apps.py`",
                file=sys.stderr,
            )
            return 1
        print(f"{args.labeler}: generated app labels are in sync.")
        return 0

    print(f"Synced generated app labels in {args.labeler}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
