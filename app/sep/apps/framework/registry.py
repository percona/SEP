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

from collections.abc import Iterable, Iterator, Mapping
from functools import lru_cache
from importlib import import_module

from fastapi import APIRouter
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.settings_override.api.models import SettingClassAppMetadata
from app.core.settings_override.api.routes import AppOwnedClassEntry
from app.core.settings_override.models import SettingClassEnum
from app.core.utils import import_var
from app.sep.apps.framework.base import BaseApp
from app.sep.config import App, sep_settings
from app.sep.crud import AppStateManager
from app.sep.deps import PROTECTED_APP_KEYS
from app.sep.models import AppLifecycleEnum


class AppRegistry:
    """Represent an ordered, key-addressable collection of mounted apps.

    Iteration order equals activation-list order; the byte-for-byte OpenAPI
    no-op for mounted plugin routes depends on it.

    :param apps: The mounted apps, in activation order.
    :type apps: list[BaseApp]
    :raises ValueError: When two apps share a key, or a ``requires_apps`` entry
        names an unknown app, itself, or forms a dependency cycle.
    """

    def __init__(self, apps: list[BaseApp]) -> None:
        self._apps = apps
        # Explicit loop, not a comprehension: a duplicate key must raise, not
        # silently overwrite, or a ``requires_apps`` reference turns ambiguous.
        self._by_key: dict[str, BaseApp] = {}
        for app in apps:
            if app.key in self._by_key:
                raise ValueError(
                    f"Duplicate app key {app.key!r}: two apps cannot share a"
                    " key, or a requires_apps reference would be ambiguous.",
                )
            self._by_key[app.key] = app
        self._validate_dependencies()

    def _validate_dependencies(self) -> None:
        """Reject self-dependencies, dangling deps, and cycles at build time.

        :raises ValueError: When a ``requires_apps`` entry names the app itself,
            names an unregistered key, or participates in a dependency cycle.
        """
        for app in self._apps:
            for dep_key in app.requires_apps:
                if dep_key == app.key:
                    raise ValueError(
                        f"App {app.key!r} cannot depend on itself.",
                    )
                if dep_key not in self._by_key:
                    raise ValueError(
                        f"App {app.key!r} requires unknown app key {dep_key!r}.",
                    )
        self._assert_acyclic()

    def _assert_acyclic(self) -> None:
        """Raise when the ``requires_apps`` graph contains a cycle.

        :raises ValueError: When a dependency cycle is detected.
        """
        white, gray, black = 0, 1, 2
        color = {app.key: white for app in self._apps}

        def visit(key: str, path: list[str]) -> None:
            color[key] = gray
            for dep_key in self._by_key[key].requires_apps:
                if color[dep_key] == gray:
                    chain = " -> ".join([*path, key, dep_key])
                    raise ValueError(f"App dependency cycle detected: {chain}.")
                if color[dep_key] == white:
                    visit(dep_key, [*path, key])
            color[key] = black

        for app in self._apps:
            if color[app.key] == white:
                visit(app.key, [])

    def resolve_effective_enabled(
        self,
        key: str,
        states: Mapping[str, AppLifecycleEnum],
        memo: dict[str, bool] | None = None,
    ) -> bool:
        """Return whether ``key``'s app is effectively enabled.

        An app is effective-enabled when its own ``AppState`` is ``ENABLED``
        **and** every app in its ``requires_apps`` is itself effective-enabled
        (resolved transitively). This is the single resolver the mount gate, the
        sidebar filter, and the ``GET /api/apps`` projection all share, so they
        cannot drift. A protected app (or dependency) is always treated as
        enabled; a missing ``AppState`` row defaults to ``ENABLED``.

        :param key: The registry key of the app to resolve.
        :param states: A ``{state_key: lifecycle}`` map (e.g. from
            :meth:`AppStateManager.all_lifecycle_states`).
        :param memo: An optional ``{key: bool}`` cache shared across a
            full-registry projection so shared dependency subtrees are walked
            once rather than re-walked per app. Only reuse a memo within a
            single ``states`` snapshot; a fresh ``states`` needs a fresh memo.
        :return: ``True`` when the app and every dependency are enabled.
        """
        app = self._by_key.get(key)
        if app is None:
            return False
        return self._effective_enabled(app, states, frozenset(), memo)

    def _effective_enabled(
        self,
        app: BaseApp,
        states: Mapping[str, AppLifecycleEnum],
        stack: frozenset[str],
        memo: dict[str, bool] | None = None,
    ) -> bool:
        """Resolve ``app``'s effective-enabled state along a DFS path.

        :param app: The app being resolved.
        :param states: The ``{state_key: lifecycle}`` map.
        :param stack: The keys on the current recursion path (cycle guard).
        :param memo: An optional ``{key: bool}`` cache; a resolved result is
            stored under ``app.key`` and reused on the next visit.
        :return: ``True`` when the app and every dependency are enabled.
        """
        if memo is not None and app.key in memo:
            return memo[app.key]
        result = self._resolve_effective(app, states, stack, memo)
        if memo is not None:
            memo[app.key] = result
        return result

    def _resolve_effective(
        self,
        app: BaseApp,
        states: Mapping[str, AppLifecycleEnum],
        stack: frozenset[str],
        memo: dict[str, bool] | None,
    ) -> bool:
        """Compute ``app``'s effective-enabled state (the un-memoized body).

        :param app: The app being resolved.
        :param states: The ``{state_key: lifecycle}`` map.
        :param stack: The keys on the current recursion path (cycle guard).
        :param memo: The projection cache threaded into dependency resolution.
        :return: ``True`` when the app and every dependency are enabled.
        """
        if app.state_key in PROTECTED_APP_KEYS:
            # Can never be disabled, so return True without recursing into its
            # own ``requires_apps``.
            return True
        if not self._own_enabled(app, states):
            return False
        if app.key in stack:
            # Defensive: the build rejects cycles, so this is unreachable. Fail
            # closed -- an unexpected cycle gates the app off, never on.
            return False
        stack = stack | {app.key}
        for dep_key in app.requires_apps:
            dep = self._by_key.get(dep_key)
            if dep is None or not self._effective_enabled(dep, states, stack, memo):
                return False
        return True

    @staticmethod
    def _own_enabled(app: BaseApp, states: Mapping[str, AppLifecycleEnum]) -> bool:
        """Return whether ``app``'s own ``AppState`` is enabled (ignoring deps).

        :param app: The app whose own state is inspected.
        :param states: The ``{state_key: lifecycle}`` map.
        :return: ``True`` when protected or the row is ``ENABLED`` (or absent).
        """
        return (
            app.state_key in PROTECTED_APP_KEYS
            or states.get(app.state_key, AppLifecycleEnum.ENABLED)
            == AppLifecycleEnum.ENABLED
        )

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
