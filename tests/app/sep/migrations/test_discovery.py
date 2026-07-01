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

"""Define tests for the ``app.sep.migrations._discovery`` helpers."""

import sys
from pathlib import Path

import pytest
from sqlmodel import SQLModel

import app.sep.apps as plugins_pkg
from app.sep.config import sep_settings
from app.sep.migrations._discovery import (
    _load_models_module,
    discover_plugin_migrations_and_models,
)


@pytest.fixture
def isolated_plugins_path(tmp_path, monkeypatch):
    """Yield a scratch plugins path used in place of the real one.

    Replace ``app.sep.apps.__path__`` with a single-entry list
    pointing at ``tmp_path`` so the test can construct throwaway
    plugins without disturbing the real plugin tree. Evicts any
    throwaway plugin modules from ``sys.modules`` on teardown.

    :param tmp_path: Pytest's per-test temporary directory.
    :type tmp_path: Path
    :param monkeypatch: Pytest monkeypatch fixture.
    :type monkeypatch: pytest.MonkeyPatch
    :return: The ``tmp_path`` acting as the plugins root.
    :rtype: Path
    """
    monkeypatch.setattr(plugins_pkg, "__path__", [str(tmp_path)])
    yield tmp_path
    for mod_name in list(sys.modules):
        if not mod_name.startswith(f"{plugins_pkg.__name__}."):
            continue
        path = getattr(sys.modules[mod_name], "__file__", "") or ""
        if str(tmp_path) in path:
            sys.modules.pop(mod_name, None)


def _build_plugin(
    root: Path,
    name: str,
    *,
    with_migrations: bool,
    models_source: str | None,
    init_source: str | None = "",
) -> Path:
    """Create a throwaway plugin package under ``root``.

    :param root: The parent directory that acts as the plugins path.
    :type root: Path
    :param name: The plugin's directory name.
    :type name: str
    :param with_migrations: Whether to create a ``migrations/versions/``
        directory so the discovery helper treats it as schema-owning.
    :type with_migrations: bool
    :param models_source: Python source for ``models.py``. ``None`` means
        no ``models.py`` is written.
    :type models_source: str | None
    :param init_source: Python source for ``__init__.py``. ``None`` makes
        this a PEP 420 namespace package (no ``__init__.py``).
    :type init_source: str | None
    :return: The plugin directory path.
    :rtype: Path
    """
    plugin_dir = root / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    if init_source is not None:
        (plugin_dir / "__init__.py").write_text(init_source)
    if models_source is not None:
        (plugin_dir / "models.py").write_text(models_source)
    if with_migrations:
        (plugin_dir / "migrations").mkdir(exist_ok=True)
        (plugin_dir / "migrations" / "versions").mkdir(exist_ok=True)
    return plugin_dir


_MARKER_SRC = """
MARKER = "plugin-models-loaded"
"""


def test_discover_imports_installed_plugin_models():
    """Discovery places ``alert_backup`` in ``SQLModel.metadata``."""
    discover_plugin_migrations_and_models()
    assert "alert_backup" in SQLModel.metadata.tables


def test_discover_returns_alerts_migrations_dir():
    """Discovery returns the absolute path to alerts' ``versions/`` dir."""
    version_dirs = discover_plugin_migrations_and_models()
    alerts_versions = str(
        Path(plugins_pkg.__path__[0]) / "alerts" / "migrations" / "versions"
    )
    assert alerts_versions in version_dirs
    assert Path(alerts_versions).is_dir()


def test_discover_ignores_sep_settings_plugins(monkeypatch):
    """Assert discovery does not consult ``sep_settings.APPS``."""
    monkeypatch.setattr(sep_settings, "APPS", [])
    version_dirs = discover_plugin_migrations_and_models()
    alerts_versions = str(
        Path(plugins_pkg.__path__[0]) / "alerts" / "migrations" / "versions"
    )
    assert alerts_versions in version_dirs


def test_discover_skips_plugin_without_migrations_dir(isolated_plugins_path):
    """Plugins without ``migrations/versions/`` are ignored entirely."""
    _build_plugin(
        isolated_plugins_path,
        "no_migrations_plugin",
        with_migrations=False,
        models_source=_MARKER_SRC,
    )
    version_dirs = discover_plugin_migrations_and_models()
    assert version_dirs == []
    assert "app.sep.apps.no_migrations_plugin.models" not in sys.modules


def test_discover_propagates_broken_models_import(isolated_plugins_path):
    """Propagate ``ModuleNotFoundError`` from a broken plugin ``models.py``."""
    _build_plugin(
        isolated_plugins_path,
        "broken_models_plugin",
        with_migrations=True,
        models_source="from _definitely_missing_pkg import nope\n",
    )
    with pytest.raises(ModuleNotFoundError):
        discover_plugin_migrations_and_models()
    assert "app.sep.apps.broken_models_plugin.models" not in sys.modules


def test_discover_does_not_trigger_plugin_init_py(isolated_plugins_path):
    """Discovery bypasses the plugin's ``__init__.py``."""
    _build_plugin(
        isolated_plugins_path,
        "init_raises_plugin",
        with_migrations=True,
        models_source=_MARKER_SRC,
        init_source=(
            "raise RuntimeError('plugin __init__.py must not run at migration time')\n"
        ),
    )
    version_dirs = discover_plugin_migrations_and_models()
    target = str(
        isolated_plugins_path / "init_raises_plugin" / "migrations" / "versions"
    )
    assert target in version_dirs
    loaded = sys.modules["app.sep.apps.init_raises_plugin.models"]
    assert loaded.MARKER == "plugin-models-loaded"


def test_discover_handles_snippets_plugin_without_error():
    """Real-tree discovery does not trigger plugin circular imports."""
    discover_plugin_migrations_and_models()


def test_all_migration_owning_plugins_have_loadable_models():
    """Every plugin with migrations exposes a loadable ``models.py``.

    Guard against a plugin shipping ``migrations/versions/`` with a
    ``models.py`` that imports from sibling plugin modules (and would
    fail at migration time). The discovery helper has a ``sys.modules``
    guard so calling ``_load_models_module`` twice is a no-op on the
    second call; we verify that the module ends up registered.
    """
    real_plugins_dir = Path(plugins_pkg.__path__[0])
    for plugin_dir in real_plugins_dir.iterdir():
        if not plugin_dir.is_dir():
            continue
        if not (plugin_dir / "migrations" / "versions").is_dir():
            continue
        models_path = plugin_dir / "models.py"
        if not models_path.is_file():
            continue
        full_name = f"{plugins_pkg.__name__}.{plugin_dir.name}.models"
        _load_models_module(full_name, models_path)
        assert full_name in sys.modules
