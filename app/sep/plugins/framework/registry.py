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

"""Define the ``AppRegistry`` that drives SEP app mounting and metadata.

The registry is the single iteration source for both mount loops and every
``SEP.PLUGINS`` metadata consumer. It imports each activated module and either
uses its exported ``app`` definition or synthesizes an implicit
:class:`~app.sep.plugins.framework.base.BaseApp` from the legacy ``Plugin``
settings entry, so legacy and definition-based apps coexist.

:func:`get_app_registry` is a lazy ``@lru_cache`` accessor rather than an eager
module-level singleton: building the registry imports every plugin module, and
two consumers (``app/sep/deps.py`` and ``app/sep/db/seed.py``) are themselves
imported before plugin modules can be safely imported. The lazy accessor defers
the build to first call -- the same point ``plugins_router`` is built today,
after ``deps``/``config`` finish importing -- mirroring the filesystem-probe
trick in ``Plugin._default_api_router_from_convention`` that avoids circular
imports through plugin ``__init__`` modules.
"""

from collections.abc import Iterable, Iterator
from functools import lru_cache
from importlib import import_module

from fastapi import APIRouter

from app.core.utils import import_var
from app.sep.config import Plugin, sep_settings
from app.sep.plugins.framework.base import BaseApp


class AppRegistry:
    """Represent an ordered, key-addressable collection of mounted apps.

    Iteration order equals activation-list order; the byte-for-byte OpenAPI
    no-op for mounted plugin routes depends on it.

    :param apps: The mounted apps, in activation order.
    :type apps: list[BaseApp]
    """

    def __init__(self, apps: list[BaseApp]) -> None:
        self._apps = apps
        self._by_key = {app.key: app for app in apps}

    def __iter__(self) -> Iterator[BaseApp]:
        return iter(self._apps)

    def keys(self) -> list[str]:
        """Return every app key in activation order.

        :return: The app keys.
        :rtype: list[str]
        """
        return [app.key for app in self._apps]

    def get(self, key: str) -> BaseApp | None:
        """Return the app registered under ``key``, or ``None`` if absent.

        :param key: The app key to look up.
        :type key: str
        :return: The registered app, or ``None``.
        :rtype: BaseApp | None
        """
        return self._by_key.get(key)


def _synthesize_legacy_app(plugin: Plugin, key: str) -> BaseApp:
    """Wrap a legacy ``Plugin`` settings entry as an implicit ``BaseApp``.

    Preserve the fail-fast ``TypeError`` that ``build_plugins_router`` raised
    when ``api_router_path`` resolves to a non-``APIRouter``.

    :param plugin: The legacy plugin settings entry.
    :type plugin: Plugin
    :param key: The module basename used as the app key.
    :type key: str
    :return: The synthesized app.
    :rtype: BaseApp
    :raises TypeError: When ``api_router_path`` resolves to a non-``APIRouter``.
    """
    api_router = import_var(plugin.api_router_path) if plugin.api_router_path else None
    if api_router is not None and not isinstance(api_router, APIRouter):
        raise TypeError(
            f"Plugin '{key}': '{plugin.api_router_path}' must resolve to an"
            f" APIRouter, got {type(api_router).__name__}"
        )
    return BaseApp(
        key=key,
        name=plugin.name or key,
        uri_path=str(plugin.uri_path) if plugin.uri_path else f"/{key}",
        css_class=plugin.css_class or key,
        sidebar=plugin.sidebar,
        enabled=plugin.enabled,
        api_router=api_router,
        jinja_router=import_var(plugin.router_path),
    )


def _bind_definition(definition: BaseApp, plugin: Plugin, key: str) -> BaseApp:
    """Bind an exported ``BaseApp`` definition to its activation entry.

    Stamp the activation-list facts (``key``, ``enabled``) and let explicit
    legacy ``Plugin`` keys override the definition's descriptive metadata, so an
    un-migrated ``settings.yaml`` entry keeps controlling the transition.

    :param definition: The app definition exported by the module.
    :type definition: BaseApp
    :param plugin: The activation entry for the module.
    :type plugin: Plugin
    :param key: The module basename used as the app key.
    :type key: str
    :return: The bound app.
    :rtype: BaseApp
    """
    overrides = {"key": key, "enabled": plugin.enabled}
    if plugin.name:
        overrides["name"] = plugin.name
        if definition.display_name == definition.name:
            overrides["display_name"] = plugin.name
    if plugin.uri_path:
        overrides["uri_path"] = str(plugin.uri_path)
    if plugin.css_class:
        overrides["css_class"] = plugin.css_class
    if "sidebar" in plugin.model_fields_set:
        overrides["sidebar"] = plugin.sidebar
    return definition.model_copy(update=overrides)


def build_app_registry(plugins: Iterable[Plugin]) -> AppRegistry:
    """Build an :class:`AppRegistry` from an activation list.

    Import each module and either use its exported ``app`` definition or
    synthesize an implicit app from the legacy settings entry. Pure function of
    the activation list -- unit tests call it directly.

    :param plugins: The ``SEP.PLUGINS`` activation entries, in order.
    :type plugins: Iterable[Plugin]
    :return: The ordered registry.
    :rtype: AppRegistry
    """
    apps = []
    for plugin in plugins:
        key = plugin.module_name.split(".")[-1]
        definition = getattr(import_module(plugin.module_name), "app", None)
        if isinstance(definition, BaseApp):
            apps.append(_bind_definition(definition, plugin, key))
        else:
            apps.append(_synthesize_legacy_app(plugin, key))
    return AppRegistry(apps)


@lru_cache(maxsize=1)
def get_app_registry() -> AppRegistry:
    """Return the process-wide registry built over ``sep_settings.PLUGINS``.

    Cached so the module-importing build runs once. ``cache_clear()`` resets it
    between tests.

    :return: The cached registry.
    :rtype: AppRegistry
    """
    return build_app_registry(sep_settings.PLUGINS)
