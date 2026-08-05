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
``_orphan_heads.py``, and ``alembic.ini`` — the combination that breaks on
any misconfigured ``version_locations`` or plugin-discovery regression.
"""

import logging
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util import CommandError
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


# The create_alert_backup_table revision: the head of the alerts branch, the
# app the PMM-embedded side-car's allow-list strip removes.
_ALERTS_HEAD = "d21ad387df7a"
# A revision id no branch in the tree defines, standing in for version skew.
_UNKNOWN_REVISION = "deadbeef1234"

_ORPHAN_HEADS_LOGGER = "app.sep.migrations._orphan_heads"


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


@pytest.fixture
def sep_alembic_config_stripped_alerts(sep_alembic_config, tmp_path):
    """Return an Alembic ``Config`` whose alerts version location is gone from disk.

    Reproduce a stripped image. ``alembic.ini`` is generated at commit time and
    ships an entry for every app that owns migrations, so removing an app removes
    its ``versions/`` directory, not the ini line — the entry stays configured
    while pointing nowhere. Dropping the entry instead would leave every
    configured location present, which is the fail-closed case rather than a
    stripped app.

    The returned config addresses the same temp SQLite database as
    ``sep_alembic_config``.

    :param sep_alembic_config: The full-config fixture whose database is shared.
    :param tmp_path: Pytest's per-test temporary directory.
    :return: A tuple of (Config, sync sqlite URL, the absent alerts path).
    """
    _, sync_url = sep_alembic_config
    absent = tmp_path / "stripped" / "alerts" / "migrations" / "versions"
    cfg = Config(str(ALEMBIC_INI), ini_section="sep")
    locations = ScriptDirectory.from_config(cfg).version_locations
    cfg.set_main_option(
        "version_locations",
        ":".join(
            str(absent) if "alerts" in location else location for location in locations
        ),
    )
    return cfg, sync_url, str(absent)


def _stamp_extra_revision(sync_url: str, revision: str) -> None:
    """Insert an extra ``alembic_version_sep`` row for the given revision.

    :param sync_url: Sync SQLAlchemy URL to the test database.
    :param revision: The revision id to stamp.
    """
    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "INSERT INTO alembic_version_sep (version_num) VALUES (?)",
                (revision,),
            )
    finally:
        engine.dispose()


def _get_table_names(sync_url: str) -> set[str]:
    """Return the table names present in the test database.

    :param sync_url: Sync SQLAlchemy URL to the test database.
    :return: Every table name the database currently holds.
    """
    engine = create_engine(sync_url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_succeeds_when_a_recorded_head_has_no_migration_script(
    sep_alembic_config, sep_alembic_config_stripped_alerts
):
    """Upgrade a database whose alerts head no longer resolves."""
    full_cfg, _ = sep_alembic_config
    stripped_cfg, _, _ = sep_alembic_config_stripped_alerts
    command.upgrade(full_cfg, "heads")

    command.upgrade(stripped_cfg, "heads")


def test_upgrade_preserves_the_unresolvable_row(
    sep_alembic_config, sep_alembic_config_stripped_alerts
):
    """Leave the orphaned alerts row in place so a returning app resumes from it."""
    full_cfg, sync_url = sep_alembic_config
    stripped_cfg, _, _ = sep_alembic_config_stripped_alerts
    command.upgrade(full_cfg, "heads")

    command.upgrade(stripped_cfg, "heads")

    assert _ALERTS_HEAD in _get_stamped_revisions(sync_url)


def test_upgrade_logs_every_skipped_revision_id(
    sep_alembic_config, sep_alembic_config_stripped_alerts, caplog
):
    """Name each skipped revision, and the absent location, in one warning."""
    full_cfg, _ = sep_alembic_config
    stripped_cfg, _, absent_path = sep_alembic_config_stripped_alerts
    command.upgrade(full_cfg, "heads")

    with caplog.at_level(logging.WARNING, logger=_ORPHAN_HEADS_LOGGER):
        command.upgrade(stripped_cfg, "heads")

    records = [
        record
        for record in caplog.records
        if record.name == _ORPHAN_HEADS_LOGGER and record.levelno == logging.WARNING
    ]
    assert len(records) == 1
    assert _ALERTS_HEAD in records[0].getMessage()
    assert absent_path in records[0].getMessage()


def test_upgrade_applies_another_branch_while_preserving_the_orphan_row(
    sep_alembic_config, sep_alembic_config_stripped_alerts
):
    """Advance the sep_main branch without disturbing the orphaned alerts row."""
    full_cfg, sync_url = sep_alembic_config
    stripped_cfg, _, _ = sep_alembic_config_stripped_alerts
    command.upgrade(full_cfg, "heads")
    command.downgrade(full_cfg, _SEP_PRE_LIFECYCLE_REVISION)

    command.upgrade(stripped_cfg, "heads")

    engine = create_engine(sync_url)
    try:
        columns = {col["name"] for col in inspect(engine).get_columns("appstate")}
    finally:
        engine.dispose()
    assert "lifecycle_state" in columns
    assert _ALERTS_HEAD in _get_stamped_revisions(sync_url)


def test_returning_app_resumes_from_the_preserved_row(
    sep_alembic_config, sep_alembic_config_stripped_alerts
):
    """Resume the alerts branch from its preserved row once the app comes back.

    The returning upgrade finds the branch already at its head, so the rows
    written while the app was stripped survive untouched.
    """
    full_cfg, sync_url = sep_alembic_config
    stripped_cfg, _, _ = sep_alembic_config_stripped_alerts
    command.upgrade(full_cfg, "heads")
    command.upgrade(stripped_cfg, "heads")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                'INSERT INTO alert_backup (created_at, data, "metadata") '
                "VALUES ('2026-01-01 00:00:00', '{\"kept\": true}', '{}')"
            )
    finally:
        engine.dispose()

    command.upgrade(full_cfg, "heads")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            rows = [
                row[0]
                for row in conn.exec_driver_sql(
                    "SELECT data FROM alert_backup"
                ).fetchall()
            ]
    finally:
        engine.dispose()
    assert rows == ['{"kept": true}']
    assert _ALERTS_HEAD in _get_stamped_revisions(sync_url)


def test_fresh_db_with_every_branch_present_logs_nothing(sep_alembic_config, caplog):
    """Leave a full-image upgrade on its existing code path, silently."""
    cfg, sync_url = sep_alembic_config

    with caplog.at_level(logging.WARNING, logger=_ORPHAN_HEADS_LOGGER):
        command.upgrade(cfg, "heads")

    table_names = _get_table_names(sync_url)
    assert "alert_backup" in table_names
    assert "snippet" in table_names
    assert [r for r in caplog.records if r.name == _ORPHAN_HEADS_LOGGER] == []


def test_fresh_db_with_a_stripped_config_materializes_present_branches_only(
    sep_alembic_config_stripped_alerts,
):
    """Create the present branches' tables and none of the stripped app's."""
    stripped_cfg, sync_url, _ = sep_alembic_config_stripped_alerts

    command.upgrade(stripped_cfg, "heads")

    table_names = _get_table_names(sync_url)
    assert "snippet" in table_names
    assert "alert_backup" not in table_names


def test_unknown_revision_is_not_skipped_when_every_location_is_present(
    sep_alembic_config,
):
    """Refuse to filter version skew, so Alembic rejects it exactly as today."""
    cfg, sync_url = sep_alembic_config
    command.upgrade(cfg, "heads")
    _stamp_extra_revision(sync_url, _UNKNOWN_REVISION)

    with pytest.raises(CommandError, match=_UNKNOWN_REVISION):
        command.upgrade(cfg, "heads")


def test_refusal_to_skip_is_explained_before_alembic_raises(sep_alembic_config, caplog):
    """Log an error naming the unresolved id and why it was left in place."""
    cfg, sync_url = sep_alembic_config
    command.upgrade(cfg, "heads")
    _stamp_extra_revision(sync_url, _UNKNOWN_REVISION)

    with (
        caplog.at_level(logging.ERROR, logger=_ORPHAN_HEADS_LOGGER),
        pytest.raises(CommandError),
    ):
        command.upgrade(cfg, "heads")

    records = [
        record
        for record in caplog.records
        if record.name == _ORPHAN_HEADS_LOGGER and record.levelno == logging.ERROR
    ]
    assert len(records) == 1
    assert _UNKNOWN_REVISION in records[0].getMessage()
    assert "present on disk" in records[0].getMessage()


def test_a_stripped_app_and_version_skew_are_skipped_together(
    sep_alembic_config, sep_alembic_config_stripped_alerts, caplog
):
    """Skip both orphan kinds once a configured location is missing, naming each."""
    full_cfg, sync_url = sep_alembic_config
    stripped_cfg, _, _ = sep_alembic_config_stripped_alerts
    command.upgrade(full_cfg, "heads")
    _stamp_extra_revision(sync_url, _UNKNOWN_REVISION)

    with caplog.at_level(logging.WARNING, logger=_ORPHAN_HEADS_LOGGER):
        command.upgrade(stripped_cfg, "heads")

    records = [
        record
        for record in caplog.records
        if record.name == _ORPHAN_HEADS_LOGGER and record.levelno == logging.WARNING
    ]
    assert len(records) == 1
    assert _ALERTS_HEAD in records[0].getMessage()
    assert _UNKNOWN_REVISION in records[0].getMessage()
    stamped = _get_stamped_revisions(sync_url)
    assert {_ALERTS_HEAD, _UNKNOWN_REVISION} <= stamped


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
