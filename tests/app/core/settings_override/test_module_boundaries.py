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

"""Test how the settings-override substrate is split across its modules."""

import ast
import functools
import inspect
import pkgutil
import subprocess
import sys
from types import ModuleType

import pytest

import app.core.settings_override as package
from app.core.settings_override import (
    constants,
    registry,
    resolution,
    secret_preservation,
)

#: The only definition the classification registry may pull back out of the
#: resolution module. Anything else means the layering has started to rot.
REGISTRY_BACK_IMPORTS = frozenset({"resolve_nested_segments"})

#: Imports the resolution module first, then calls the one function whose
#: registry import is deferred, so the deferred import runs while resolution is
#: the module that owns the interpreter's entry point.
DEFERRED_IMPORT_PROBE = """
import app.core.settings_override.resolution as resolution
from pydantic import BaseModel

from app.core.settings_override.registry import hot_field, nested_overridable_field


class Leaf(BaseModel):
    depth: int = hot_field(1)


class Root(BaseModel):
    leaf: Leaf = nested_overridable_field(Leaf())


metadata = resolution.resolve_nested_field_metadata(Root, "leaf__depth")
assert metadata is not None, "nested key did not resolve"
assert metadata.key == "leaf__depth", metadata.key
"""

NEW_MODULES = (resolution, secret_preservation)


def _package_module_names() -> list[str]:
    """Return every importable module in the settings-override package.

    :return: Dotted module names, the package itself included.
    """
    return [
        package.__name__,
        *sorted(
            info.name
            for info in pkgutil.walk_packages(package.__path__, f"{package.__name__}.")
        ),
    ]


@functools.cache
def _declared_names(module: ModuleType) -> frozenset[str]:
    """Return the names ``module`` binds at its own top level.

    Attribution cannot go through ``__module__``: only functions and classes
    carry it, so a borrowed constant — the kind of symbol this split was most
    careful about — would read as owned by whichever module imported it, and a
    module's own constant would read as borrowed. Parsing the source answers
    the question the tests actually ask, for every kind of definition.

    :param module: The module whose source to parse.
    :return: Every name bound by a top-level statement other than an import.
    """
    names: set[str] = set()
    for node in ast.parse(inspect.getsource(module)).body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Assign):
            names.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
    return frozenset(names)


def _borrowed_from(module: ModuleType, sources: tuple[ModuleType, ...]) -> set[str]:
    """Return the names ``module`` imported from ``sources``.

    A name counts as borrowed when a source owns it — declares it, or exports
    it — and ``module`` is bound to that same object, so a relayed constant is
    caught alongside a relayed function. Names the module declares itself are
    excluded, and so are the third-party imports both modules happen to share.

    :param module: The importing module.
    :param sources: The modules whose definitions to look for.
    :return: Every name in ``module`` bound to a definition one of ``sources`` owns.
    """
    unbound = object()
    own = _declared_names(module)
    owned_by = {
        source: _declared_names(source) | set(getattr(source, "__all__", ()))
        for source in sources
    }
    return {
        name
        for name, value in vars(module).items()
        if name not in own
        and any(
            name in names and value is getattr(source, name, unbound)
            for source, names in owned_by.items()
        )
    }


class TestSymbolOwnership:
    """Cover which module each moved symbol belongs to."""

    @pytest.mark.parametrize(
        "module", NEW_MODULES, ids=["resolution", "secret-preservation"]
    )
    def test_module_defines_everything_it_exports(self, module: ModuleType) -> None:
        """Assert a module owns its exports instead of re-exporting them.

        :param module: One of the two modules carved out of the registry.
        :return: ``None``.
        """
        owned = _declared_names(module)
        borrowed = sorted(name for name in module.__all__ if name not in owned)
        assert not borrowed, borrowed

    def test_registry_borrows_only_the_one_resolution_helper(self) -> None:
        """Assert the registry keeps exactly one back-import from the new modules.

        Asserted dynamically rather than against a symbol list so a later
        rename stays free while a new cross-module import does not.
        """
        assert _borrowed_from(registry, NEW_MODULES) == REGISTRY_BACK_IMPORTS

    def test_field_resolution_helper_is_public_everywhere(self) -> None:
        """Assert the cross-module helper carries its public name only.

        A half-applied rename would leave callers importing a private alias
        that still exists, so the old name has to be gone from every namespace
        that used to expose it.
        """
        assert callable(resolution.resolve_field_in_model)
        for module in (registry, resolution):
            assert "_resolve_field_in_model" not in vars(module)


class TestExportLists:
    """Cover the ``__all__`` contract of the three modules."""

    @pytest.mark.parametrize(
        "module",
        [package, registry, *NEW_MODULES],
        ids=["package", "registry", "resolution", "secret-preservation"],
    )
    def test_every_export_resolves(self, module: ModuleType) -> None:
        """Assert each exported name exists on its module.

        The package is checked alongside the three modules because its
        ``__init__`` re-export list is what consumers outside the package
        import from, and a symbol that moves between modules can be dropped
        from it without any module-level import failing.

        :param module: The module whose ``__all__`` to check.
        :return: ``None``.
        """
        unresolved = sorted(
            name for name in module.__all__ if not hasattr(module, name)
        )
        assert not unresolved, unresolved

    def test_registry_exports_nothing_it_no_longer_owns(self) -> None:
        """Assert the registry stops advertising the moved public API."""
        moved = set(resolution.__all__) | set(secret_preservation.__all__)
        assert not set(registry.__all__) & moved


class TestImportCycles:
    """Cover importing each module first in a fresh interpreter."""

    @pytest.mark.parametrize("module_name", _package_module_names())
    def test_module_imports_standalone(self, module_name: str) -> None:
        """Assert the module imports with nothing else imported first.

        The registry and resolution modules import each other, so the entry
        point decides which one is left partially initialized: only a fresh
        interpreter per entry point can catch that. Every module in the package
        is an entry point in production — the API routes and the cache reach
        the pair before anything else does — and the list is discovered rather
        than written down so a module added later cannot opt out.

        :param module_name: The module to import as the interpreter's first act.
        :return: ``None``.
        """
        result = subprocess.run(
            [sys.executable, "-c", f"import {module_name}"],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr

    def test_the_deferred_registry_import_resolves_when_it_runs(self) -> None:
        """Assert the cycle-breaking import still resolves at call time.

        Importing a module only proves the deferred import was not hoisted back
        to module scope. The import inside ``resolve_nested_field_metadata``
        does not run until the function is called, so a name the registry stops
        exporting would surface on the first LIST request instead of at
        startup — after every import test has already passed.
        """
        result = subprocess.run(
            [sys.executable, "-c", DEFERRED_IMPORT_PROBE],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr


class TestSharedSentinel:
    """Cover the identity of the missing-value sentinel after the split."""

    def test_every_module_sees_one_sentinel_object(self) -> None:
        """Assert the sentinel stays a single object across its re-exports.

        Callers compare it with ``is``, so a duplicated ``object()`` would make
        a missing nested segment read as a present value. The package re-export
        is included because that is the path most consumers take.
        """
        assert (
            constants.NESTED_VALUE_MISSING
            is resolution.NESTED_VALUE_MISSING
            is package.NESTED_VALUE_MISSING
        )

    def test_the_registry_no_longer_relays_the_sentinel(self) -> None:
        """Assert readers reach the sentinel through the module that owns it.

        The sentinel was moved to a leaf module precisely so no reader has to
        import it from a module that may still be initializing; a relay left on
        the registry would hand that hazard back to every consumer that keeps
        using it.
        """
        assert "NESTED_VALUE_MISSING" not in vars(registry)
        assert "NESTED_VALUE_MISSING" not in registry.__all__
