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

"""Rename SEP to PMM Extensions across a checkout, driven by the rename map.

Every old and new name comes from a row of the rename map
(``scripts/rename_to_extensions_map.json`` by default). This module only knows
*how* each row's names appear in the tree: which item of the row's ``old`` and
``new`` lists pair up, and in which textual shapes a name occurs (a dotted module
path, a quoted track key, an image reference). A row missing from the map
contributes no rule, so a name the map does not confirm is never renamed.

The run has two halves. Files whose path carries an old name are moved with
``git mv`` (plus the ignored ``CLAUDE.md``/``AGENTS.md`` files beside them), then
every tracked text file outside the excluded paths is rewritten. Before the
rules run, the spans listed in :data:`PROTECTED` are masked, so ticket keys,
separator variables, deliberate leftovers and names whose row the map lacks
come through byte-identical.

The run is idempotent: no rule matches its own output, so a second run on a
renamed tree reports zero replacements. That is what lets an open pull request
be migrated by merging ``main`` and running the script again.

Usage::

    python scripts/rename_to_extensions.py --dry-run
    python scripts/rename_to_extensions.py --report rename-report.json
    python scripts/rename_to_extensions.py --side-repo "$SIDE_GIT_DIR"

``--dry-run`` prints the per-row replacement counts and the planned moves
without touching the tree. ``--side-repo`` names the git-dir of the side
repository that tracks the ignored ``CLAUDE.md`` files; the moves are then also
recorded there with ``git mv``, which is only meaningful when that repository's
work-tree is this checkout.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAP = REPO_ROOT / "scripts" / "rename_to_extensions_map.json"

ITEM_SEPARATOR = " · "

EXCLUDED_PATHS = re.compile(
    r"(^|/)migrations/versions/"
    r"|^CHANGELOG\.md$"
    r"|^changelog\.d/"
    r"|^\.claude/"
    r"|^\.claude-plans/"
    r"|^poetry\.lock$"
    r"|^scripts/rename_to_extensions(_map\.json|\.py)$"
    r"|^tests/scripts/test_rename_to_extensions\.py$"
)
"""Paths never rewritten: history, other pull requests' scope, lockfiles, and this tool."""

LOCKFILE_ROWS: dict[str, frozenset[str]] = {
    "frontend/pnpm-lock.yaml": frozenset({"fescope"})
}
"""Lockfiles and the only rows applied to them: workspace package names, never versions."""

PROSE_ONLY_PATHS = re.compile(r"^docs/|^README\.md$|^CONTRIBUTING\.md$")
"""Paths whose prose was renamed by the docs pull request; only code references change."""

IGNORED_COMPANIONS = ("CLAUDE.md", "AGENTS.md")
"""Ignored files that travel with a moved directory."""

Replacement = str | Callable[[re.Match[str]], str]


@dataclass(frozen=True, slots=True)
class Rule:
    """Carry one pattern attributed to one map row.

    :param row: The key of the map row the names come from.
    :param pattern: The compiled pattern to replace.
    :param replacement: The replacement string or function.
    :param prose: Whether the rule rewrites prose, skipped in :data:`PROSE_ONLY_PATHS`.
    """

    row: str
    pattern: re.Pattern[str]
    replacement: Replacement
    prose: bool = False


@dataclass
class Report:
    """Record the outcome of a run, per map row and per file.

    :param replacements: Replacements per map row.
    :param files_per_row: Files each map row changed.
    :param moved: Old path -> new path for every moved tracked file.
    :param moved_ignored: Old path -> new path for every moved ignored companion.
    :param edited: Paths whose content changed.
    :param protected: Masked spans per protection category.
    :param collisions: Per file, renamed identifiers that already existed there.
    :param absent_rows: Rows the rules expect but the map does not carry.
    """

    replacements: Counter[str] = field(default_factory=Counter)
    files_per_row: Counter[str] = field(default_factory=Counter)
    moved: dict[str, str] = field(default_factory=dict)
    moved_ignored: dict[str, str] = field(default_factory=dict)
    edited: list[str] = field(default_factory=list)
    protected: Counter[str] = field(default_factory=Counter)
    collisions: dict[str, list[str]] = field(default_factory=dict)
    absent_rows: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        """Return the report as JSON-serialisable data.

        :return: The per-row counts, the move and edit totals, and the details.
        """
        return {
            "rows": {
                row: {"replacements": count, "files": self.files_per_row[row]}
                for row, count in sorted(self.replacements.items())
            },
            "moved": len(self.moved),
            "moved_ignored": self.moved_ignored,
            "edited": len(self.edited),
            "protected": dict(sorted(self.protected.items())),
            "collisions": self.collisions,
            "absent_rows": self.absent_rows,
        }


class RenameMap:
    """Hold the rename map's rows, parsed into ``old``/``new`` item lists.

    :param rows: The ``rows`` array of the map file.
    """

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = {str(row["key"]): row for row in rows if row.get("confirmed")}

    def __contains__(self, key: str) -> bool:
        return key in self._rows

    def items(self, key: str, side: str) -> list[str]:
        """Return one side of a row split into its items, annotations removed.

        :param key: The row key.
        :param side: ``"old"`` or ``"new"``.
        :return: The items, each stripped of parenthesised notes and ellipses.
        """
        raw = str(self._rows[key][side])
        items = []
        for item in raw.split(ITEM_SEPARATOR):
            cleaned = re.sub(r"\s+\([^)]*\)", "", item).replace("…", "").strip()
            items.append(cleaned)
        return items

    def pair(
        self, key: str, old_index: int, new_index: int | None = None
    ) -> tuple[str, str]:
        """Return the ``old``/``new`` items at the given positions of a row.

        :param key: The row key.
        :param old_index: The position in ``old``.
        :param new_index: The position in ``new``; defaults to ``old_index``.
        :return: The two items.
        """
        new_items = self.items(key, "new")
        position = old_index if new_index is None else new_index
        return self.items(key, "old")[old_index], new_items[
            min(position, len(new_items) - 1)
        ]


def last_word(item: str) -> str:
    """Return the name an annotated item carries, e.g. ``sep-error`` of ``SSE event sep-error``.

    :param item: One map item, possibly prefixed with what the name is.
    :return: The item's last whitespace-separated word.
    """
    return item.split()[-1]


def bounded(name: str) -> re.Pattern[str]:
    """Match ``name`` where it is not part of a longer identifier, path or kebab word.

    :param name: The literal name to match.
    :return: The compiled, boundary-guarded pattern.
    """
    return re.compile(rf"(?<![\w-]){re.escape(name)}(?![\w-])")


def literal_pairs(
    rename_map: RenameMap, key: str, count: int, *, words: bool = False
) -> list[Rule]:
    """Build one bounded rule per ``old``/``new`` item pair of a row.

    :param rename_map: The parsed map.
    :param key: The row key.
    :param count: How many leading pairs to take.
    :param words: Whether each item is annotated and its last word is the name.
    :return: The rules.
    """
    rules = []
    for index in range(count):
        old, new = rename_map.pair(key, index)
        if words:
            old, new = last_word(old), last_word(new)
        rules.append(Rule(key, bounded(old), new))
    return rules


def prefix_rule(rename_map: RenameMap, key: str, index: int) -> Rule:
    """Build a rule for a wildcard item such as ``SEP__*`` or ``PMM_DEV_SEP_*``.

    :param rename_map: The parsed map.
    :param key: The row key.
    :param index: The item position.
    :return: A rule renaming the prefix wherever it starts a name.
    """
    old, new = (last_word(item).rstrip("*") for item in rename_map.pair(key, index))
    return Rule(key, re.compile(rf"(?<![\w-]){re.escape(old)}"), new)


def _stems(rename_map: RenameMap) -> tuple[str, str]:
    """Return the package stem pair, ``sep``/``extensions``, from the ``pkg`` row.

    :param rename_map: The parsed rename map.
    :return: The old and new stems.
    """
    old, new = rename_map.pair("pkg", 0)
    return old.rsplit("/", 1)[-1], new.rsplit("/", 1)[-1]


def _camel(word: str) -> str:
    return word[:1].upper() + word[1:]


def build_rules(rename_map: RenameMap, report: Report) -> list[Rule]:
    """Build every rule, most specific first, from the rows the map carries.

    :param rename_map: The parsed map.
    :param report: Receives the keys of rows the rules expect but the map lacks.
    :return: The ordered rules.
    """
    builders: list[tuple[str, Callable[[], list[Rule]]]] = [
        ("addr", lambda: _addr(rename_map)),
        ("compose", lambda: _compose(rename_map)),
        ("enable", lambda: literal_pairs(rename_map, "enable", 1)),
        ("pgpass", lambda: literal_pairs(rename_map, "pgpass", 1)),
        ("devenv", lambda: [prefix_rule(rename_map, "devenv", 0)]),
        ("proto", lambda: literal_pairs(rename_map, "proto", 3)),
        ("goenv", lambda: literal_pairs(rename_map, "goenv", 1)),
        ("telemetry", lambda: literal_pairs(rename_map, "telemetry", 3)),
        ("routes", lambda: literal_pairs(rename_map, "routes", 2)),
        ("nginxd", lambda: literal_pairs(rename_map, "nginxd", 2)),
        ("secrets", lambda: literal_pairs(rename_map, "secrets", 4)),
        ("vol", lambda: literal_pairs(rename_map, "vol", 2)),
        ("harness", lambda: literal_pairs(rename_map, "harness", 1)),
        ("pgrole", lambda: _pgrole(rename_map)),
        ("alerts", lambda: _alerts(rename_map)),
        ("root", lambda: _root(rename_map)),
        ("apiseg", lambda: _apiseg(rename_map)),
        ("home", lambda: _home(rename_map)),
        ("srcdir", lambda: literal_pairs(rename_map, "srcdir", 1)),
        ("pyproject", lambda: _pyproject(rename_map)),
        ("ci", lambda: _ci(rename_map)),
        ("imgtag", lambda: _imgtag(rename_map)),
        ("dev", lambda: _dev(rename_map)),
        ("sqlite", lambda: _sqlite(rename_map)),
        ("hmac", lambda: _hmac(rename_map)),
        ("appname", lambda: _appname(rename_map)),
        ("header", lambda: literal_pairs(rename_map, "header", 1)),
        ("markers", lambda: literal_pairs(rename_map, "markers", 3)),
        ("browser", lambda: literal_pairs(rename_map, "browser", 2)),
        ("sse", lambda: literal_pairs(rename_map, "sse", 1, words=True)),
        ("principal", lambda: _principal(rename_map)),
        ("supervisord", lambda: _supervisord(rename_map)),
        ("prefix", lambda: _prefix(rename_map)),
        ("token", lambda: literal_pairs(rename_map, "token", 2)),
        ("alembic", lambda: _alembic(rename_map)),
        ("beat", lambda: [prefix_rule(rename_map, "beat", 0)]),
        ("fescope", lambda: _fescope(rename_map)),
        ("pkg", lambda: _pkg(rename_map)),
        ("short", lambda: _short(rename_map)),
        ("display", lambda: _display(rename_map)),
    ]
    rules: list[Rule] = []
    for key, build in builders:
        if key not in rename_map:
            report.absent_rows.append(key)
            continue
        rules.extend(build())
    return rules


def _addr(rename_map: RenameMap) -> list[Rule]:
    old, new = rename_map.pair("addr", 0)
    old_var, old_default = old.split("=")
    new_var, new_default = new.split("=")
    return [
        Rule("addr", bounded(old_var), new_var),
        Rule(
            "addr", re.compile(rf"(?<![\w/.-]){re.escape(old_default)}\b"), new_default
        ),
    ]


def _compose(rename_map: RenameMap) -> list[Rule]:
    rules = []
    for index in (1, 2):
        old, new = rename_map.pair("compose", index)
        rules.append(Rule("compose", re.compile(rf"(?<![\w-]){re.escape(old)}\b"), new))
    return rules


def _pgrole(rename_map: RenameMap) -> list[Rule]:
    old, new = rename_map.pair("pgrole", 1)
    return [Rule("pgrole", re.compile(re.escape(old) + r"\b"), new)]


def _alerts(rename_map: RenameMap) -> list[Rule]:
    old, new = rename_map.pair("alerts", 2)
    return [Rule("alerts", bounded(old), new)]


def _root(rename_map: RenameMap) -> list[Rule]:
    location, root_path = rename_map.items("root", "old")[:2]
    new_path = rename_map.items("root", "new")[0].rstrip("/")
    old_path = location.split()[-1].rstrip("/")
    root_key = root_path.split(":")[0]
    return [
        Rule(
            "root",
            re.compile(rf"(location\s+){re.escape(old_path)}/"),
            rf"\g<1>{new_path}/",
        ),
        Rule(
            "root",
            re.compile(rf"({root_key}\s*[:=]\s*[\"']?){re.escape(old_path)}(?![\w-])"),
            rf"\g<1>{new_path}",
        ),
    ]


def _apiseg(rename_map: RenameMap) -> list[Rule]:
    old, new = rename_map.pair("apiseg", 0)
    old, new = old.split()[0].strip("/"), new.split()[0].strip("/")
    return [Rule("apiseg", re.compile(rf"(?<![\w-]){re.escape(old)}(?![\w-])"), new)]


def _home(rename_map: RenameMap) -> list[Rule]:
    user_item, home_item = rename_map.items("home", "old")[:2]
    new_user_item, new_home_item = rename_map.items("home", "new")[:2]
    return [
        Rule("home", bounded(home_item), new_home_item),
        Rule("home", bounded(user_item), new_user_item),
    ]


def _pyproject(rename_map: RenameMap) -> list[Rule]:
    name_item, wheel_item = rename_map.items("pyproject", "old")[:2]
    new_name, new_wheel = rename_map.items("pyproject", "new")[:2]
    field_name, old_name = name_item.split()
    old_prefix, suffix = wheel_item.split("{v}")
    new_prefix = new_wheel.split("{v}")[0]
    return [
        Rule(
            "pyproject",
            re.compile(rf'(?<![\w])({field_name} = "){re.escape(old_name)}(")'),
            rf"\g<1>{new_name}\g<2>",
        ),
        Rule(
            "pyproject",
            re.compile(
                rf"(?<![\w-]){re.escape(old_prefix)}(?=(\{{[^}}]*\}}|[\w.]+){re.escape(suffix)})"
            ),
            new_prefix,
        ),
    ]


def _imgtag(rename_map: RenameMap) -> list[Rule]:
    old, new = rename_map.pair("imgtag", 0)
    old_image, new_image = old.split(":")[0], new.split(":")[0]
    return [
        Rule(
            "imgtag",
            re.compile(
                rf"(?:(?<=localhost/)|(?<=://)|(?<![\w./-])){re.escape(old_image)}:(?=[\w${{])"
            ),
            f"{new_image}:",
        )
    ]


def _ci(rename_map: RenameMap) -> list[Rule]:
    rules = literal_pairs(rename_map, "ci", 3)
    old_db, new_db = rename_map.pair("ci", 2)
    old_user, new_user = old_db.split("_")[0], new_db.split("_")[0]
    rules += [
        Rule(
            "ci",
            re.compile(rf"(//){old_user}:{old_user}@"),
            rf"\g<1>{new_user}:{new_user}@",
        ),
        Rule(
            "ci",
            re.compile(rf"(POSTGRES_(?:USER|PASSWORD):\s*){old_user}$", re.MULTILINE),
            rf"\g<1>{new_user}",
        ),
    ]
    return rules


def _dev(rename_map: RenameMap) -> list[Rule]:
    rules = []
    olds, news = rename_map.items("dev", "old"), rename_map.items("dev", "new")
    old_casdoor, new_casdoor = last_word(olds[1]).split("/"), news[1].split("/")
    pairs = [(olds[0], news[0]), (olds[2], news[2])]
    pairs += [
        (old, new)
        for old, new in zip(old_casdoor, new_casdoor, strict=True)
        if "-" in old
    ]
    rules += [Rule("dev", bounded(old), new) for old, new in pairs]
    org_old, org_new = next(
        (o, n) for o, n in zip(old_casdoor, new_casdoor, strict=True) if "-" not in o
    )
    rules.append(
        Rule(
            "dev",
            re.compile(
                rf"^(\s*(?:organization_name|NAME|BEAT_SCHEMA):\s*){org_old}$",
                re.MULTILINE,
            ),
            rf"\g<1>{org_new}",
        )
    )
    return rules


def _sqlite(rename_map: RenameMap) -> list[Rule]:
    old, new = rename_map.pair("sqlite", 0)
    return [Rule("sqlite", re.compile(rf"(?<![\w.-]){re.escape(old)}\b"), new)]


def _hmac(rename_map: RenameMap) -> list[Rule]:
    old, new = rename_map.pair("hmac", 0)
    return [Rule("hmac", re.compile(re.escape(old)), new)]


def _appname(rename_map: RenameMap) -> list[Rule]:
    old, new = rename_map.pair("appname", 1)
    return [Rule("appname", re.compile(re.escape(old)), new)]


def _principal(rename_map: RenameMap) -> list[Rule]:
    username, first_name = rename_map.items("principal", "old")[:2]
    new_username, new_first_name = rename_map.items("principal", "new")[:2]
    field_name, old_value = first_name.split(maxsplit=1)
    new_value = new_first_name.split(maxsplit=1)[1]
    return [
        Rule("principal", bounded(last_word(username)), last_word(new_username)),
        Rule(
            "principal",
            re.compile(rf"({field_name}\s*[=:]\s*[\"']){re.escape(old_value)}([\"'])"),
            rf"\g<1>{new_value}\g<2>",
        ),
    ]


def _supervisord(rename_map: RenameMap) -> list[Rule]:
    rules = []
    for index in range(3):
        old, new = rename_map.pair("supervisord", index)
        rules.append(
            Rule(
                "supervisord", re.compile(rf"(?<![\w-]){re.escape(old)}(?![\w-])"), new
            )
        )
    return rules


def _prefix(rename_map: RenameMap) -> list[Rule]:
    old_section = rename_map.items("prefix", "old")[1].split()[-1].rstrip(":")
    new_section = rename_map.items("prefix", "new")[1].split()[-1].rstrip(":")
    return [
        prefix_rule(rename_map, "prefix", 0),
        Rule(
            "prefix",
            re.compile(rf"^(\s*){old_section}:(?=\s*$)", re.MULTILINE),
            rf"\g<1>{new_section}:",
        ),
        Rule(
            "prefix",
            re.compile(rf"(?<![\w.]){old_section}\.(?=[A-Z])"),
            f"{new_section}.",
        ),
    ]


def _alembic(rename_map: RenameMap) -> list[Rule]:
    olds, news = rename_map.items("alembic", "old"), rename_map.items("alembic", "new")
    flag, old_track = olds[1].split()
    new_track = news[1].split()[1]
    return [
        Rule("alembic", bounded(olds[0]), news[0]),
        Rule(
            "alembic",
            re.compile(rf"((?:{flag}|-n)[ =]){old_track}\b"),
            rf"\g<1>{new_track}",
        ),
        Rule("alembic", bounded(olds[2]), news[2]),
        Rule("alembic", re.compile(re.escape(olds[3])), news[3]),
        Rule(
            "alembic",
            re.compile(re.escape(re.escape(olds[3]))),
            re.escape(news[3]).replace("\\", "\\\\"),
        ),
        Rule(
            "alembic", re.compile(rf"([\"'`]){old_track}\1"), rf"\g<1>{new_track}\g<1>"
        ),
        Rule("alembic", re.compile(rf"``{old_track}``"), f"``{new_track}``"),
        Rule("alembic", _TRACK_LIST, _in_track_list(old_track, new_track)),
        Rule("alembic", _DATABASES_LINE, _in_track_list(old_track, new_track)),
    ]


_DATABASES_LINE = re.compile(
    r"(?:^|(?<=\\n))[ \t]*[\"']?databases[ \t]*=[^\n\\\"']*", re.MULTILINE
)
"""An ``alembic.ini`` track list, which may name the old track alone.

Matched at a line start or after an escaped ``\\n``, so the ini text a test
builds inside a string literal is covered as well as the file itself.
"""


_TRACK_LIST = re.compile(
    r"^.*\binventory\b.*\btasks\b.*$|^.*\btasks\b.*\binventory\b.*$", re.MULTILINE
)
"""A line naming the other two tracks, where a bare old track name is the third."""


def _in_track_list(old: str, new: str) -> Callable[[re.Match[str]], str]:
    """Rename the bare track name inside a matched track-list line.

    :param old: The old track name.
    :param new: The new track name.
    :return: A replacement function for :meth:`re.Pattern.sub`.
    """
    word = re.compile(rf"(?<![\w./@-]){old}(?![\w./-])")
    return lambda match: word.sub(new, match.group())


_SERVICE_LIST = re.compile(
    r"^.*\bInventory\b.*\bTasks\b.*$|^.*\bTasks\b.*\bInventory\b.*$", re.MULTILINE
)
"""A line naming the Inventory and Tasks services, where the abbreviation is the third."""


def _short(rename_map: RenameMap) -> list[Rule]:
    """Name the core service beside Inventory and Tasks with the short product name.

    :param rename_map: The parsed rename map.
    :return: The ``short`` row's rules.
    """
    abbreviation = rename_map.items("display", "old")[0]
    new = rename_map.items("short", "new")[0]
    word = re.compile(rf"(?<![\w./-]){abbreviation}(?![\w/-])")
    return [
        Rule(
            "short",
            _SERVICE_LIST,
            lambda match: word.sub(new, match.group()),
            prose=True,
        )
    ]


def _fescope(rename_map: RenameMap) -> list[Rule]:
    old_scope, new_scope = (item.rstrip("*") for item in rename_map.pair("fescope", 0))
    old_dir, new_dir = rename_map.pair("fescope", 1)
    return [
        Rule(
            "fescope",
            re.compile(rf"(?<![\w-]){re.escape(old_scope)}(?=[\w*'\"])"),
            new_scope,
        ),
        Rule("fescope", bounded(old_dir), new_dir),
    ]


_STRING_METHODS = (
    "join|split|rsplit|strip|lstrip|rstrip|replace|encode|decode|startswith|endswith|"
    "lower|upper|format|length|partition|rpartition|count|find|index"
)


def _pkg(rename_map: RenameMap) -> list[Rule]:
    """Rename package paths and module names, then every identifier built on the stem.

    The stem pair is the last path segment of the row's first item. Identifier
    components follow the case of the component they replace.

    :param rename_map: The parsed rename map.
    :return: The ``pkg`` row's rules.
    """
    old_path, new_path = rename_map.pair("pkg", 0)
    old_mount, new_mount = rename_map.pair("pkg", 1)
    old, new = _stems(rename_map)
    root = old_path.split("/")[0]
    upper, camel_old, camel_new = old.upper(), _camel(old), _camel(new)
    no_alnum_before = r"(?<![A-Za-z0-9])"
    no_alnum_after = r"(?![A-Za-z0-9])"
    return [
        Rule(
            "pkg",
            re.compile(rf"(?:(?<![\w-])|(?<=\\[tnr])){re.escape(old_path)}(?![\w-])"),
            new_path,
        ),
        Rule(
            "pkg",
            re.compile(rf"(?<![\w])({root}(?:\\\\?)?\.){old}(?![\w])"),
            rf"\g<1>{new}",
        ),
        Rule("pkg", re.compile(rf"(\bfrom \.+){old}(?=[.\s])"), rf"\g<1>{new}"),
        Rule("pkg", re.compile(rf"(?<![\w])({root}__){old}__"), rf"\g<1>{new}__"),
        Rule(
            "pkg",
            re.compile(rf"([\"']{root}[\"']\s*[,/]\s*[\"']){old}([\"'])"),
            rf"\g<1>{new}\g<2>",
        ),
        Rule("pkg", bounded(old_mount), new_mount),
        Rule("pkg", re.compile(rf"(?<=/){old}(?=['\"`])"), new),
        Rule(
            "pkg",
            re.compile(rf"(?<![\w.]){upper}(?=\s*=(?!=))|(?<=\.){upper}(?![\w-])"),
            new.upper(),
        ),
        Rule(
            "pkg",
            re.compile(rf"{no_alnum_before}{upper}(?=_)|(?<=_){upper}{no_alnum_after}"),
            new.upper(),
        ),
        Rule("pkg", re.compile(rf"(?<![A-Za-z]){upper}(?=[A-Z][a-z])"), camel_new),
        Rule(
            "pkg",
            re.compile(
                rf"(?<![A-Za-z]){camel_old}(?=[A-Z_])|(?<=[a-z0-9]){camel_old}(?=[A-Z_]|{no_alnum_after})"
            ),
            camel_new,
        ),
        Rule("pkg", re.compile(rf"(?<![A-Za-z0-9$]){old}(?=[A-Z])"), new),
        Rule(
            "pkg",
            re.compile(
                rf"{no_alnum_before}{old}(?=_[A-Za-z0-9])|(?<=_){old}{no_alnum_after}"
            ),
            new,
        ),
        Rule(
            "pkg",
            re.compile(
                rf"{no_alnum_before}{old}(?=-[A-Za-z])|(?<=[A-Za-z0-9]-){old}(?![\w-])"
            ),
            new,
        ),
        Rule(
            "pkg",
            re.compile(rf"(?<![\w.]){old}\.(?!(?:{_STRING_METHODS})\b)(?=[A-Za-z])"),
            f"{new}.",
        ),
    ]


def _display(rename_map: RenameMap) -> list[Rule]:
    """Rename prose: the long product names, then the abbreviation with its grammar.

    :param rename_map: The parsed rename map.
    :return: The ``display`` row's rules.
    """
    olds = rename_map.items("display", "old")
    new = rename_map.items("display", "new")[0]
    abbreviation = olds[0]
    long_names = sorted(olds[1:], key=len, reverse=True)
    rules = [
        Rule(
            "display",
            re.compile(rf"{re.escape(name)}(?: \({abbreviation}\))?"),
            new,
            prose=True,
        )
        for name in long_names
    ]
    word = rf"(?<![\w./-]){abbreviation}(?![\w/])"
    rules += [
        Rule("display", re.compile(rf"\b([Aa])n {word}"), rf"\g<1> {new}", prose=True),
        Rule(
            "display",
            re.compile(rf"{word}(['\u2019])s\b"),
            lambda match: f"{new}{match.group(1)}",
            prose=True,
        ),
        Rule(
            "display",
            re.compile(rf"(?<![\w./-]){abbreviation}-(?=[a-z])"),
            f"{new} ",
            prose=True,
        ),
        Rule("display", re.compile(rf"{word}(?!-)"), new, prose=True),
    ]
    return rules


PROTECTED: dict[str, re.Pattern[str]] = {
    "ticket keys": re.compile(
        r"\bSEP-(?:\d|X|N|<|\{|\\d|\[|\*)[^\s'\"`)]*|(?<![\w/-])sep-\d+(?![\d.])[\w-]*|\bSEP\|(?=\w)|(?<=\|)SEP\b"
        r"|\(SEP\||\"SEP\", \"PMM\""
    ),
    "repository and Jenkins names (external rows)": re.compile(
        r"(?i:\bpercona/sep\b)[\w./-]*|\bpercona-sep\b|\bjob/SEP\b|\bSEP/(?=[\w{$])|(?<=/)SEP\b|:5555/sep\b"
        r"|\bSEP_DOCKER_HUB_WRITE_TOKEN\b"
    ),
    "repository name and ticket project literals": re.compile(
        r"(?<![=:]\s)(?<![=:])([\"'])SEP\1"
    ),
    "separators": re.compile(
        r"\bos\.sep\b|\bpath\.sep\b|\bsep\s*=(?!=)|\bsep\s*:\s*str\b|\w*dot_sep\b|\w*DotSep\b|\b_MODELS_SEP\b|\bsep\.(?:"
        + _STRING_METHODS
        + r")\b"
    ),
    "pre-rename names the forward migrations read": re.compile(
        r"\bPRE_RENAME_\w*(?:\s*(?::\s*[\w\[\]]+)?\s*=\s*[\"'][^\"'\n]*[\"'])?|sep\.enc\.v1\."
    ),
    "legacy setting token": re.compile(
        r"[\"'`]SEP_SETTINGS[\"'`]|\b_?LEGACY_SEP\w*|_FrozenSEPSettings|SEPSettings\.(?=\w)(?=[^\n]*legacy)"
    ),
    "unconfirmed: plugin periodic-task table": re.compile(
        r"\w*SEPPluginPeriodicTask\w*|\bseppluginperiodictask\w*"
    ),
    "unconfirmed: grafana assertion salt": re.compile(r"sep\.auth\.grafana\.v1"),
    "unconfirmed: files on customer hosts": re.compile(
        r"\.?sep-run-result\.json|\bsep_interpreter\b"
    ),
    "customer-host debug variable not in the map": re.compile(r"\bSEPDEBUG\b"),
    "PMM-side flag not in the map": re.compile(r"--sep-token"),
    "external GAS automation": re.compile(
        r"\broles/sep\b[\w./-]*|\bautomation/sep\.yaml\b|\bsep_(?:image_name|image_tag|nomad_\w+|user|controller)\b"
    ),
    "Jira fixVersion (dismissed row)": re.compile(r"\bsep-next\b"),
    "names exported by the external @percona/percona-ui package": re.compile(
        r"\b(?:sep(?:Brand|TechnologyColors|ThemeOptions\w*|PrimaryLight|PrimaryDark"
        r"|TokensLight|TokensDark)|SepTheme)\b"
    ),
}
"""Spans masked before any rule runs, by the category the report lists them under."""

GUARDED_ROWS: dict[str, str] = {
    "plugintask": "unconfirmed: plugin periodic-task table",
    "grafsalt": "unconfirmed: grafana assertion salt",
    "hostfiles": "unconfirmed: files on customer hosts",
}
"""Rows whose names the generic rules would otherwise derive -> the guard each lifts.

The generic ``pkg`` rules would give these names a plain ``extensions`` form,
which is not what the map settled on. Without the row, the guard keeps them
untouched; with it, :func:`build_guarded_rules` applies the row's own names.
"""


def build_guarded_rules(rename_map: RenameMap) -> list[Rule]:
    """Build the rules of the guarded rows the map carries.

    Each such row is a list of ``old``/``new`` pairs whose last word is the name.
    A name matches as the start of a longer word too, so a class carries its
    ``Base``/``Manager`` companions and a table its index names. A leading dot is
    optional on both sides, so a hidden file name also matches where it is
    written without one. The row's guard is lifted by :func:`active_protections`.

    :param rename_map: The parsed map.
    :return: The rules, longest name first.
    """
    rules = []
    for key in GUARDED_ROWS:
        if key not in rename_map:
            continue
        olds = [last_word(item).lstrip(".") for item in rename_map.items(key, "old")]
        news = [last_word(item).lstrip(".") for item in rename_map.items(key, "new")]
        for old, new in sorted(
            zip(olds, news, strict=True), key=lambda pair: -len(pair[0])
        ):
            rules.append(
                Rule(key, re.compile(rf"(?<![A-Za-z0-9]){re.escape(old)}"), new)
            )
    return rules


_REVISION_SLUG = re.compile(r"/[0-9_]+-[0-9a-f]+_(?P<slug>\w+)\.py$")


def revision_slug_protection(files: Iterable[str]) -> dict[str, re.Pattern[str]]:
    """Guard the names of history revisions, which prose cites and history keeps.

    A revision's slug is part of its file name, which never changes, so a
    comment naming the revision must keep naming it as written.

    :param files: The tracked paths.
    :return: One protection category, empty when no slug carries an old name.
    """
    slugs = sorted(
        {
            match.group("slug")
            for path in files
            if HISTORY_PATHS.search(path)
            and (match := _REVISION_SLUG.search(path))
            and "sep" in match.group("slug").lower()
        },
        key=len,
        reverse=True,
    )
    if not slugs:
        return {}
    alternatives = "|".join(re.escape(slug) for slug in slugs)
    return {"history revision names": re.compile(rf"\b(?:{alternatives})\b")}


def active_protections(rename_map: RenameMap) -> dict[str, re.Pattern[str]]:
    """Return :data:`PROTECTED` without the guards of the guarded rows the map carries.

    :param rename_map: The parsed rename map.
    :return: The masking patterns in force, by category.
    """
    lifted = {category for key, category in GUARDED_ROWS.items() if key in rename_map}
    return {
        category: pattern
        for category, pattern in PROTECTED.items()
        if category not in lifted
    }


_MASK = "\x00{}\x00"
_IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*")


def rewrite(
    text: str,
    rules: list[Rule],
    protections: dict[str, re.Pattern[str]],
    *,
    prose: bool,
) -> tuple[str, Counter[str], Counter[str]]:
    """Apply the rules to one file's text.

    :param text: The original content.
    :param rules: The ordered rules.
    :param protections: The spans to mask.
    :param prose: Whether prose rules apply to this file.
    :return: The new content, replacements per row, and masked spans per category.
    """
    masked: list[str] = []
    protected: Counter[str] = Counter()

    def mask(category: str) -> Callable[[re.Match[str]], str]:
        def _mask(match: re.Match[str]) -> str:
            masked.append(match.group())
            protected[category] += 1
            return _MASK.format(len(masked) - 1)

        return _mask

    for category, pattern in protections.items():
        text = pattern.sub(mask(category), text)
    counts: Counter[str] = Counter()
    for rule in rules:
        if rule.prose and not prose:
            continue
        text = rule.pattern.sub(_counting(rule, counts), text)
    text = re.sub("\x00(\\d+)\x00", lambda match: masked[int(match.group(1))], text)
    return text, counts, protected


def _counting(rule: Rule, counts: Counter[str]) -> Callable[[re.Match[str]], str]:
    """Wrap a rule's replacement so only a match it actually changes is counted.

    :param rule: The rule whose replacement is wrapped.
    :param counts: The per-row counter to increment.
    :return: A replacement function for :meth:`re.Pattern.sub`.
    """

    def _replace(match: re.Match[str]) -> str:
        if isinstance(rule.replacement, str):
            replaced = match.expand(rule.replacement)
        else:
            replaced = rule.replacement(match)
        if replaced != match.group():
            counts[rule.row] += 1
        return replaced

    return _replace


HISTORY_PATHS = re.compile(r"(^|/)migrations/versions/[^/]+\.py$")
"""Revision scripts: history, whose only edit is the module path it imports from."""

_HISTORY_IMPORT = re.compile(
    r"^from (?P<module>[\w.]+) import (?P<names>\([^)]*\)|[^\n]+)$", re.MULTILINE
)


def rewrite_history_imports(
    text: str, rules: list[Rule], protections: dict[str, re.Pattern[str]]
) -> tuple[str, int]:
    """Point a revision script's imports at the moved modules, and change nothing else.

    A revision that imports from the renamed package cannot load once the
    package moves, but its body is history and stays byte-identical. So only the
    ``from ... import`` lines change: the module path takes its new name, and an
    imported name that was renamed too is bound back to the name the body uses
    (``extensions_settings as sep_settings``).

    :param text: The revision script.
    :param rules: The ordered rules.
    :param protections: The spans to mask.
    :return: The rewritten script and the number of import lines changed.
    """
    count = 0

    def _import(match: re.Match[str]) -> str:
        nonlocal count
        module = rename_path(match.group("module"), rules, protections)
        if module == match.group("module"):
            return match.group()
        names = match.group("names")
        parenthesised = names.startswith("(")
        bindings = []
        for entry in names.strip("()").split(","):
            name, _, alias = (part.strip() for part in entry.strip().partition(" as "))
            if not name:
                continue
            renamed = rename_path(name, rules, protections)
            bound = alias or (name if renamed != name else "")
            bindings.append(f"{renamed} as {bound}" if bound else renamed)
        count += 1
        if parenthesised:
            body = "".join(f"    {binding},\n" for binding in bindings)
            return f"from {module} import (\n{body})"
        return f"from {module} import {', '.join(bindings)}"

    return _HISTORY_IMPORT.sub(_import, text), count


def rename_path(
    path: str, rules: list[Rule], protections: dict[str, re.Pattern[str]]
) -> str:
    """Return the renamed form of a repository path, by the non-prose rules.

    :param path: The repository-relative path.
    :param rules: The rules to apply.
    :param protections: The masking patterns in force.
    :return: The path with every old name renamed.
    """
    return rewrite(
        path, [rule for rule in rules if not rule.prose], protections, prose=False
    )[0]


def git(*args: str, git_dir: str | None = None) -> str:
    """Run git in the repository root and return its stdout.

    :param args: The git arguments.
    :param git_dir: A git directory to run against instead of the repository's.
    :return: The command's standard output.
    """
    prefix = (
        ["git", f"--git-dir={git_dir}", f"--work-tree={REPO_ROOT}"]
        if git_dir
        else ["git"]
    )
    return subprocess.run(
        [*prefix, *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout


def tracked_files() -> list[str]:
    """Return every tracked path, submodules and symlinks included.

    :return: The repository-relative paths.
    """
    return [path for path in git("ls-files", "-z").split("\0") if path]


def plan_moves(
    files: Iterable[str], rules: list[Rule], protections: dict[str, re.Pattern[str]]
) -> dict[str, str]:
    """Return old -> new for every tracked path whose name carries an old name.

    An excluded file keeps its own name, since history stays byte-identical, but
    it still follows its directory.

    :param files: The tracked paths.
    :param rules: The rules to apply.
    :param protections: The masking patterns in force.
    :return: Old path -> new path for every path that changes.
    """
    moves = {}
    for path in files:
        if EXCLUDED_PATHS.search(path):
            directory, _, name = path.rpartition("/")
            renamed = rename_path(directory, rules, protections)
            new_path = f"{renamed}/{name}" if directory else path
        else:
            new_path = rename_path(path, rules, protections)
        if new_path != path:
            moves[path] = new_path
    return moves


def plan_ignored_moves(moves: dict[str, str]) -> dict[str, str]:
    """Return old -> new for ignored companions inside every moved directory.

    :param moves: Old path -> new path for the tracked files.
    :return: Old path -> new path for each ignored companion.
    """
    directories = {
        str(Path(old).parent): str(Path(new).parent) for old, new in moves.items()
    }
    companions = {}
    for old_dir, new_dir in directories.items():
        for name in IGNORED_COMPANIONS:
            source = REPO_ROOT / old_dir / name
            if source.is_symlink() or source.exists():
                companions[f"{old_dir}/{name}"] = f"{new_dir}/{name}"
    return companions


def apply_moves(moves: dict[str, str]) -> None:
    """Move tracked files with ``git mv``, batched by destination directory.

    :param moves: Old path -> new path for the tracked files.
    """
    by_destination: dict[str, list[str]] = {}
    for old, new in moves.items():
        if Path(new).name != Path(old).name:
            (REPO_ROOT / new).parent.mkdir(parents=True, exist_ok=True)
            git("mv", old, new)
            continue
        by_destination.setdefault(str(Path(new).parent), []).append(old)
    for destination, sources in by_destination.items():
        (REPO_ROOT / destination).mkdir(parents=True, exist_ok=True)
        for start in range(0, len(sources), 200):
            git("mv", *sources[start : start + 200], destination)


def apply_ignored_moves(companions: dict[str, str], side_repo: str | None) -> None:
    """Move ignored companions, recording the move in the side repository if given.

    :param companions: Old path -> new path for each ignored companion.
    :param side_repo: The side repository's git directory, or ``None``.
    """
    for old, new in companions.items():
        target = REPO_ROOT / new
        if target.exists() or target.is_symlink():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if side_repo:
            git("mv", old, new, git_dir=side_repo)
        else:
            (REPO_ROOT / old).rename(target)


def remove_stale_caches(moves: dict[str, str]) -> None:
    """Delete ``__pycache__`` left in vacated directories, then the directories left empty.

    A vacated package whose ``__pycache__`` survived would still import as a
    namespace package, so its caches go too. Directories are visited deepest
    first, up every moved file's parent chain, so a tree that held only
    subdirectories is removed as well.

    :param moves: Old path -> new path for the tracked files.
    """
    directories: set[Path] = set()
    for old in moves:
        directories.update(Path(old).parents[:-1])
    for relative in sorted(directories, key=lambda path: -len(path.parts)):
        directory = REPO_ROOT / relative
        if directory.is_symlink() or not directory.is_dir():
            continue
        cache = directory / "__pycache__"
        if cache.is_dir() and not any(directory.glob("*.py")):
            shutil.rmtree(cache)
        if not any(directory.iterdir()):
            directory.rmdir()


def read_text(path: Path) -> str | None:
    """Return a file's text, or ``None`` for a binary, unreadable or symlinked file.

    :param path: The file to read.
    :return: The decoded text, or ``None``.
    """
    if path.is_symlink() or not path.is_file():
        return None
    data = path.read_bytes()
    if b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def collisions(
    text: str, rules: list[Rule], protections: dict[str, re.Pattern[str]]
) -> list[str]:
    """Return ``old -> new`` for every identifier whose new name the file already used.

    :param text: The original content.
    :param rules: The ordered rules.
    :param protections: The spans to mask.
    :return: The clashing renames, sorted.
    """
    for pattern in protections.values():
        text = pattern.sub("", text)
    identifiers = set(_IDENTIFIER.findall(text))
    clashes = []
    for identifier in (name for name in identifiers if "sep" in name.lower()):
        renamed = rename_path(identifier, rules, protections)
        if renamed != identifier and renamed in identifiers:
            clashes.append(f"{identifier} -> {renamed}")
    return sorted(clashes)


def rewrite_file(
    path: str,
    text: str,
    rules: list[Rule],
    protections: dict[str, re.Pattern[str]],
    report: Report,
) -> str:
    """Return one tracked file's new content, recording its counts in the report.

    A history file has only its imports rewritten, and any other excluded file
    comes back unchanged. A lockfile gets only the rows it lists.

    :param path: The file's path before any move, which the path filters test.
    :param text: The file's content.
    :param rules: The ordered rules.
    :param protections: The spans to mask.
    :param report: Receives the replacement, protection and collision counts.
    :return: The new content.
    """
    if HISTORY_PATHS.search(path):
        new_text, count = rewrite_history_imports(text, rules, protections)
        if count:
            report.replacements["pkg"] += count
            report.files_per_row["pkg"] += 1
        return new_text
    if EXCLUDED_PATHS.search(path):
        return text
    applicable = rules
    if path in LOCKFILE_ROWS:
        applicable = [rule for rule in rules if rule.row in LOCKFILE_ROWS[path]]
    new_text, counts, protected = rewrite(
        text, applicable, protections, prose=not PROSE_ONLY_PATHS.search(path)
    )
    report.protected.update(protected)
    report.replacements.update(counts)
    report.files_per_row.update(counts.keys())
    if new_text != text and (clashes := collisions(text, rules, protections)):
        report.collisions[path] = clashes
    return new_text


def run(rename_map: RenameMap, *, dry_run: bool, side_repo: str | None) -> Report:
    """Move and rewrite the checkout, or only plan it on a dry run.

    :param rename_map: The parsed map.
    :param dry_run: Whether to leave the tree untouched.
    :param side_repo: The git-dir of the side repository tracking ignored files.
    :return: The report.
    """
    report = Report()
    rules = build_rules(rename_map, report)
    rules = build_guarded_rules(rename_map) + rules
    files = tracked_files()
    protections = active_protections(rename_map) | revision_slug_protection(files)
    report.moved = plan_moves(files, rules, protections)
    report.moved_ignored = plan_ignored_moves(report.moved)
    if not dry_run:
        apply_moves(report.moved)
        apply_ignored_moves(report.moved_ignored, side_repo)
        remove_stale_caches(report.moved)
    for path in files:
        current = report.moved.get(path, path) if not dry_run else path
        text = read_text(REPO_ROOT / current)
        if text is None:
            continue
        new_text = rewrite_file(path, text, rules, protections, report)
        if new_text != text:
            report.edited.append(current)
            if not dry_run:
                (REPO_ROOT / current).write_text(new_text, encoding="utf-8")
    return report


def print_summary(report: Report, *, dry_run: bool) -> None:
    """Print the per-row table and totals.

    :param report: The run's report.
    :param dry_run: Whether the run only planned its edits.
    """
    heading = "Planned" if dry_run else "Applied"
    print(f"{heading} replacements per map row:")
    for row, count in sorted(report.replacements.items(), key=lambda item: -item[1]):
        print(f"  {row:<12} {count:>7} in {report.files_per_row[row]:>5} files")
    print(f"Tracked files moved: {len(report.moved)}")
    print(f"Ignored companions moved: {len(report.moved_ignored)}")
    print(f"Files edited: {len(report.edited)}")
    print("Left untouched on purpose:")
    for category, count in sorted(report.protected.items()):
        print(f"  {category}: {count}")
    if report.absent_rows:
        print(f"Rows not in the map (no rule applied): {', '.join(report.absent_rows)}")
    if report.collisions:
        print(f"Files where a new name already existed: {len(report.collisions)}")


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run.

    :param argv: The arguments, or ``None`` for :data:`sys.argv`.
    :return: The exit status.
    """
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--map", type=Path, default=DEFAULT_MAP, help="rename map JSON")
    parser.add_argument(
        "--dry-run", action="store_true", help="plan only; print per-row counts"
    )
    parser.add_argument("--report", type=Path, help="write the JSON report here")
    parser.add_argument(
        "--side-repo", help="git-dir of the side repo tracking ignored CLAUDE.md files"
    )
    args = parser.parse_args(argv)
    rename_map = RenameMap(json.loads(args.map.read_text(encoding="utf-8"))["rows"])
    report = run(rename_map, dry_run=args.dry_run, side_repo=args.side_repo)
    print_summary(report, dry_run=args.dry_run)
    if args.report:
        args.report.write_text(
            json.dumps(report.as_dict(), indent=1) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
