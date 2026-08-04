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

"""Guard the shared test modules against activatable-app imports.

``tests/app/factories.py`` and its siblings sit at the root of the test tree, so
every subtree imports them. A factory or fixture for an activatable app's model
belongs beside that app's tests in ``tests/app/sep/apps/<app>/factories.py``,
where it is owned, discovered, and deleted together with the app. Every module
directly under ``tests/app/`` must therefore name neither ``app.sep.apps`` nor
``tests.app.sep.apps`` in an import, in any spelling -- absolute or relative,
and wherever the import sits, including a function body or an
``if TYPE_CHECKING:`` block. The second prefix closes the re-export loophole,
where a shared module keeps a relocated name importable from its old home by
pulling it back in.

The rule is deliberately stricter than the production-side boundary in
``tests/app/sep/test_import_boundary.py``, and stricter along two axes. That one
guards the PMM-embedded side-car image, which strips non-activated app packages,
so only edges that *execute* on import can break it and it skips function bodies
and ``if TYPE_CHECKING:`` blocks; this one guards ownership, so a deferred or
annotation-only import of an app model counts too -- it is an app-specific
factory waiting to happen. And where that rule classifies
``app.sep.apps.framework``/``shared`` as belonging to no app package -- they ship
in the image, so reaching them breaks nothing -- this one forbids them like any
other app path: a factory for a framework model is still app scaffolding, and
``tests/app/sep/apps/framework/`` already owns that role through ``kit.py`` and
``contract_suite.py``.

Two evasions are deliberately not caught, so the guard is not mistaken for a
total one: a dynamic import whose target is a string literal
(``import_module("app.sep.apps.alters.models")``), and any indirect edge through
a third module that re-exports an app model -- whether named or pulled in by a
star import from that third module. A star import naming an app module directly
is caught like any other import.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

from app import BASE_DIR

SHARED_TEST_ROOT = BASE_DIR / "tests" / "app"

FORBIDDEN_PREFIXES = ("app.sep.apps", "tests.app.sep.apps")


def _absolute_base(node: ast.ImportFrom, package: str) -> str | None:
    """Return the absolute dotted path ``node``'s module part resolves to.

    :param node: The ``from ... import`` node to resolve.
    :param package: The dotted package the importing module belongs to.
    :return: The absolute module path, or ``None`` when the level climbs past the
        package root.
    """
    if node.level == 0:
        return node.module
    parts = package.split(".")
    anchor = parts[: len(parts) - node.level + 1]
    if not anchor:
        return None
    return ".".join([*anchor, node.module] if node.module else anchor)


def _imported_modules(source: str, package: str) -> Iterator[tuple[str, int]]:
    """Yield ``(target, lineno)`` for every import ``source`` declares.

    A ``from`` import is reported as ``<module>.<name>`` per alias rather than as
    the module alone, because ``from app.sep import apps`` names the app tree in
    the alias and would otherwise resolve to the innocent ``app.sep``. The extra
    trailing segment is harmless under a prefix rule: an imported symbol reads as
    one level deeper than its module. A relative form resolves against
    ``package`` first, so ``from .sep.apps.atw.factories import X`` is classified
    exactly as its absolute spelling would be.

    Descends the whole tree, so an import nested in a class body, a function
    body, or an ``if TYPE_CHECKING:`` guard is reported like any other.

    :param source: The module source to parse.
    :param package: The dotted package the importing module belongs to.
    :yield: A dotted import target with its line number.
    """
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            base = _absolute_base(node, package)
            if base:
                for alias in node.names:
                    yield f"{base}.{alias.name}", node.lineno


def _is_forbidden(module: str) -> bool:
    """Report whether ``module`` names the activatable-app tree.

    Matches a prefix exactly or on a dotted boundary, so a sibling package whose
    name merely starts with a forbidden prefix is left alone.

    :param module: The dotted module path an import declares.
    :return: Whether the path is an app-tree package or one of its submodules.
    """
    return any(
        module == prefix or module.startswith(f"{prefix}.")
        for prefix in FORBIDDEN_PREFIXES
    )


def _shared_module_paths(root: Path) -> list[Path]:
    """Return every module sitting directly at the root of the test tree.

    The scan is not recursive: modules deeper in the tree are scoped to a
    subtree and may legitimately import the app they test.

    :param root: The test-tree root to scan.
    :return: The source paths subject to the app-agnostic rule.
    """
    return sorted(root.glob("*.py"))


def _package_of(path: Path, base: Path) -> str:
    """Return the dotted package a module resolves its relative imports against.

    :param path: The source path to derive the package from.
    :param base: The directory the path is dotted relative to.
    :return: The dotted package name, which for an ``__init__.py`` is its own
        directory.
    """
    return ".".join(path.relative_to(base).parts[:-1])


def _violations(root: Path, base: Path) -> list[str]:
    """Collect every app-tree import declared by a shared test module.

    :param root: The test-tree root whose modules are subject to the rule.
    :param base: The directory reported paths and dotted packages resolve against.
    :return: One ``path:line -> module`` entry per violating import.
    """
    return [
        f"{path.relative_to(base)}:{lineno} -> {module}"
        for path in _shared_module_paths(root)
        for module, lineno in _imported_modules(
            path.read_text(encoding="utf-8"), _package_of(path, base)
        )
        if _is_forbidden(module)
    ]


def _write_shared_module(base: Path, relative_path: str, source: str) -> Path:
    """Write ``source`` into a throwaway tree mirroring the real test-root layout.

    The tree is rooted at ``tests/app`` under ``base`` so a synthetic module derives
    the same dotted package -- and so reports the same relative path -- as its real
    counterpart would.

    :param base: The directory standing in for the repository root.
    :param relative_path: The module's path relative to the synthetic test root.
    :param source: The module source to write.
    :return: The synthetic test root to scan.
    """
    root = base / "tests" / "app"
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return root


class TestSharedTestModulesStayAppAgnostic:
    """Check that the root of the test tree declares no app-tree imports."""

    def test_no_shared_test_module_imports_the_app_tree(self) -> None:
        """Reject every import of the activatable-app tree from the test root."""
        violations = _violations(SHARED_TEST_ROOT, BASE_DIR)
        assert not violations, (
            "modules directly under tests/app/ are shared by the whole test tree"
            " and must not import app.sep.apps.*; move the factory or fixture"
            " into tests/app/sep/apps/<app>/factories.py:\n" + "\n".join(violations)
        )

    def test_the_shared_factory_module_is_in_scope(self) -> None:
        """Keep the rule anchored to the module it exists to protect."""
        assert SHARED_TEST_ROOT / "factories.py" in _shared_module_paths(
            SHARED_TEST_ROOT
        )


class TestViolationReporting:
    """Check the report a synthetic test root produces, end to end."""

    def test_forbidden_absolute_import_is_reported(self, tmp_path: Path) -> None:
        """Report a shared module's app-tree import as ``path:line -> module``."""
        root = _write_shared_module(
            tmp_path, "factories.py", "from app.sep.apps.atw.models import AtwIncident"
        )
        assert _violations(root, tmp_path) == [
            "tests/app/factories.py:1 -> app.sep.apps.atw.models.AtwIncident"
        ]

    def test_relative_re_export_is_reported(self, tmp_path: Path) -> None:
        """Resolve a relative re-export against the importing module's package."""
        root = _write_shared_module(
            tmp_path,
            "conftest.py",
            "from .sep.apps.atw.factories import AtwIncidentFactory",
        )
        assert _violations(root, tmp_path) == [
            "tests/app/conftest.py:1 -> "
            "tests.app.sep.apps.atw.factories.AtwIncidentFactory"
        ]

    def test_module_below_the_root_is_out_of_scope(self, tmp_path: Path) -> None:
        """Leave a module deeper in the tree free to import the app it tests."""
        root = _write_shared_module(
            tmp_path,
            "sep/apps/atw/factories.py",
            "from app.sep.apps.atw.models import AtwIncident",
        )
        assert _violations(root, tmp_path) == []

    def test_clean_tree_yields_no_violations(self, tmp_path: Path) -> None:
        """Accept a shared module that imports only core and shared names."""
        root = _write_shared_module(
            tmp_path,
            "factories.py",
            "from app.tasks.models import Task\nfrom tests.app.factories import Mock\n",
        )
        assert _violations(root, tmp_path) == []


class TestForbiddenImportDetection:
    """Check the walker over each import spelling the rule must classify."""

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            pytest.param(
                "from app.sep.apps.alters.models import AltersCreate",
                {"app.sep.apps.alters.models.AltersCreate"},
                id="submodule-from-import",
            ),
            pytest.param(
                "from app.sep.apps import alters",
                {"app.sep.apps.alters"},
                id="package-level-from-import",
            ),
            pytest.param(
                "from app.sep import apps",
                {"app.sep.apps"},
                id="app-tree-named-only-in-the-alias",
            ),
            pytest.param(
                "import app.sep.apps.atw.models",
                {"app.sep.apps.atw.models"},
                id="plain-import",
            ),
            pytest.param(
                "import app.sep.apps.atw.models as atw_models",
                {"app.sep.apps.atw.models"},
                id="aliased-plain-import",
            ),
            pytest.param(
                "from app.sep.apps.atw import models as atw_models",
                {"app.sep.apps.atw.models"},
                id="aliased-from-import",
            ),
            pytest.param(
                "from app.sep.apps.atw.models import *",
                {"app.sep.apps.atw.models.*"},
                id="star-import-naming-an-app-module",
            ),
            pytest.param(
                "from tests.app.sep.apps.atw.factories import AtwIncidentFactory",
                {"tests.app.sep.apps.atw.factories.AtwIncidentFactory"},
                id="relocated-factory-re-export",
            ),
            pytest.param(
                "from .sep.apps.atw.factories import AtwIncidentFactory",
                {"tests.app.sep.apps.atw.factories.AtwIncidentFactory"},
                id="relative-re-export",
            ),
            pytest.param(
                "from .sep.apps import atw",
                {"tests.app.sep.apps.atw"},
                id="relative-package-level-from-import",
            ),
            pytest.param(
                "from .factories import TaskFactory",
                set(),
                id="relative-sibling-module",
            ),
            pytest.param(
                "from ... import conftest",
                set(),
                id="relative-level-past-the-package-root",
            ),
            pytest.param(
                "from app.sep.apps.framework.registry import get_app_registry",
                {"app.sep.apps.framework.registry.get_app_registry"},
                id="infrastructure-package-is-not-exempt",
            ),
            pytest.param(
                "if TYPE_CHECKING:\n"
                "    from app.sep.apps.alters.models import AltersCreate\n",
                {"app.sep.apps.alters.models.AltersCreate"},
                id="type-checking-guard",
            ),
            pytest.param(
                "def _build():\n"
                "    from app.sep.apps.alters.models import AltersCreate\n",
                {"app.sep.apps.alters.models.AltersCreate"},
                id="function-body",
            ),
            pytest.param(
                "class Holder:\n"
                "    from app.sep.apps.alters.models import AltersCreate\n",
                {"app.sep.apps.alters.models.AltersCreate"},
                id="class-body",
            ),
            pytest.param(
                "from app.tasks.models import Task",
                set(),
                id="core-module",
            ),
            pytest.param(
                "from app.sep.inventory import CreatedNode",
                set(),
                id="sep-outside-the-app-tree",
            ),
            pytest.param(
                "from tests.app.factories import TaskFactory",
                set(),
                id="shared-test-factories",
            ),
            pytest.param(
                "from app.sep.appsx.models import Thing",
                set(),
                id="prefix-boundary",
            ),
            pytest.param(
                'import_module("app.sep.apps.alters.models")',
                set(),
                id="dynamic-literal-target-is-not-caught",
            ),
        ],
    )
    def test_source_resolves_the_expected_forbidden_modules(
        self, source: str, expected: set[str]
    ) -> None:
        """Resolve a forbidden module only for the spellings the rule covers."""
        package = _package_of(SHARED_TEST_ROOT / "factories.py", BASE_DIR)
        found = {
            module
            for module, _ in _imported_modules(source, package)
            if _is_forbidden(module)
        }
        assert found == expected
