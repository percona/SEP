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

"""Define tests for SEP migration discovery and alembic.ini sync."""

import importlib.util
import sys
from pathlib import Path

import pytest
from sqlmodel import SQLModel

import app.sep.apps as plugins_pkg
from app.sep.config import sep_settings
from app.sep.migrations._discovery import (
    _load_models_module,
    discover_plugin_migrations_and_models,
    discover_plugin_version_dirs,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_SYNC_SCRIPT = _PROJECT_ROOT / "scripts" / "sync_alembic_version_locations.py"

_spec = importlib.util.spec_from_file_location(
    "sync_alembic_version_locations", _SYNC_SCRIPT
)
assert _spec is not None, f"cannot load {_SYNC_SCRIPT}"
assert _spec.loader is not None, f"cannot load {_SYNC_SCRIPT}"
sync_alembic_version_locations = importlib.util.module_from_spec(_spec)
sys.modules["sync_alembic_version_locations"] = sync_alembic_version_locations
_spec.loader.exec_module(sync_alembic_version_locations)

_MINIMAL_INI = """\
[alembic]
databases = sep

[sep]
# path to migration scripts.
script_location = app/sep/migrations
# stale hand-written comment
version_locations = %(here)s/app/sep/migrations/versions

[post_write_hooks]
# keep this section marker
"""


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


def test_discover_plugin_version_dirs_sorted_without_loading_models(tmp_path):
    """Filesystem helper returns sorted dirs and never loads ``models.py``."""
    _build_plugin(tmp_path, "zebra", with_migrations=True, models_source=_MARKER_SRC)
    _build_plugin(tmp_path, "alpha", with_migrations=True, models_source=_MARKER_SRC)
    _build_plugin(tmp_path, "no_mig", with_migrations=False, models_source=_MARKER_SRC)
    version_dirs = discover_plugin_version_dirs(tmp_path)
    assert version_dirs == [
        str(tmp_path / "alpha" / "migrations" / "versions"),
        str(tmp_path / "zebra" / "migrations" / "versions"),
    ]
    assert "app.sep.apps.alpha.models" not in sys.modules
    assert "app.sep.apps.zebra.models" not in sys.modules


def test_discover_skips_namespace_package_without_init(tmp_path):
    """Dirs without ``__init__.py`` are not treated as migration-owning plugins."""
    _build_plugin(
        tmp_path,
        "namespace_only",
        with_migrations=True,
        models_source=_MARKER_SRC,
        init_source=None,
    )
    _build_plugin(
        tmp_path,
        "real_pkg",
        with_migrations=True,
        models_source=_MARKER_SRC,
    )
    version_dirs = discover_plugin_version_dirs(tmp_path)
    assert version_dirs == [
        str(tmp_path / "real_pkg" / "migrations" / "versions"),
    ]


def test_sync_regenerates_from_synthetic_app_tree(tmp_path):
    """Sync rewrites ``version_locations`` from a synthetic apps tree."""
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    _build_plugin(apps_root, "zebra", with_migrations=True, models_source=None)
    _build_plugin(apps_root, "alpha", with_migrations=True, models_source=None)
    ini_path = tmp_path / "alembic.ini"
    ini_path.write_text(_MINIMAL_INI)

    assert sync_alembic_version_locations.sync_alembic_ini(ini_path, apps_root)
    text = ini_path.read_text()
    expected = (
        "%(here)s/app/sep/migrations/versions:"
        "%(here)s/app/sep/apps/alpha/migrations/versions:"
        "%(here)s/app/sep/apps/zebra/migrations/versions"
    )
    assert f"version_locations = {expected}" in text
    assert "GENERATED" in text
    assert "stale hand-written comment" not in text


def test_sync_is_idempotent_on_second_run(tmp_path):
    """A second sync leaves the file byte-identical."""
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    _build_plugin(apps_root, "alpha", with_migrations=True, models_source=None)
    ini_path = tmp_path / "alembic.ini"
    ini_path.write_text(_MINIMAL_INI)

    assert sync_alembic_version_locations.sync_alembic_ini(ini_path, apps_root)
    after_first = ini_path.read_text()
    assert sync_alembic_version_locations.sync_alembic_ini(ini_path, apps_root)
    assert ini_path.read_text() == after_first
    assert sync_alembic_version_locations.sync_alembic_ini(
        ini_path, apps_root, check=True
    )


def test_sync_preserves_crlf_line_endings(tmp_path):
    """Sync preserves CRLF ``alembic.ini`` without converting to ``LF``."""
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    _build_plugin(apps_root, "alpha", with_migrations=True, models_source=None)
    ini_path = tmp_path / "alembic.ini"
    crlf_ini = _MINIMAL_INI.replace("\n", "\r\n").encode("utf-8")
    ini_path.write_bytes(crlf_ini)

    assert sync_alembic_version_locations.sync_alembic_ini(ini_path, apps_root)
    rewritten = ini_path.read_bytes()
    assert b"\r\n" in rewritten
    assert b"\n" not in rewritten.replace(b"\r\n", b"")
    assert b"app/sep/apps/alpha/migrations/versions" in rewritten


def test_sync_rejects_multiline_version_locations(tmp_path):
    """Sync raises when ``version_locations`` has indented continuation lines."""
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    _build_plugin(apps_root, "alpha", with_migrations=True, models_source=None)
    ini_path = tmp_path / "alembic.ini"
    ini_path.write_text(
        _MINIMAL_INI.replace(
            "version_locations = %(here)s/app/sep/migrations/versions\n",
            "version_locations = %(here)s/app/sep/migrations/versions:\n"
            "    %(here)s/app/sep/apps/stale/migrations/versions\n",
        )
    )

    with pytest.raises(ValueError, match="single line"):
        sync_alembic_version_locations.sync_alembic_ini(ini_path, apps_root)


def test_sync_preserves_comment_block_and_other_sections(tmp_path):
    """Sync keeps ``script_location`` and non-``[sep]`` sections intact."""
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    _build_plugin(apps_root, "alpha", with_migrations=True, models_source=None)
    ini_path = tmp_path / "alembic.ini"
    ini_path.write_text(_MINIMAL_INI)

    sync_alembic_version_locations.sync_alembic_ini(ini_path, apps_root)
    text = ini_path.read_text()
    assert "script_location = app/sep/migrations" in text
    assert "[post_write_hooks]" in text
    assert "# keep this section marker" in text
    assert "databases = sep" in text
    assert "GENERATED — do not hand-edit" in text


def test_sync_check_detects_drift(tmp_path):
    """``--check`` returns false when the committed value is stale."""
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    _build_plugin(apps_root, "alpha", with_migrations=True, models_source=None)
    ini_path = tmp_path / "alembic.ini"
    ini_path.write_text(_MINIMAL_INI)

    assert not sync_alembic_version_locations.sync_alembic_ini(
        ini_path, apps_root, check=True
    )
    assert (
        sync_alembic_version_locations.main(
            ["--check", "--ini", str(ini_path), "--apps-root", str(apps_root)]
        )
        == 1
    )


def test_committed_alembic_ini_matches_discovery():
    """Guard: committed ``alembic.ini`` matches the filesystem walk."""
    assert sync_alembic_version_locations.main(["--check"]) == 0
