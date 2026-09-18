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

import subprocess
import sys
from types import ModuleType

import pytest

from app.core.settings_override import (
    constants,
    registry,
    resolution,
    secret_preservation,
)

#: The only definition the classification registry may pull back out of the
#: resolution module. Anything else means the layering has started to rot.
REGISTRY_BACK_IMPORTS = frozenset({"resolve_nested_segments"})

NEW_MODULES = (resolution, secret_preservation)


def _defines(module: ModuleType, name: str) -> bool:
    """Return whether ``module`` is where ``name`` is defined, not just visible.

    :param module: The module to inspect.
    :param name: The symbol name to attribute.
    :return: ``True`` when ``module`` declares the symbol itself.
    """
    value = vars(module).get(name)
    return value is not None and getattr(value, "__module__", None) == module.__name__


def _borrowed_from(module: ModuleType, sources: tuple[ModuleType, ...]) -> set[str]:
    """Return the names ``module`` imported from ``sources``.

    :param module: The importing module.
    :param sources: The modules whose definitions to look for.
    :return: Every name in ``module`` that one of ``sources`` defines.
    """
    origins = {source.__name__ for source in sources}
    return {
        name
        for name, value in vars(module).items()
        if getattr(value, "__module__", None) in origins
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
        borrowed = sorted(name for name in module.__all__ if not _defines(module, name))
        assert not borrowed

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
        [registry, *NEW_MODULES],
        ids=["registry", "resolution", "secret-preservation"],
    )
    def test_every_export_resolves(self, module: ModuleType) -> None:
        """Assert each exported name exists on its module.

        :param module: The module whose ``__all__`` to check.
        :return: ``None``.
        """
        unresolved = sorted(
            name for name in module.__all__ if not hasattr(module, name)
        )
        assert not unresolved

    def test_registry_exports_nothing_it_no_longer_owns(self) -> None:
        """Assert the registry stops advertising the moved public API."""
        moved = set(resolution.__all__) | set(secret_preservation.__all__)
        assert not sorted(set(registry.__all__) & moved)


class TestImportCycles:
    """Cover importing each module first in a fresh interpreter."""

    @pytest.mark.parametrize(
        "module_name",
        [
            "app.core.settings_override",
            "app.core.settings_override.registry",
            "app.core.settings_override.resolution",
            "app.core.settings_override.secret_preservation",
        ],
    )
    def test_module_imports_standalone(self, module_name: str) -> None:
        """Assert the module imports with nothing else imported first.

        The registry and resolution modules import each other, so the entry
        point decides which one is left partially initialized: only a fresh
        interpreter per entry point can catch that.

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


class TestSharedSentinel:
    """Cover the identity of the missing-value sentinel after the split."""

    def test_every_module_sees_one_sentinel_object(self) -> None:
        """Assert the sentinel stays a single object across its re-exports.

        Callers compare it with ``is``, so a duplicated ``object()`` would make
        a missing nested segment read as a present value.
        """
        assert (
            constants.NESTED_VALUE_MISSING
            is registry.NESTED_VALUE_MISSING
            is resolution.NESTED_VALUE_MISSING
        )
