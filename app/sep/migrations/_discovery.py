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
import pkgutil
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
    Filesystem-based walk over ``pkgutil.iter_modules(plugins_pkg.__path__)``;
    does NOT consult ``sep_settings.APPS``. Schema management follows
    installed code, not enablement in configuration.

    :return: Absolute paths to each participating plugin's migration
        ``versions/`` directory, in iteration order.
    :rtype: list[str]
    """
    version_dirs = []
    for finder, name, is_pkg in pkgutil.iter_modules(plugins_pkg.__path__):
        if not is_pkg:
            continue
        plugin_dir = Path(finder.path) / name
        versions_dir = plugin_dir / "migrations" / "versions"
        if not versions_dir.is_dir():
            continue
        models_path = plugin_dir / "models.py"
        if models_path.is_file():
            full_name = f"{plugins_pkg.__name__}.{name}.models"
            _load_models_module(full_name, models_path)
        version_dirs.append(str(versions_dir))
    return version_dirs


#: Plugins whose DB table lives in a self-contained ``catalog_models.py`` rather
#: than in ``models.py``. Such a plugin keeps ``models.py`` heavy (importing
#: ``app.inventory`` / ``app.tasks`` / the app framework for form-model
#: construction), which cannot be loaded at migration time without bleeding those
#: foreign tables into the sep autogenerate comparison; its table therefore lives
#: in a self-contained module (importing only ``app.core`` / ``sqlalchemy`` /
#: ``sqlmodel`` / ``pydantic``). Listed explicitly — one known file per entry —
#: rather than scanned for, so migration metadata stays deterministic.
_CATALOG_MODEL_PLUGINS = ("mysql_backups",)


def load_catalog_models() -> None:
    """Register the known self-contained ``catalog_models.py`` modules.

    Loads each plugin in :data:`_CATALOG_MODEL_PLUGINS` via
    ``spec_from_file_location`` — bypassing the package ``__init__`` (which pulls
    the full route graph) exactly as
    :func:`discover_plugin_migrations_and_models` does for ``models.py``. Unlike
    migration discovery this is not migrations-first: a catalog table may live on
    the shared ``sep_main`` chain rather than a per-plugin branch, so its owning
    plugin need not have a ``migrations/`` directory of its own.

    :return: ``None``.
    """
    package_dir = Path(plugins_pkg.__path__[0])
    for name in _CATALOG_MODEL_PLUGINS:
        catalog_path = package_dir / name / "catalog_models.py"
        if catalog_path.is_file():
            _load_models_module(
                f"{plugins_pkg.__name__}.{name}.catalog_models", catalog_path
            )
