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

The ``settingoverride`` table is created by the SEP, Tasks and Inventory
Alembic tracks alike, and every track also drops the ``setting_class`` CHECK
and adds the ``updated_by`` actor column. On a shared PostgreSQL database the
tracks run ``upgrade heads`` against one physical schema, so the guarded
migrations must apply the DDL exactly once regardless of which track wins the
race. The real-PostgreSQL cases exercise that cross-track scenario; the SQLite
cases pin the cross-dialect helpers the guards rely on.
"""

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
    text,
)
from sqlalchemy import (
    Enum as EnumField,
)
from sqlalchemy.exc import OperationalError

from app.core.db.utils import (
    acquire_pg_advisory_xact_lock,
    check_constraint_lists_members,
    check_constraint_name,
    column_exists,
)
from app.core.settings_override.constants import (
    SETTINGOVERRIDE_MIGRATION_LOCK_KEY,
    SETTINGOVERRIDE_UPDATED_BY_COLUMN,
)
from app.core.utils.fields import AsyncDatabaseEngine
from app.inventory.config import inventory_settings
from app.sep.config import sep_settings
from app.tasks.config import tasks_settings
from tests.app.alembic_paths import ALEMBIC_INI

_SETTING_CLASS_VARCHAR_LENGTH = 255
#: A username far longer than any bounded column would have allowed, used to
#: prove ``updated_by`` carries no width on the deployment dialect.
_LONG_USERNAME_LENGTH = 512
#: The ``SYNC_REFRESH_TIME`` value seeded before a downgrade, read back through
#: the JSONB column to prove the drop left the row's data intact.
_SEEDED_OVERRIDE_VALUE = 5

# The SEP and Tasks revisions immediately below ``add_setting_override_table``
# on each track — downgrading to them drops the shared table and runs the other
# track's enum-narrowing downgrades against the now-missing table.
_SEP_PRE_SETTINGOVERRIDE_REVISION = "810c31754b54"
_TASKS_PRE_SETTINGOVERRIDE_REVISION = "e42ce8324da7"

# The SEP revision immediately below ``add_settingoverride_updated_by``, so a
# downgrade to it runs exactly the column drop.
_SEP_PRE_UPDATED_BY_REVISION = "867df844fe17"


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
    """Configure the SEP, Tasks and Inventory tracks to share one real-PostgreSQL database.

    ``command.upgrade`` builds its own engine from ``<svc>_settings.DATABASE.URL``
    via each track's ``env.py`` and writes to the ``public`` schema — it does not
    inherit the ``postgres_engine`` fixture's per-worker schema — so every service
    settings must point at the same host and database for the cross-track race to
    occur. Yield the sync URL for verification and drop every table the upgrade
    created on teardown so the shared schema is left clean for sibling tests.
    """
    for settings in (sep_settings, tasks_settings, inventory_settings):
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


class TestColumnExists:
    """Cover the cross-dialect :func:`column_exists` helper on SQLite."""

    def test_returns_true_for_a_declared_column(self):
        """Report a column the table declares as present."""
        engine = _sqlite_engine_with_setting_class_check(("SEP_SETTINGS",))
        try:
            with engine.connect() as conn:
                assert column_exists(conn, "settingoverride", "setting_class") is True
        finally:
            engine.dispose()

    def test_returns_false_for_an_absent_column(self):
        """Report a column the table does not declare as absent."""
        engine = _sqlite_engine_with_setting_class_check(("SEP_SETTINGS",))
        try:
            with engine.connect() as conn:
                assert (
                    column_exists(
                        conn, "settingoverride", SETTINGOVERRIDE_UPDATED_BY_COLUMN
                    )
                    is False
                )
        finally:
            engine.dispose()

    def test_returns_false_for_missing_table(self):
        """Report ``False`` for a missing table instead of raising ``NoSuchTableError``."""
        engine = create_engine("sqlite://")
        try:
            with engine.connect() as conn:
                assert (
                    column_exists(
                        conn, "settingoverride", SETTINGOVERRIDE_UPDATED_BY_COLUMN
                    )
                    is False
                )
        finally:
            engine.dispose()


@pytest.mark.postgres
def test_column_exists_on_real_postgres(postgres_sync_url):
    """Distinguish a declared from an undeclared column on the deployment dialect."""
    engine = create_engine(postgres_sync_url)
    metadata = MetaData()
    Table(
        "settingoverride_column_probe",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("setting_class", String(64), nullable=False),
    )
    try:
        metadata.create_all(engine)
        try:
            with engine.connect() as conn:
                assert (
                    column_exists(conn, "settingoverride_column_probe", "setting_class")
                    is True
                )
                assert (
                    column_exists(
                        conn,
                        "settingoverride_column_probe",
                        SETTINGOVERRIDE_UPDATED_BY_COLUMN,
                    )
                    is False
                )
        finally:
            metadata.drop_all(engine)
    finally:
        engine.dispose()


def _updated_by_columns(sync_url) -> list[dict]:
    """Return every reflected ``settingoverride`` column named ``updated_by``.

    :param sync_url: The sync URL of the shared database to inspect.
    :return: The matching inspector column dicts.
    """
    engine = create_engine(sync_url)
    try:
        columns = inspect(engine).get_columns("settingoverride")
    finally:
        engine.dispose()
    return [
        column
        for column in columns
        if column["name"] == SETTINGOVERRIDE_UPDATED_BY_COLUMN
    ]


@pytest.mark.xdist_group("shared_postgres_db")
@pytest.mark.postgres
@pytest.mark.parametrize(
    "order",
    [("sep", "tasks", "inventory"), ("tasks", "sep", "inventory")],
    ids=["sep-first", "tasks-first"],
)
def test_shared_db_three_track_upgrade_adds_updated_by_once(shared_postgres_db, order):
    """Add ``updated_by`` exactly once however the three tracks interleave."""
    sync_url = shared_postgres_db
    for section in order:
        command.upgrade(Config(str(ALEMBIC_INI), ini_section=section), "heads")

    engine = create_engine(sync_url)
    try:
        inspector = inspect(engine)
        assert inspector.has_table("alembic_version_sep")
        assert inspector.has_table("alembic_version_tasks")
        assert inspector.has_table("alembic_version_inventory")
    finally:
        engine.dispose()

    matching = _updated_by_columns(sync_url)
    assert len(matching) == 1
    assert matching[0]["nullable"] is True


@pytest.mark.xdist_group("shared_postgres_db")
@pytest.mark.postgres
def test_shared_db_rerunning_a_track_upgrade_is_a_noop(shared_postgres_db):
    """Re-run one track's ``upgrade heads`` without a duplicate-column error."""
    sync_url = shared_postgres_db
    sep_cfg = Config(str(ALEMBIC_INI), ini_section="sep")
    command.upgrade(sep_cfg, "heads")
    command.upgrade(Config(str(ALEMBIC_INI), ini_section="tasks"), "heads")

    command.upgrade(sep_cfg, "heads")

    assert len(_updated_by_columns(sync_url)) == 1


@pytest.mark.xdist_group("shared_postgres_db")
@pytest.mark.postgres
def test_shared_db_long_actor_round_trips(shared_postgres_db):
    """Store an unusually long username intact on the deployment dialect.

    The column is unbounded, so there is no width for a long username to exceed;
    a bounded one would raise ``StringDataRightTruncation`` here while passing on
    SQLite, which ignores ``VARCHAR`` lengths.
    """
    sync_url = shared_postgres_db
    command.upgrade(Config(str(ALEMBIC_INI), ini_section="sep"), "heads")
    actor = "a" * _LONG_USERNAME_LENGTH

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO settingoverride "
                    "(setting_class, key, value, is_active, created_at, updated_by) "
                    "VALUES ('SEP_SETTINGS', 'SYNC_REFRESH_TIME', '5', true, now(), "
                    ":actor)"
                ),
                {"actor": actor},
            )
        with engine.connect() as conn:
            stored = conn.execute(text("SELECT updated_by FROM settingoverride"))
            assert stored.scalar_one() == actor
    finally:
        engine.dispose()


@pytest.mark.xdist_group("shared_postgres_db")
@pytest.mark.postgres
def test_shared_db_downgrade_drops_updated_by_and_keeps_the_rows(shared_postgres_db):
    """Drop ``updated_by`` on downgrade while the override rows and values survive."""
    sync_url = shared_postgres_db
    sep_cfg = Config(str(ALEMBIC_INI), ini_section="sep")
    command.upgrade(sep_cfg, "heads")
    command.upgrade(Config(str(ALEMBIC_INI), ini_section="tasks"), "heads")

    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO settingoverride "
                    "(setting_class, key, value, is_active, created_at, updated_by) "
                    "VALUES ('SEP_SETTINGS', 'SYNC_REFRESH_TIME', '5', true, now(), "
                    "'alice')"
                )
            )
    finally:
        engine.dispose()

    command.downgrade(sep_cfg, _SEP_PRE_UPDATED_BY_REVISION)

    assert _updated_by_columns(sync_url) == []
    engine = create_engine(sync_url)
    try:
        with engine.connect() as conn:
            surviving = conn.execute(
                text("SELECT value FROM settingoverride WHERE key = :key"),
                {"key": "SYNC_REFRESH_TIME"},
            )
            # ``value`` is JSONB, so the driver decodes the stored ``'5'`` back
            # to a Python int rather than the literal that was inserted.
            assert surviving.scalar_one() == _SEEDED_OVERRIDE_VALUE
    finally:
        engine.dispose()
