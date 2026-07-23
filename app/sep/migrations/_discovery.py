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

"""Define plugin discovery helpers for SEP's Alembic env.py.

Kept in a separate module (not ``env.py``) because importing ``env.py``
runs migrations as a side effect — the bottom of that file dispatches
into ``run_migrations_online()`` or ``run_migrations_offline()`` at
import time. Helpers here are pure and import-safe; unit tests exercise
them directly without spinning up Alembic.

**Critical design constraint — do NOT use ``importlib.import_module`` or
``importlib.util.find_spec`` to probe for plugin models.** Both trigger
a parent-package import, which runs the plugin's ``__init__.py``. In
this repo every plugin's ``__init__.py`` imports ``routes``, which
pulls in the full request-handler graph (crud, deps, plugin clients,
template context). That graph has inter-plugin imports with cycles
(``snippets -> routes -> deps -> artifacts -> dipper`` is the one
verified to break today). At migration time we only need metadata
registration, not route-handler construction — so discovery walks the
filesystem and loads each plugin's ``models.py`` via
``spec_from_file_location``, which bypasses the parent ``__init__``
entirely.
"""

import importlib.util
import sys
from pathlib import Path

import app.sep.apps as plugins_pkg


def _load_models_module(full_name: str, models_path: Path) -> None:
    """Load ``<plugin>/models.py`` into ``sys.modules`` under ``full_name``.

    Uses ``spec_from_file_location`` + ``exec_module`` so Python never
    runs the parent package's ``__init__``. The loaded module's own
    ``import`` statements still resolve through the normal import
    system; since plugin ``models.py`` files are self-contained (they
    import only from ``app.core``, ``app.sep.models``, ``sqlalchemy``,
    and ``sqlmodel`` — never from sibling plugin modules), this is
    safe.

    :param full_name: The fully qualified module name under which to
        register the loaded module (e.g. ``app.sep.apps.alerts.models``).
    :type full_name: str
    :param models_path: Filesystem path to the plugin's ``models.py``
        file.
    :type models_path: Path
    :return: ``None``.
    :rtype: None
    """
    if full_name in sys.modules:
        return
    spec = importlib.util.spec_from_file_location(full_name, models_path)
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(full_name, None)
        raise


def discover_plugin_version_dirs(apps_root: Path | None = None) -> list[str]:
    """Return sorted migration ``versions/`` dirs for plugins that own migrations.

    Filesystem-only: does not import or load any plugin ``models.py``. A
    plugin participates only when ``migrations/versions/`` exists on disk
    (migrations-first). Does not consult ``sep_settings.APPS``.

    :param apps_root: Directory of plugin packages to scan. Defaults to
        every entry on ``app.sep.apps.__path__``.
    :type apps_root: Path | None
    :return: Absolute paths to each participating plugin's migration
        ``versions/`` directory, sorted for stable ordering.
    :rtype: list[str]
    """
    roots = (
        [apps_root]
        if apps_root is not None
        else [Path(entry) for entry in plugins_pkg.__path__]
    )
    version_dirs: list[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        for plugin_dir in root.iterdir():
            if not plugin_dir.is_dir():
                continue
            versions_dir = plugin_dir / "migrations" / "versions"
            if versions_dir.is_dir():
                version_dirs.append(str(versions_dir))
    return sorted(version_dirs)


def discover_plugin_migrations_and_models() -> list[str]:
    """Return migration ``versions/`` dirs for installed plugins that own migrations.

    For each such plugin, ``models.py`` is loaded via
    ``spec_from_file_location`` so the plugin's ``__init__.py`` and
    route graph stay out of migration-time startup. Plugins WITHOUT a
    migrations directory are skipped entirely — their ``models.py`` is
    not touched, even if it exists and imports from sibling plugin
    modules.

    Discovery is **migrations-first**: a plugin only participates in
    Alembic if it has a ``migrations/versions/`` directory on disk.
    Delegates the directory walk to :func:`discover_plugin_version_dirs`;
    does NOT consult ``sep_settings.APPS``. Schema management follows
    installed code, not enablement in configuration.

    :return: Absolute paths to each participating plugin's migration
        ``versions/`` directory, sorted for stable ordering.
    :rtype: list[str]
    """
    version_dirs = discover_plugin_version_dirs()
    for versions_dir_str in version_dirs:
        plugin_dir = Path(versions_dir_str).parent.parent
        models_path = plugin_dir / "models.py"
        if models_path.is_file():
            full_name = f"{plugins_pkg.__name__}.{plugin_dir.name}.models"
            _load_models_module(full_name, models_path)
    return version_dirs
