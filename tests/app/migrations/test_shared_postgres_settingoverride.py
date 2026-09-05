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

"""Test the shared-database guards on the ``settingoverride`` migrations.

The ``settingoverride`` table is created by both the SEP and Tasks Alembic
tracks, and both tracks also drop the ``setting_class`` CHECK. On a shared
PostgreSQL database both tracks run ``upgrade heads`` against one physical
schema, so the guarded migrations must apply the DDL exactly once regardless
of which track wins the race. The real-PostgreSQL cases exercise that
cross-track scenario; the SQLite cases pin the two cross-dialect helpers the
guards rely on.
"""

from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import (
    CheckConstraint,
    Column,
    create_engine,
    inspect,
    Integer,
    MetaData,
    String,
    Table,
)
from sqlalchemy import (
    Enum as EnumField,
)
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError
from sqlmodel import select, Session

from app.core.db.utils import (
    acquire_pg_advisory_xact_lock,
    check_constraint_lists_members,
    check_constraint_name,
)
from app.core.encryption import decrypt
from app.core.settings_override.constants import SETTINGOVERRIDE_MIGRATION_LOCK_KEY
from app.core.settings_override.models import SettingOverride
from app.core.utils import json_serializer
from app.core.utils.fields import AsyncDatabaseEngine
from app.sep.config import sep_settings
from app.tasks.config import tasks_settings
from tests.app.core.settings_override.conftest import (
    ALERT_SETTINGS_TOKEN,
    PMM_API_KEY,
    PMM_ENDPOINT,
    ROUTING_KEY,
    SETTINGS_TOKEN,
    TASKS_SETTINGS_TOKEN,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
_SETTING_CLASS_VARCHAR_LENGTH = 255

# The SEP revision immediately below the secret re-encryption one, so a test can
# seed plaintext rows into the state a deployment carrying overrides upgrades from.
_SEP_PRE_ENCRYPTION_REVISION = "867df844fe17"


_SEED_ROWS = [
    (SETTINGS_TOKEN, "PMM", {"endpoint": PMM_ENDPOINT, "api_key": PMM_API_KEY}),
    (SETTINGS_TOKEN, "PMM__api_key", PMM_API_KEY),
    (SETTINGS_TOKEN, "LOGGING", "DEBUG"),
    (
        ALERT_SETTINGS_TOKEN,
        "PROVIDERS",
        [{"PROVIDER": "pagerduty", "routing_key": ROUTING_KEY}],
    ),
    (TASKS_SETTINGS_TOKEN, "STALENESS_THRESHOLD_SECONDS", 7200),
]

# The SEP and Tasks revisions immediately below ``add_setting_override_table``
# on each track — downgrading to them drops the shared table and runs the other
# track's enum-narrowing downgrades against the now-missing table.
_SEP_PRE_SETTINGOVERRIDE_REVISION = "810c31754b54"
_TASKS_PRE_SETTINGOVERRIDE_REVISION = "e42ce8324da7"


def _sqlite_engine_with_setting_class_check(members):
    """Build an in-memory SQLite engine whose ``settingoverride`` CHECK lists ``members``.

    :param members: The enum member names the ``setting_class`` CHECK constraint
        should enumerate.
    :type members: tuple[str, ...]
    :return: A connected in-memory SQLite engine with the table materialized.
    :rtype: Engine
    """
    engine = create_engine("sqlite://")
    metadata = MetaData()
    Table(
        "settingoverride",
        metadata,
        Column("id", Integer, primary_key=True),
        Column(
            "setting_class",
            EnumField(
                *members,
                name="settingclassenum",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
    )
    metadata.create_all(engine)
    return engine


class TestCheckConstraintListsMembers:
    """Cover the cross-dialect ``check_constraint_lists_members`` helper on SQLite."""

    def test_returns_true_for_a_present_member(self):
        """Confirm one listed member is reported as present."""
        engine = _sqlite_engine_with_setting_class_check(
            ("SEP_SETTINGS", "TASKS_SETTINGS")
        )
        try:
            with engine.connect() as conn:
                assert (
                    check_constraint_lists_members(
                        conn, "settingoverride", "setting_class", ("SEP_SETTINGS",)
                    )
                    is True
                )
        finally:
            engine.dispose()

    def test_returns_true_when_all_requested_members_present(self):
        """Confirm ``True`` only when every requested member is listed."""
        engine = _sqlite_engine_with_setting_class_check(
            ("SEP_SETTINGS", "TASKS_SETTINGS", "SETTINGS", "ALERT_SETTINGS")
        )
        try:
            with engine.connect() as conn:
                assert (
                    check_constraint_lists_members(
                        conn,
                        "settingoverride",
                        "setting_class",
                        ("SETTINGS", "ALERT_SETTINGS"),
                    )
                    is True
                )
        finally:
            engine.dispose()

    def test_returns_false_when_a_member_is_absent(self):
        """Confirm ``False`` when the requested member is not listed."""
        engine = _sqlite_engine_with_setting_class_check(
            ("SEP_SETTINGS", "TASKS_SETTINGS", "SETTINGS", "ALERT_SETTINGS")
        )
        try:
            with engine.connect() as conn:
                assert (
                    check_constraint_lists_members(
                        conn,
                        "settingoverride",
                        "setting_class",
                        ("ANONYMIZER_SETTINGS",),
                    )
                    is False
                )
        finally:
            engine.dispose()

    def test_returns_false_when_only_some_members_present(self):
        """Confirm ``False`` when only a subset of the requested members is listed."""
        engine = _sqlite_engine_with_setting_class_check(
            ("SEP_SETTINGS", "TASKS_SETTINGS", "SETTINGS", "ALERT_SETTINGS")
        )
        try:
            with engine.connect() as conn:
                assert (
                    check_constraint_lists_members(
                        conn,
                        "settingoverride",
                        "setting_class",
                        ("SETTINGS", "ANONYMIZER_SETTINGS"),
                    )
                    is False
                )
        finally:
            engine.dispose()

    def test_does_not_match_quoted_substring(self):
        """Match whole quoted tokens so ``SETTINGS`` does not match ``SEP_SETTINGS``."""
        engine = _sqlite_engine_with_setting_class_check(
            ("SEP_SETTINGS", "TASKS_SETTINGS")
        )
        try:
            with engine.connect() as conn:
                assert (
                    check_constraint_lists_members(
                        conn, "settingoverride", "setting_class", ("SETTINGS",)
                    )
                    is False
                )
        finally:
            engine.dispose()

    def test_returns_false_for_missing_table(self):
        """Confirm ``False`` for a missing table instead of raising ``NoSuchTableError``."""
        engine = create_engine("sqlite://")
        try:
            with engine.connect() as conn:
                assert (
                    check_constraint_lists_members(
                        conn, "settingoverride", "setting_class", ("SEP_SETTINGS",)
                    )
                    is False
                )
        finally:
            engine.dispose()


class TestCheckConstraintName:
    """Cover :func:`check_constraint_name` on SQLite."""

    def test_returns_sqlalchemy_enum_constraint_name(self):
        """Return the name SQLAlchemy assigns a non-native enum CHECK."""
        engine = _sqlite_engine_with_setting_class_check(
            ("SEP_SETTINGS", "TASKS_SETTINGS")
        )
        try:
            with engine.connect() as conn:
                assert (
                    check_constraint_name(conn, "settingoverride", "setting_class")
                    == "settingclassenum"
                )
        finally:
            engine.dispose()

    def test_returns_none_for_missing_table(self):
        """Return ``None`` for a missing table instead of raising."""
        engine = create_engine("sqlite://")
        try:
            with engine.connect() as conn:
                assert (
                    check_constraint_name(conn, "settingoverride", "setting_class")
                    is None
                )
        finally:
            engine.dispose()

    def test_returns_none_when_column_has_no_check(self):
        """Return ``None`` when the table exists but the column is unconstrained."""
        engine = create_engine("sqlite://")
        metadata = MetaData()
        Table(
            "settingoverride",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("setting_class", Integer, nullable=False),
        )
        metadata.create_all(engine)
        try:
            with engine.connect() as conn:
                assert (
                    check_constraint_name(conn, "settingoverride", "setting_class")
                    is None
                )
        finally:
            engine.dispose()

    def test_raises_when_multiple_checks_mention_column(self):
        """Fail fast when more than one CHECK mentions the column."""
        engine = create_engine("sqlite://")
        metadata = MetaData()
        Table(
            "settingoverride",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("setting_class", String(64), nullable=False),
            CheckConstraint(
                "setting_class IN ('A', 'B')",
                name="setting_class_enum_check",
            ),
            CheckConstraint(
                "length(setting_class) > 0",
                name="setting_class_nonempty_check",
            ),
        )
        metadata.create_all(engine)
        try:
            with (
                engine.connect() as conn,
                pytest.raises(RuntimeError, match="at most one CHECK"),
            ):
                check_constraint_name(conn, "settingoverride", "setting_class")
        finally:
            engine.dispose()


def test_advisory_lock_is_noop_off_postgres():
    """Issue no SQL and raise nothing when the bind is not PostgreSQL."""
    engine = create_engine("sqlite://")
    try:
        with engine.connect() as conn:
            assert (
                acquire_pg_advisory_xact_lock(conn, SETTINGOVERRIDE_MIGRATION_LOCK_KEY)
                is None
            )
    finally:
        engine.dispose()


@pytest.fixture
def shared_postgres_db(postgres_sync_url, monkeypatch):
    """Configure both the SEP and Tasks tracks to share one real-PostgreSQL database.

    ``command.upgrade`` builds its own engine from ``<svc>_settings.DATABASE.URL``
    via each track's ``env.py`` and writes to the ``public`` schema — it does not
    inherit the ``postgres_engine`` fixture's per-worker schema — so both service
    settings must point at the same host and database for the cross-track race to
    occur. Yield the sync URL for verification and drop every table the upgrade
    created on teardown so the shared schema is left clean for sibling tests.
    """
    for settings in (sep_settings, tasks_settings):
        monkeypatch.setattr(settings.DATABASE, "ENGINE", AsyncDatabaseEngine.POSTGRESQL)
        monkeypatch.setattr(settings.DATABASE, "USER", postgres_sync_url.username)
        monkeypatch.setattr(
            settings.DATABASE,
            "PASSWORD",
            SecretStr(postgres_sync_url.password)
            if postgres_sync_url.password
            else None,
        )
        monkeypatch.setattr(settings.DATABASE, "HOST", postgres_sync_url.host)
        monkeypatch.setattr(settings.DATABASE, "PORT", postgres_sync_url.port)
        monkeypatch.setattr(settings.DATABASE, "NAME", postgres_sync_url.database)
    try:
        yield postgres_sync_url
    finally:
        engine = create_engine(postgres_sync_url)
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql("DROP SCHEMA public CASCADE")
                conn.exec_driver_sql("CREATE SCHEMA public")
        finally:
            engine.dispose()


def _setting_class_check_haystack(sync_url) -> str:
    """Return the joined ``setting_class`` CHECK constraint text for ``settingoverride``."""
    engine = create_engine(sync_url)
    try:
        constraints = inspect(engine).get_check_constraints("settingoverride")
    finally:
        engine.dispose()
    return " ".join(
        constraint["sqltext"] or ""
        for constraint in constraints
        if "setting_class" in (constraint["sqltext"] or "")
    )


@pytest.mark.xdist_group("shared_postgres_db")
@pytest.mark.postgres
def test_shared_db_sep_then_tasks_upgrade_is_clean(shared_postgres_db):
    """Apply the SEP-then-Tasks upgrade on one shared database with no duplicate-table error."""
    sync_url = shared_postgres_db
    sep_cfg = Config(str(ALEMBIC_INI), ini_section="sep")
    tasks_cfg = Config(str(ALEMBIC_INI), ini_section="tasks")

    command.upgrade(sep_cfg, "heads")
    command.upgrade(tasks_cfg, "heads")

    engine = create_engine(sync_url)
    try:
        inspector = inspect(engine)
        assert inspector.has_table("settingoverride")
        assert inspector.has_table("alembic_version_sep")
        assert inspector.has_table("alembic_version_tasks")
        setting_class_type = next(
            column["type"]
            for column in inspector.get_columns("settingoverride")
            if column["name"] == "setting_class"
        )
        assert setting_class_type.length == _SETTING_CLASS_VARCHAR_LENGTH
    finally:
        engine.dispose()

    haystack = _setting_class_check_haystack(sync_url)
    assert haystack == ""


@pytest.mark.xdist_group("shared_postgres_db")
@pytest.mark.postgres
def test_shared_db_tasks_then_sep_upgrade_is_clean(shared_postgres_db):
    """Apply the Tasks-then-SEP upgrade — the reverse order must be equally clean."""
    sync_url = shared_postgres_db
    sep_cfg = Config(str(ALEMBIC_INI), ini_section="sep")
    tasks_cfg = Config(str(ALEMBIC_INI), ini_section="tasks")

    command.upgrade(tasks_cfg, "heads")
    command.upgrade(sep_cfg, "heads")

    engine = create_engine(sync_url)
    try:
        inspector = inspect(engine)
        assert inspector.has_table("settingoverride")
        assert inspector.has_table("alembic_version_sep")
        assert inspector.has_table("alembic_version_tasks")
        setting_class_type = next(
            column["type"]
            for column in inspector.get_columns("settingoverride")
            if column["name"] == "setting_class"
        )
        assert setting_class_type.length == _SETTING_CLASS_VARCHAR_LENGTH
    finally:
        engine.dispose()

    haystack = _setting_class_check_haystack(sync_url)
    assert haystack == ""


@pytest.mark.xdist_group("shared_postgres_db")
@pytest.mark.postgres
def test_shared_db_downgrade_either_order_is_clean(shared_postgres_db):
    """Drop the shared table via SEP, then downgrade Tasks over the missing table.

    The Tasks enum-narrowing downgrades run after the SEP track already dropped
    ``settingoverride``; their guards must no-op instead of raising
    ``NoSuchTableError``.
    """
    sync_url = shared_postgres_db
    sep_cfg = Config(str(ALEMBIC_INI), ini_section="sep")
    tasks_cfg = Config(str(ALEMBIC_INI), ini_section="tasks")

    command.upgrade(sep_cfg, "heads")
    command.upgrade(tasks_cfg, "heads")

    command.downgrade(sep_cfg, _SEP_PRE_SETTINGOVERRIDE_REVISION)
    command.downgrade(tasks_cfg, _TASKS_PRE_SETTINGOVERRIDE_REVISION)

    engine = create_engine(sync_url)
    try:
        assert not inspect(engine).has_table("settingoverride")
    finally:
        engine.dispose()


def _seed_override_rows(sync_url: URL, rows: list[tuple[str, str, Any]]) -> None:
    """Insert one ``settingoverride`` row per entry through a sync engine.

    :param sync_url: The sync URL of the shared database.
    :param rows: ``(setting_class, key, value)`` triples to persist.
    """
    engine = create_engine(sync_url, json_serializer=json_serializer)
    try:
        with Session(engine) as session:
            for setting_class, key, value in rows:
                session.add(
                    SettingOverride(
                        setting_class=setting_class,
                        key=key,
                        value=value,
                        is_active=True,
                    )
                )
            session.commit()
    finally:
        engine.dispose()


def _stored_override_values(sync_url: URL) -> dict[tuple[str, str], Any]:
    """Return every stored override value keyed by ``(setting_class, key)``.

    :param sync_url: The sync URL of the shared database.
    :return: The values as PostgreSQL's ``jsonb`` column returns them.
    """
    engine = create_engine(sync_url, json_serializer=json_serializer)
    try:
        with Session(engine) as session:
            rows = session.exec(select(SettingOverride)).all()
        return {(row.setting_class, row.key): row.value for row in rows}
    finally:
        engine.dispose()


@pytest.mark.xdist_group("shared_postgres_db")
@pytest.mark.postgres
def test_shared_db_secret_rows_are_encrypted_by_the_sep_track(shared_postgres_db):
    """Encrypt the secret leaves of pre-existing rows when the SEP chain reaches them.

    Seeds at the revision below the re-encryption one so the rows already exist
    when it runs, which is the upgrade path a deployment carrying overrides
    takes. The values come back through ``jsonb`` rather than SQLite's ``json``,
    which is what makes this the dialect arm of the walker's coverage.

    The Tasks chain then runs over the same physical table and must neither
    re-encrypt what the SEP chain rewrote nor touch the rows whose
    ``setting_class`` it cannot resolve.
    """
    sync_url = shared_postgres_db
    sep_cfg = Config(str(ALEMBIC_INI), ini_section="sep")
    tasks_cfg = Config(str(ALEMBIC_INI), ini_section="tasks")

    command.upgrade(sep_cfg, _SEP_PRE_ENCRYPTION_REVISION)
    _seed_override_rows(sync_url, _SEED_ROWS)
    before = _stored_override_values(sync_url)

    command.upgrade(sep_cfg, "heads")

    stored = _stored_override_values(sync_url)
    assert decrypt(stored[(SETTINGS_TOKEN, "PMM")]["api_key"]) == PMM_API_KEY
    assert stored[(SETTINGS_TOKEN, "PMM")]["endpoint"] == PMM_ENDPOINT
    assert decrypt(stored[(SETTINGS_TOKEN, "PMM__api_key")]) == PMM_API_KEY
    provider = stored[(ALERT_SETTINGS_TOKEN, "PROVIDERS")][0]
    assert decrypt(provider["routing_key"]) == ROUTING_KEY
    assert provider["PROVIDER"] == "pagerduty"
    assert stored[(SETTINGS_TOKEN, "LOGGING")] == before[(SETTINGS_TOKEN, "LOGGING")]
    assert (
        stored[(TASKS_SETTINGS_TOKEN, "STALENESS_THRESHOLD_SECONDS")]
        == (before[(TASKS_SETTINGS_TOKEN, "STALENESS_THRESHOLD_SECONDS")])
    )

    after_sep = _stored_override_values(sync_url)
    command.upgrade(tasks_cfg, "heads")
    assert _stored_override_values(sync_url) == after_sep


@pytest.mark.xdist_group("shared_postgres_db")
@pytest.mark.postgres
def test_shared_db_downgrade_restores_the_original_plaintext(shared_postgres_db):
    """Return every secret leaf to the plaintext the previous release reads."""
    sync_url = shared_postgres_db
    sep_cfg = Config(str(ALEMBIC_INI), ini_section="sep")

    command.upgrade(sep_cfg, _SEP_PRE_ENCRYPTION_REVISION)
    _seed_override_rows(sync_url, _SEED_ROWS)
    before = _stored_override_values(sync_url)
    command.upgrade(sep_cfg, "heads")
    assert _stored_override_values(sync_url) != before

    command.downgrade(sep_cfg, _SEP_PRE_ENCRYPTION_REVISION)

    assert _stored_override_values(sync_url) == before


@pytest.mark.postgres
def test_advisory_lock_serializes(postgres_sync_url):
    """Verify two connections cannot hold the migration advisory lock at once."""
    engine = create_engine(postgres_sync_url)
    try:
        with engine.connect() as conn_a, engine.connect() as conn_b:
            conn_b.exec_driver_sql("SET lock_timeout = '750ms'")
            conn_b.commit()

            trans_a = conn_a.begin()
            acquire_pg_advisory_xact_lock(conn_a, SETTINGOVERRIDE_MIGRATION_LOCK_KEY)

            trans_b = conn_b.begin()
            with pytest.raises(OperationalError):
                acquire_pg_advisory_xact_lock(
                    conn_b, SETTINGOVERRIDE_MIGRATION_LOCK_KEY
                )
            trans_b.rollback()

            trans_a.commit()

            trans_b_retry = conn_b.begin()
            acquire_pg_advisory_xact_lock(conn_b, SETTINGOVERRIDE_MIGRATION_LOCK_KEY)
            trans_b_retry.commit()
    finally:
        engine.dispose()
