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

#: Symbols that must live in the resolution module. ``_resolve_nested_segments``
#: is imported back by the registry, so ownership is asserted on ``__module__``
#: rather than on absence from the registry namespace.
RESOLUTION_SYMBOLS = frozenset(
    {
        "_mapping_segment_or_default",
        "_provenance_keys_for_row",
        "_resolve_nested_segments",
        "_stored_key_matches_override_key",
        "canonical_override_key",
        "override_provenance_for_rows",
        "override_rows_for_key",
        "resolve_field_in_model",
        "resolve_nested_field",
        "resolve_nested_field_metadata",
        "resolve_nested_value",
        "SettingProvenance",
    }
)

#: Symbols the registry may keep importing after the split.
REGISTRY_REIMPORTS = frozenset({"_resolve_nested_segments"})

SECRET_PRESERVATION_SYMBOLS = frozenset(
    {
        "_annotation_collection_element_model",
        "_annotation_is_secret_valued_dict",
        "_annotation_is_secret_valued_sequence",
        "_collection_discriminator_candidates",
        "_collection_item_value_score",
        "_match_by_field_name_overlap",
        "_match_collection_item_index",
        "_pick_best_scored_index",
        "_preserve_masked_secret_scalar",
        "_preserve_secrets_in_dict_payload",
        "_preserve_secrets_in_secret_sequence_payload",
        "_preserve_secrets_in_sequence_payload",
        "_read_mapping_or_model_attr",
        "_stable_collection_items",
        "preserve_credential_urls_in_model_payload",
        "preserve_patch_credential_url_value",
        "preserve_patch_secret_value",
        "preserve_secrets_in_model_payload",
    }
)


def _owned(module: ModuleType, symbols: frozenset[str]) -> None:
    """Assert ``module`` defines every symbol in ``symbols`` itself.

    :param module: The module expected to own the symbols.
    :param symbols: The symbol names to check.
    :return: ``None``; raises ``AssertionError`` on the first mismatch.
    """
    missing = sorted(name for name in symbols if name not in vars(module))
    assert not missing, f"{module.__name__} is missing {missing}"
    foreign = sorted(
        name
        for name in symbols
        if getattr(vars(module)[name], "__module__", module.__name__) != module.__name__
    )
    assert not foreign, f"{module.__name__} does not define {foreign}"


class TestSymbolOwnership:
    """Cover which module each moved symbol belongs to."""

    def test_resolution_owns_the_nested_key_cluster(self) -> None:
        """Assert the resolution module defines the whole nested-key cluster."""
        _owned(resolution, RESOLUTION_SYMBOLS)

    def test_registry_no_longer_defines_the_nested_key_cluster(self) -> None:
        """Assert the registry keeps only the re-imports it needs."""
        leftover = sorted(
            name
            for name in RESOLUTION_SYMBOLS - REGISTRY_REIMPORTS
            if name in vars(registry)
        )
        assert not leftover

    def test_secret_preservation_owns_the_patch_restore_cluster(self) -> None:
        """Assert the preservation module defines the whole PATCH-restore cluster."""
        _owned(secret_preservation, SECRET_PRESERVATION_SYMBOLS)

    def test_registry_no_longer_defines_the_patch_restore_cluster(self) -> None:
        """Assert no preservation symbol is reachable through the registry."""
        leftover = sorted(
            name for name in SECRET_PRESERVATION_SYMBOLS if name in vars(registry)
        )
        assert not leftover

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
        [registry, resolution, secret_preservation],
        ids=["registry", "resolution", "secret-preservation"],
    )
    def test_every_export_resolves(self, module: ModuleType) -> None:
        """Assert each exported name exists on its module."""
        unresolved = sorted(
            name for name in module.__all__ if not hasattr(module, name)
        )
        assert not unresolved

    def test_registry_exports_no_moved_symbol(self) -> None:
        """Assert the registry stops advertising what it no longer owns."""
        moved = RESOLUTION_SYMBOLS | SECRET_PRESERVATION_SYMBOLS
        assert not sorted(set(registry.__all__) & moved)

    def test_new_modules_export_their_public_symbols(self) -> None:
        """Assert every public moved symbol is exported by its new module."""
        for module, symbols in (
            (resolution, RESOLUTION_SYMBOLS),
            (secret_preservation, SECRET_PRESERVATION_SYMBOLS),
        ):
            public = {name for name in symbols if not name.startswith("_")}
            assert public <= set(module.__all__)


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
        interpreter per order can catch that.
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
