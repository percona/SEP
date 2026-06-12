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

"""Tests for the ``AppRegistry`` and its builders in ``registry.py``."""

from types import SimpleNamespace

import pytest
from fastapi import APIRouter
from pytest_mock import MockerFixture

from app.sep.config import Plugin, sep_settings
from app.sep.plugins.framework.base import BaseApp
from app.sep.plugins.framework.registry import (
    AppRegistry,
    build_app_registry,
    get_app_registry,
)


@pytest.fixture(autouse=True)
def _clear_registry_cache() -> None:
    """Reset the cached registry so each test rebuilds from its own input."""
    get_app_registry.cache_clear()
    yield
    get_app_registry.cache_clear()


class TestLegacyWrapping:
    """Tests for synthesizing a ``BaseApp`` from a legacy ``Plugin``."""

    def test_legacy_plugin_wrapped_with_metadata(self) -> None:
        """A plugin with no ``app`` export is wrapped from its settings entry."""
        registry = build_app_registry(
            [Plugin(name="Checksums", module_name="checksums")]
        )
        app = registry.get("checksums")
        assert app is not None
        assert app.name == "Checksums"
        assert app.uri_path == "/checksums"
        assert app.css_class == "checksums"
        assert app.sidebar is True
        assert app.custom_ui is False
        assert app.app_schema is None

    def test_legacy_plugin_resolves_both_routers(self) -> None:
        """The synthesized app carries the resolved Jinja and API routers."""
        registry = build_app_registry(
            [Plugin(name="Checksums", module_name="checksums")]
        )
        app = registry.get("checksums")
        assert isinstance(app.jinja_router, APIRouter)
        assert isinstance(app.api_router, APIRouter)

    def test_module_name_only_derives_metadata(self) -> None:
        """A MODULE_NAME-only entry derives name/uri/css/display from the key."""
        registry = build_app_registry([Plugin(module_name="checksums")])
        app = registry.get("checksums")
        assert app.name == "checksums"
        assert app.uri_path == "/checksums"
        assert app.css_class == "checksums"
        assert app.display_name == "checksums"

    def test_api_router_is_none_when_opted_out(self) -> None:
        """A plugin opting out of the API mount carries ``api_router is None``."""
        registry = build_app_registry(
            [Plugin(name="Inventory", module_name="inventory", api_router_path=None)]
        )
        assert registry.get("inventory").api_router is None


class TestFailFast:
    """Tests for the fail-fast carried over from ``build_plugins_router``."""

    def test_non_router_attribute_raises_type_error(self) -> None:
        """An ``api_router_path`` resolving to a non-``APIRouter`` raises ``TypeError``."""
        plugin = Plugin(
            name="Checksums",
            module_name="checksums",
            api_router_path="app.sep.config.Plugin",
        )
        with pytest.raises(TypeError, match="checksums"):
            build_app_registry([plugin])

    def test_empty_string_api_router_path_is_no_mount(self) -> None:
        """An empty-string ``api_router_path`` yields ``api_router is None``."""
        plugin = Plugin.model_construct(
            name="Ghost",
            module_name="app.sep.plugins.checksums",
            api_router_path="",
        )
        registry = build_app_registry([plugin])
        assert registry.get("checksums").api_router is None


class TestOrderAndLookup:
    """Tests for activation-order preservation and key lookup."""

    def test_keys_preserve_activation_order(self) -> None:
        """``keys()`` mirrors the activation-list order (OpenAPI-critical)."""
        registry = build_app_registry(
            [
                Plugin(name="Inventory", module_name="inventory"),
                Plugin(name="Snippet Manager", module_name="snippets"),
                Plugin(name="Checksums", module_name="checksums"),
            ]
        )
        assert registry.keys() == ["inventory", "snippets", "checksums"]

    def test_iteration_yields_entries_in_order(self) -> None:
        """Iterating the registry yields ``BaseApp`` entries in order."""
        registry = build_app_registry(
            [
                Plugin(name="Inventory", module_name="inventory"),
                Plugin(name="Snippet Manager", module_name="snippets"),
            ]
        )
        assert [app.key for app in registry] == ["inventory", "snippets"]

    def test_protected_app_surfaces_like_any_other(self) -> None:
        """The protected ``inventory`` app is a normal registry entry."""
        registry = build_app_registry(
            [Plugin(name="Inventory", module_name="inventory")]
        )
        assert registry.get("inventory") is not None

    def test_get_returns_none_for_unknown_key(self) -> None:
        """An unconfigured key resolves to ``None``."""
        registry = build_app_registry(
            [Plugin(name="Inventory", module_name="inventory")]
        )
        assert registry.get("nonexistent") is None


class TestDefinitionCollection:
    """Tests for the future declarative-definition collection path."""

    @staticmethod
    def _patch_definition(mocker: MockerFixture, definition: BaseApp) -> None:
        """Make ``import_module`` return a stub module exporting ``definition``."""
        mocker.patch(
            "app.sep.plugins.framework.registry.import_module",
            return_value=SimpleNamespace(app=definition),
        )

    def test_exported_definition_is_used_and_stamped(
        self, mocker: MockerFixture
    ) -> None:
        """A module exporting ``app`` is used, with key/enabled stamped."""
        api_router = APIRouter()
        definition = BaseApp(
            name="internal",
            display_name="Internal Display",
            uri_path="/def-path",
            css_class="def-css",
            sidebar=False,
            custom_ui=True,
            api_router=api_router,
        )
        self._patch_definition(mocker, definition)

        registry = build_app_registry([Plugin(module_name="checksums")])
        app = registry.get("checksums")
        assert app.key == "checksums"
        assert app.enabled is True
        assert app.name == "internal"
        assert app.uri_path == "/def-path"
        assert app.sidebar is False
        assert app.custom_ui is True
        assert app.api_router is api_router
        assert app.display_name == "Internal Display"

    def test_explicit_yaml_keys_override_definition(
        self, mocker: MockerFixture
    ) -> None:
        """Explicit legacy YAML keys win over the definition's values."""
        definition = BaseApp(
            name="internal", uri_path="/def-path", css_class="def-css", custom_ui=True
        )
        self._patch_definition(mocker, definition)

        registry = build_app_registry(
            [Plugin(name="Yaml Override", module_name="checksums")]
        )
        app = registry.get("checksums")
        assert app.name == "Yaml Override"
        assert app.uri_path == "/yaml-override"
        assert app.css_class == "yaml-override"
        assert app.custom_ui is True
        assert app.display_name == "Yaml Override"

    def test_explicit_display_name_survives_yaml_name_override(
        self, mocker: MockerFixture
    ) -> None:
        """A definition's distinct ``display_name`` is kept when YAML overrides name."""
        definition = BaseApp(
            name="internal", display_name="Internal Display", uri_path="/def-path"
        )
        self._patch_definition(mocker, definition)

        registry = build_app_registry(
            [Plugin(name="Yaml Override", module_name="checksums")]
        )
        app = registry.get("checksums")
        assert app.name == "Yaml Override"
        assert app.display_name == "Internal Display"

    def test_enabled_stamped_from_activation_entry(self, mocker: MockerFixture) -> None:
        """A disabled activation entry stamps ``enabled=False`` on the definition."""
        definition = BaseApp(name="internal", uri_path="/def-path")
        self._patch_definition(mocker, definition)

        registry = build_app_registry([Plugin(module_name="checksums", enabled=False)])
        assert registry.get("checksums").enabled is False


class TestGetAppRegistry:
    """Tests for the lazy cached accessor over ``sep_settings.PLUGINS``."""

    def test_returns_registry_over_configured_plugins(self) -> None:
        """The accessor builds a registry covering every configured plugin."""
        registry = get_app_registry()
        assert isinstance(registry, AppRegistry)
        expected = [p.module_name.split(".")[-1] for p in sep_settings.PLUGINS]
        assert registry.keys() == expected

    def test_result_is_cached(self) -> None:
        """Repeated calls return the same cached instance."""
        assert get_app_registry() is get_app_registry()
