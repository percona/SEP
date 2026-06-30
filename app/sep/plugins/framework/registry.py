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
:class:`~app.sep.plugins.framework.base.BaseApp` from the legacy ``App``
settings entry, so legacy and definition-based apps coexist.

:func:`get_app_registry` is a lazy ``@lru_cache`` accessor rather than an eager
module-level singleton: building the registry imports every plugin module, and
two consumers (``app/sep/deps.py`` and ``app/sep/db/seed.py``) are themselves
imported before plugin modules can be safely imported. The lazy accessor defers
the build to first call -- the same point ``apps_router`` is built today,
after ``deps``/``config`` finish importing -- mirroring the filesystem-probe
trick in ``App._default_api_router_from_convention`` that avoids circular
imports through plugin ``__init__`` modules.
"""

from collections.abc import Iterable, Iterator
from functools import lru_cache
from importlib import import_module

from fastapi import APIRouter

from app.core.utils import import_var
from app.sep.config import App, sep_settings
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


def _derive_app_key(module_name: str) -> str:
    """Derive the scoped app key from a plugin's full module path.

    Strip the shared ``app.sep.plugins.`` package prefix and map the remaining
    dotted path to a ``/``-joined key. Top-level modules stay single-segment
    (``…mysql_backups`` -> ``mysql_backups``); nested sub-apps become scoped
    (``…mysql_backups.restore`` -> ``mysql_backups/restore``), so the JSON mount
    and admin toggle address the sub-app under its own namespace.

    :param module_name: The plugin's full import path.
    :return: The auto-derived scoped app key.
    """
    return module_name.removeprefix("app.sep.plugins.").replace(".", "/")


def _synthesize_legacy_app(plugin: App, auto_key: str) -> BaseApp:
    """Wrap a legacy ``App`` settings entry as an implicit ``BaseApp``.

    Preserve the fail-fast ``TypeError`` that ``build_apps_router`` raised
    when ``api_router_path`` resolves to a non-``APIRouter``.

    :param plugin: The legacy plugin settings entry.
    :type plugin: App
    :param auto_key: The scoped app key derived from the module path.
    :return: The synthesized app.
    :rtype: BaseApp
    :raises TypeError: When ``api_router_path`` resolves to a non-``APIRouter``.
    """
    api_router = import_var(plugin.api_router_path) if plugin.api_router_path else None
    if api_router is not None and not isinstance(api_router, APIRouter):
        raise TypeError(
            f"App '{auto_key}': '{plugin.api_router_path}' must resolve to an"
            f" APIRouter, got {type(api_router).__name__}"
        )
    return BaseApp(
        key=auto_key,
        name=plugin.name or auto_key,
        uri_path=str(plugin.uri_path) if plugin.uri_path else f"/{auto_key}",
        css_class=plugin.css_class or auto_key,
        sidebar=plugin.sidebar,
        group=plugin.group,
        nav_order=plugin.nav_order,
        enabled=plugin.enabled,
        api_router=api_router,
        jinja_router=import_var(plugin.router_path),
    )


def _bind_definition(definition: BaseApp, plugin: App, auto_key: str) -> BaseApp:
    """Bind an exported ``BaseApp`` definition to its activation entry.

    Stamp the activation-list facts (``key``, ``enabled``) and let explicit
    legacy ``App`` keys override the definition's descriptive metadata, so an
    un-migrated ``settings.yaml`` entry keeps controlling the transition. A
    definition that sets its own ``key`` keeps it; otherwise the module-derived
    scoped key is stamped.

    :param definition: The app definition exported by the module.
    :type definition: BaseApp
    :param plugin: The activation entry for the module.
    :type plugin: App
    :param auto_key: The scoped app key derived from the module path.
    :return: The bound app.
    :rtype: BaseApp
    """
    overrides = {"key": definition.key or auto_key, "enabled": plugin.enabled}
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
    if "group" in plugin.model_fields_set:
        overrides["group"] = plugin.group
    if "nav_order" in plugin.model_fields_set:
        overrides["nav_order"] = plugin.nav_order
    return definition.model_copy(update=overrides)


def build_app_registry(plugins: Iterable[App]) -> AppRegistry:
    """Build an :class:`AppRegistry` from an activation list.

    Import each module and either use its exported ``app`` definition or
    synthesize an implicit app from the legacy settings entry. Pure function of
    the activation list -- unit tests call it directly.

    :param plugins: The ``SEP.PLUGINS`` activation entries, in order.
    :type plugins: Iterable[App]
    :return: The ordered registry.
    :rtype: AppRegistry
    """
    apps = []
    for plugin in plugins:
        auto_key = _derive_app_key(plugin.module_name)
        definition = getattr(import_module(plugin.module_name), "app", None)
        if isinstance(definition, BaseApp):
            apps.append(_bind_definition(definition, plugin, auto_key))
        else:
            apps.append(_synthesize_legacy_app(plugin, auto_key))
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
