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

"""Resolve :mod:`ast` import nodes to the dotted paths an import boundary reads.

Two guards walk a source tree and classify what each import reaches:
:mod:`tests.app.sep.test_import_boundary` over ``app/``, and
:mod:`tests.app.test_factories_boundary` over the root of the test tree. Both
need the same two answers first -- which package a module resolves its relative
imports against, and what a ``from ... import`` resolves to once that package is
applied -- and neither answer depends on the rule being enforced. They live here
so the resolution is decided once: a bug in either is a quiet non-enforcement in
a guard, and one home means one fix.

Nothing here imports beyond the standard library, so this module satisfies the
app-agnostic rule its own consumer enforces over the test root.
"""

import ast
from pathlib import Path


def absolute_base(node: ast.ImportFrom, package: str) -> str | None:
    """Return the absolute dotted path ``node``'s module part resolves to.

    The level is checked against the package depth before the anchor is sliced: one
    level past the root leaves nothing to anchor to, and two or more past it would
    otherwise index from the end of the package and resolve against a prefix of
    itself.

    :param node: The ``from ... import`` node to resolve.
    :param package: The dotted package the importing module belongs to.
    :return: The absolute module path, or ``None`` when the level climbs past the
        package root.
    """
    if node.level == 0:
        return node.module
    parts = package.split(".")
    if len(parts) < node.level:
        return None
    anchor = parts[: len(parts) - node.level + 1]
    return ".".join([*anchor, node.module] if node.module else anchor)


def package_of(path: Path, base: Path) -> str:
    """Return the dotted package a module resolves its relative imports against.

    :param path: The source path to derive the package from.
    :param base: The directory the path is dotted relative to.
    :return: The dotted package name, which for an ``__init__.py`` is its own
        directory.
    """
    return ".".join(path.relative_to(base).parts[:-1])
