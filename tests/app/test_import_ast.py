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

"""Check the import resolution both boundary guards read their verdicts from.

The two guards that consume this -- :mod:`tests.app.sep.test_import_boundary`
and :mod:`tests.app.test_factories_boundary` -- assert on classified paths, so a
resolution that silently returns the wrong package reads as a clean tree in
both. The relative levels are therefore pinned here directly, past the depth any
real module spells: a level that climbs one step too far must resolve to nothing
rather than to a prefix of the package it started in.
"""

import ast
from pathlib import Path

import pytest

from app import BASE_DIR
from tests.app.import_ast import absolute_base, package_of


def _import_from(source: str) -> ast.ImportFrom:
    """Return the single ``from ... import`` statement ``source`` declares.

    :param source: The one-statement module source to parse.
    :return: The parsed node.
    """
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.ImportFrom)
    return node


class TestAbsoluteBase:
    """Check the dotted path a ``from ... import`` module part resolves to."""

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            pytest.param(
                "from app.sep.apps.atw.models import AtwIncident",
                "app.sep.apps.atw.models",
                id="absolute-is-returned-unchanged",
            ),
            pytest.param(
                "from .sep.apps import atw",
                "tests.app.sep.apps",
                id="one-dot-anchors-at-the-package",
            ),
            pytest.param(
                "from . import factories",
                "tests.app",
                id="one-dot-alone-is-the-package",
            ),
            pytest.param(
                "from ..app.factories import TaskFactory",
                "tests.app.factories",
                id="two-dots-climb-one-level",
            ),
            pytest.param(
                "from .. import app",
                "tests",
                id="two-dots-alone-are-the-parent",
            ),
            pytest.param(
                "from ... import tests",
                None,
                id="one-level-past-the-root-resolves-to-nothing",
            ),
            pytest.param(
                "from .... import tests",
                None,
                id="two-levels-past-the-root-resolves-to-nothing",
            ),
            pytest.param(
                "from ..... import tests",
                None,
                id="three-levels-past-the-root-resolves-to-nothing",
            ),
        ],
    )
    def test_a_level_resolves_against_the_importing_package(
        self, source: str, expected: str | None
    ) -> None:
        """Resolve each relative level a two-segment package can be climbed from.

        The levels past the root are the ones worth pinning: the anchor is a
        slice, so a level greater than the package depth indexes from the end and
        would resolve to a prefix of the package rather than to ``None``.
        """
        assert absolute_base(_import_from(source), "tests.app") == expected

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            pytest.param(
                "from ....models import AtwIncident",
                "app.models",
                id="level-equal-to-the-package-depth-anchors-at-its-head",
            ),
            pytest.param(
                "from ..... import app",
                None,
                id="level-past-a-deeper-package-resolves-to-nothing",
            ),
        ],
    )
    def test_a_deeper_package_absorbs_more_levels(
        self, source: str, expected: str | None
    ) -> None:
        """Climb as many levels as the importing package has segments, and no more."""
        assert absolute_base(_import_from(source), "app.sep.apps.atw") == expected


class TestPackageOf:
    """Check the package a module resolves its relative imports against."""

    @pytest.mark.parametrize(
        ("relative_path", "expected"),
        [
            pytest.param("tests/app/factories.py", "tests.app", id="module"),
            pytest.param("tests/app/__init__.py", "tests.app", id="package-init"),
            pytest.param(
                "tests/app/sep/apps/atw/factories.py",
                "tests.app.sep.apps.atw",
                id="nested-module",
            ),
        ],
    )
    def test_a_path_dots_to_its_containing_directory(
        self, relative_path: str, expected: str
    ) -> None:
        """Derive the package from the directories above the module itself."""
        assert package_of(BASE_DIR / relative_path, BASE_DIR) == expected

    def test_the_base_sets_what_the_package_is_dotted_from(self) -> None:
        """Resolve a synthetic tree's package against the base it is rooted at."""
        base = Path("/tmp/pytest-of-someone/pytest-0/test_x0")
        assert package_of(base / "tests" / "app" / "factories.py", base) == "tests.app"
