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

"""Define end-to-end tests for SEP's multi-head Alembic configuration.

Exercise ``alembic.command.upgrade``/``downgrade``/``check`` against a
temporary SQLite database using the real ``env.py``, ``_discovery.py``,
and ``alembic.ini`` — the combination that breaks on any misconfigured
``version_locations`` or plugin-discovery regression.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError

from app.sep.apps.alerts.models import AlertBackup
from app.sep.config import sep_settings

REPO_ROOT = Path(__file__).resolve().parents[4]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

# The add_setting_override_table revision on the SEP track, before SETTINGS /
# ALERT_SETTINGS were added to the setting_class CHECK constraint.
_SEP_PRE_ENUM_REVISION = "ed97b99eef38"

# The add_seppluginperiodictask revision: appstate still has the boolean
# ``enabled`` column, before ``lifecycle_state`` replaces it.
_SEP_PRE_LIFECYCLE_REVISION = "64f10ead74f6"
# The add_lifecycle_state_to_app_state revision under test.
_SEP_LIFECYCLE_REVISION = "a7c4e9f1b2d3"


def _insert_override(conn, setting_class: str) -> None:
    """Insert a minimal ``settingoverride`` row with the given setting_class."""
    conn.exec_driver_sql(
        "INSERT INTO settingoverride "
        "(created_at, setting_class, key, value, is_active) "
        "VALUES ('2026-01-01 00:00:00', ?, 'X', 'true', 1)",
        (setting_class,),
    )


def _insert_appstate_enabled(conn, app_key: str, enabled: int) -> None:
    """Insert an ``appstate`` row using the pre-lifecycle ``enabled`` column."""
    conn.exec_driver_sql(
        "INSERT INTO appstate (created_at, app_key, enabled) "
        "VALUES ('2026-01-01 00:00:00', ?, ?)",
        (app_key, enabled),
    )


@pytest.fixture
def sep_alembic_config(tmp_path, monkeypatch):
    """Yield an Alembic ``Config`` pointing at a temp SQLite file.

    Patch ``sep_settings.DATABASE.HOST`` and ``NAME`` so that the
    computed ``DATABASE.URL`` property evaluates to a temp SQLite path
    when ``env.py`` reads it.

    :param tmp_path: Pytest's per-test temporary directory.
    :type tmp_path: Path
    :param monkeypatch: Pytest monkeypatch fixture.
    :type monkeypatch: pytest.MonkeyPatch
    :return: A tuple of (Config, sync sqlite URL) for the test DB.
    :rtype: tuple[Config, str]
    """
    db_path = tmp_path / "test_sep.sqlite"
    sync_url = f"sqlite:///{db_path}"

    monkeypatch.setattr(sep_settings.DATABASE, "HOST", "")
    monkeypatch.setattr(sep_settings.DATABASE, "NAME", str(db_path))

    cfg = Config(str(ALEMBIC_INI), ini_section="sep")
    return cfg, sync_url


def _get_stamped_revisions(sync_url: str) -> set[str]:
    """Return the set of revisions stamped in ``alembic_version_sep``.

    :param sync_url: Sync SQLAlchemy URL to the test database.
    :type sync_url: str
    :return: All ``version_num`` values currently in the version table.
    :rtype: set[str]
    """
    engine = create_engine(sync_url)
    try:
        with engine.connect() as conn:
            if "alembic_version_sep" not in inspect(conn).get_table_names():
                return set()
            rows = conn.exec_driver_sql(
                "SELECT version_num FROM alembic_version_sep"
            ).fetchall()
            return {row[0] for row in rows}
    finally:
        engine.dispose()


def test_alembic_upgrade_heads_fresh_db_creates_alert_backup(sep_alembic_config):
    """Run ``upgrade heads`` on a fresh DB to materialize both branches."""
    cfg, sync_url = sep_alembic_config
    command.upgrade(cfg, "heads")

    engine = create_engine(sync_url)
    try:
        table_names = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert "alert_backup" in table_names
    assert "snippet" in table_names


def test_alembic_upgrade_idempotent_on_existing_table(sep_alembic_config):
    """Tolerate ``alert_backup`` left over from pre-migration runs."""
    cfg, sync_url = sep_alembic_config

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            AlertBackup.__table__.create(conn)
    finally:
        engine.dispose()

    command.upgrade(cfg, "heads")

    engine = create_engine(sync_url)
    try:
        assert "alert_backup" in set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_alembic_downgrade_alerts_to_base_drops_table(sep_alembic_config):
    """Run ``downgrade alerts@base`` to drop the alerts branch only."""
    cfg, sync_url = sep_alembic_config
    command.upgrade(cfg, "heads")

    command.downgrade(cfg, "alerts@base")

    engine = create_engine(sync_url)
    try:
        table_names = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert "alert_backup" not in table_names
    assert "snippet" in table_names
    stamped = _get_stamped_revisions(sync_url)
    script = ScriptDirectory.from_config(cfg)
    sep_main_heads = {rev.revision for rev in script.get_revisions("sep_main@heads")}
    alerts_heads = {rev.revision for rev in script.get_revisions("alerts@heads")}
    assert not (alerts_heads & stamped)
    assert sep_main_heads & stamped


def test_setting_class_enum_accepts_new_members_after_upgrade(sep_alembic_config):
    """After ``upgrade heads``, SETTINGS and ALERT_SETTINGS rows are accepted."""
    cfg, sync_url = sep_alembic_config
    command.upgrade(cfg, "heads")

    new_members = ("SETTINGS", "ALERT_SETTINGS")
    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            for member in new_members:
                _insert_override(conn, member)
            count = conn.exec_driver_sql(
                "SELECT COUNT(*) FROM settingoverride"
            ).scalar()
        assert count == len(new_members)
    finally:
        engine.dispose()


def test_setting_class_enum_rejects_new_members_before_upgrade(sep_alembic_config):
    """At the pre-enum revision, a SETTINGS row violates the CHECK constraint."""
    cfg, sync_url = sep_alembic_config
    command.upgrade(cfg, _SEP_PRE_ENUM_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn, pytest.raises(IntegrityError):
            _insert_override(conn, "SETTINGS")
    finally:
        engine.dispose()


def test_app_lifecycle_backfill_maps_enabled_to_state(sep_alembic_config):
    """The lifecycle migration backfills ``enabled`` into ``lifecycle_state``."""
    cfg, sync_url = sep_alembic_config
    command.upgrade(cfg, _SEP_PRE_LIFECYCLE_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            _insert_appstate_enabled(conn, "snippets", 1)
            _insert_appstate_enabled(conn, "checksums", 0)
    finally:
        engine.dispose()

    command.upgrade(cfg, _SEP_LIFECYCLE_REVISION)

    engine = create_engine(sync_url)
    try:
        columns = {col["name"] for col in inspect(engine).get_columns("appstate")}
        with engine.begin() as conn:
            rows = dict(
                conn.exec_driver_sql(
                    "SELECT app_key, lifecycle_state FROM appstate"
                ).fetchall()
            )
    finally:
        engine.dispose()

    assert "enabled" not in columns
    assert "lifecycle_state" in columns
    assert rows == {"snippets": "ENABLED", "checksums": "DISABLED"}


def test_app_lifecycle_check_rejects_unknown_state(sep_alembic_config):
    """After upgrade, a bogus ``lifecycle_state`` violates the CHECK constraint."""
    cfg, sync_url = sep_alembic_config
    command.upgrade(cfg, _SEP_LIFECYCLE_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn, pytest.raises(IntegrityError):
            conn.exec_driver_sql(
                "INSERT INTO appstate (created_at, app_key, lifecycle_state) "
                "VALUES ('2026-01-01 00:00:00', 'snippets', 'BOGUS')"
            )
    finally:
        engine.dispose()


def test_app_lifecycle_downgrade_restores_enabled(sep_alembic_config):
    """Downgrading the lifecycle migration restores the boolean ``enabled`` column."""
    cfg, sync_url = sep_alembic_config
    command.upgrade(cfg, _SEP_LIFECYCLE_REVISION)

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "INSERT INTO appstate (created_at, app_key, lifecycle_state) "
                "VALUES ('2026-01-01 00:00:00', 'snippets', 'ENABLED')"
            )
            conn.exec_driver_sql(
                "INSERT INTO appstate (created_at, app_key, lifecycle_state) "
                "VALUES ('2026-01-01 00:00:00', 'checksums', 'DISABLING')"
            )
    finally:
        engine.dispose()

    command.downgrade(cfg, _SEP_PRE_LIFECYCLE_REVISION)

    engine = create_engine(sync_url)
    try:
        columns = {col["name"] for col in inspect(engine).get_columns("appstate")}
        with engine.begin() as conn:
            rows = dict(
                conn.exec_driver_sql("SELECT app_key, enabled FROM appstate").fetchall()
            )
    finally:
        engine.dispose()

    assert "lifecycle_state" not in columns
    assert "enabled" in columns
    assert rows == {"snippets": 1, "checksums": 0}
