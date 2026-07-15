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
``SEP.APPS`` metadata consumer. It imports each activated module and either
uses its exported ``app`` definition or synthesizes an implicit
:class:`~app.sep.apps.framework.base.BaseApp` from the legacy ``App``
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
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.celery.config import STATIC_CELERY_INCLUDE
from app.core.settings_override.api.models import SettingClassAppMetadata
from app.core.settings_override.api.routes import AppOwnedClassEntry
from app.core.settings_override.models import SettingClassEnum
from app.core.utils import import_var
from app.sep.apps.framework.base import BaseApp
from app.sep.config import App, sep_settings
from app.sep.crud import AppStateManager
from app.sep.deps import PROTECTED_APP_KEYS


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

    Strip the shared ``app.sep.apps.`` package prefix and map the remaining
    dotted path to a ``/``-joined key. Top-level modules stay single-segment
    (``…mysql_backups`` -> ``mysql_backups``); nested sub-apps become scoped
    (``…mysql_backups.restore`` -> ``mysql_backups/restore``), so the JSON mount
    and admin toggle address the sub-app under its own namespace.

    :param module_name: The plugin's full import path.
    :return: The auto-derived scoped app key.
    """
    return module_name.removeprefix("app.sep.apps.").replace(".", "/")


def app_celery_module_paths(plugins: Iterable[App] | None = None) -> list[str]:
    """Return the ordered app-owned Celery module paths for an activation list.

    Read from each entry's ``App.celery_module_path`` (the single, filesystem-derived
    source). Pure and **import-free** -- it never imports a plugin module, so it is
    safe to call while the Celery app is being assembled (``app/celery.py``), before
    the full registry (which imports every plugin) can be built.

    :param plugins: The activation entries to scan. Defaults to ``sep_settings.APPS``.
    :return: The app Celery module import paths, in activation order.
    """
    plugins = sep_settings.APPS if plugins is None else plugins
    return [p.celery_module_path for p in plugins if p.celery_module_path]


def app_celery_module_for(
    app_key: str,
    plugins: Iterable[App] | None = None,
) -> str | None:
    """Return the Celery module path owned by ``app_key``, or ``None``.

    Keyed by the same scoped key derivation the registry uses
    (:func:`_derive_app_key`), so the beat seed can source an app-owned
    ``task_name`` prefix from the identical origin as the include list.

    :param app_key: The scoped app key (e.g. ``"snippets"``).
    :param plugins: The activation entries to scan. Defaults to ``sep_settings.APPS``.
    :return: The app's Celery module path, or ``None`` when the app is unknown,
        ships no ``celery.py``, or opted out.
    """
    plugins = sep_settings.APPS if plugins is None else plugins
    for plugin in plugins:
        if _derive_app_key(plugin.module_name) == app_key:
            return plugin.celery_module_path
    return None


def build_celery_include(plugins: Iterable[App] | None = None) -> list[str]:
    """Compose the full Celery ``include`` list: static base + app modules.

    The single seam both the Celery-app assembly (``app/celery.py``) and the worker
    bootstrap (``start_celery_worker``) call, so the two can never drift.

    :param plugins: The activation entries to scan. Defaults to ``sep_settings.APPS``.
    :return: The static service modules followed by the registry-derived app modules,
        deduplicated while preserving first-seen order.
    """
    return list(
        dict.fromkeys([*STATIC_CELERY_INCLUDE, *app_celery_module_paths(plugins)])
    )


def _synthesize_legacy_app(plugin: App, auto_key: str) -> BaseApp:
    """Wrap a legacy ``App`` settings entry as an implicit ``BaseApp``.

    Preserve the fail-fast ``TypeError`` that ``build_apps_router`` raised
    when ``api_router_path`` resolves to a non-``APIRouter``.

    :param plugin: The legacy plugin settings entry.
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
        react_route=plugin.react_route,
        nav_icon=plugin.nav_icon,
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
    if "react_route" in plugin.model_fields_set:
        overrides["react_route"] = plugin.react_route
    if "nav_icon" in plugin.model_fields_set:
        overrides["nav_icon"] = plugin.nav_icon
    return definition.model_copy(update=overrides)


def _bind_child_apps(parent: BaseApp) -> list[BaseApp]:
    """Return a parent's ``child_apps`` stamped for registration.

    Each child inherits the parent's activation state (``enabled``) so it is
    mounted and snapshotted exactly when the parent is. A child owns no
    ``settings.yaml`` entry, so it carries its own scoped ``key`` and must name
    the parent via ``parent_key``.

    :param parent: The bound parent app whose children are being registered.
    :return: The parent's children, each with ``enabled`` stamped from the parent.
    :raises ValueError: When a child's ``parent_key`` does not name the parent.
    """
    children = []
    for child in parent.child_apps:
        if child.parent_key != parent.key:
            raise ValueError(
                f"App '{parent.key}': child '{child.key}' declares parent_key "
                f"'{child.parent_key}', expected '{parent.key}'"
            )
        children.append(child.model_copy(update={"enabled": parent.enabled}))
    return children


def build_app_registry(plugins: Iterable[App]) -> AppRegistry:
    """Build an :class:`AppRegistry` from an activation list.

    Import each module and either use its exported ``app`` definition or
    synthesize an implicit app from the legacy settings entry. Pure function of
    the activation list -- unit tests call it directly.

    :param plugins: The ``SEP.APPS`` activation entries, in order.
    :return: The ordered registry.
    :rtype: AppRegistry
    """
    apps = []
    for plugin in plugins:
        auto_key = _derive_app_key(plugin.module_name)
        definition = getattr(import_module(plugin.module_name), "app", None)
        if isinstance(definition, BaseApp):
            bound = _bind_definition(definition, plugin, auto_key)
            apps.append(bound)
            apps.extend(_bind_child_apps(bound))
        else:
            apps.append(_synthesize_legacy_app(plugin, auto_key))
    return AppRegistry(apps)


@lru_cache(maxsize=1)
def get_app_registry() -> AppRegistry:
    """Return the process-wide registry built over ``sep_settings.APPS``.

    Cached so the module-importing build runs once. ``cache_clear()`` resets it
    between tests.

    :return: The cached registry.
    :rtype: AppRegistry
    """
    return build_app_registry(sep_settings.APPS)


def collect_app_owned_settings_classes(
    plugins: Iterable[App] | None = None,
) -> list[AppOwnedClassEntry]:
    """Collect app-owned settings classes declared by activated plugins.

    Each plugin may export ``APP_OWNED_SETTINGS_CLASSES`` as a list of
    :class:`~app.core.settings_override.api.routes.AppOwnedClassEntry` values.
    Entries are returned in activation-list order; duplicate
    ``setting_class`` values or unknown ``app_key`` references fail fast.

    :param plugins: The ``SEP.APPS`` activation entries to scan. Defaults to
        ``sep_settings.APPS``.
    :return: The merged app-owned settings entries.
    :rtype: list[AppOwnedClassEntry]
    :raises TypeError: If a module's declaration is not a list of
        :class:`AppOwnedClassEntry` instances.
    :raises ValueError: If a setting class is declared more than once or
        references an unknown app key.
    """
    activation = list(plugins if plugins is not None else sep_settings.APPS)
    registry = build_app_registry(activation)
    entries: list[AppOwnedClassEntry] = []
    seen_classes: set[SettingClassEnum] = set()
    for plugin in activation:
        declared = getattr(
            import_module(plugin.module_name),
            "APP_OWNED_SETTINGS_CLASSES",
            None,
        )
        if declared is None:
            continue
        if not isinstance(declared, list):
            raise TypeError(
                f"App module {plugin.module_name!r}: APP_OWNED_SETTINGS_CLASSES"
                f" must be a list, got {type(declared).__name__}.",
            )
        for entry in declared:
            if not isinstance(entry, AppOwnedClassEntry):
                raise TypeError(
                    f"App module {plugin.module_name!r}: every"
                    " APP_OWNED_SETTINGS_CLASSES entry must be an"
                    f" AppOwnedClassEntry, got {type(entry).__name__}.",
                )
            if entry.setting_class in seen_classes:
                raise ValueError(
                    f"Settings class {entry.setting_class.value!r} is declared"
                    " by more than one app-owned settings registration.",
                )
            if registry.get(entry.app_key) is None:
                raise ValueError(
                    f"App-owned settings class {entry.setting_class.value!r}"
                    f" references unknown app key {entry.app_key!r}.",
                )
            seen_classes.add(entry.setting_class)
            entries.append(entry)
    return entries


async def resolve_app_settings_metadata(
    session: AsyncSession,
    app_key: str,
) -> SettingClassAppMetadata:
    """Resolve app identity and enabled state for a settings LIST group.

    Protected apps are always reported enabled. Non-protected apps reflect
    their DB lifecycle state via :meth:`AppStateManager.is_enabled`.

    :param session: The SEP database session.
    :param app_key: The owning app's registry key.
    :return: Metadata for an app-owned :class:`SettingClassGroup`.
    :rtype: SettingClassAppMetadata
    :raises ValueError: If ``app_key`` is not registered.
    """
    app = get_app_registry().get(app_key)
    if app is None:
        raise ValueError(f"Unknown app key {app_key!r}.")
    app_enabled = app_key in PROTECTED_APP_KEYS or await AppStateManager.is_enabled(
        session,
        app_key,
    )
    return SettingClassAppMetadata(
        app_id=app.key,
        app_display_name=app.display_name,
        app_enabled=app_enabled,
    )
