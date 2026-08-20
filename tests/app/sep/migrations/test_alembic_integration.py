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

import io
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from logging.config import dictConfig, fileConfig

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from rich.logging import RichHandler
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError

from app.core.config import LOGGING_CONFIG
from app.sep.apps.alerts.models import AlertBackup

from .conftest import ALEMBIC_INI, ALERTS_HEAD, UNKNOWN_REVISION

# The add_setting_override_table revision on the SEP track, before SETTINGS /
# ALERT_SETTINGS were added to the setting_class CHECK constraint.
_SEP_PRE_ENUM_REVISION = "ed97b99eef38"

# The add_seppluginperiodictask revision: appstate still has the boolean
# ``enabled`` column, before ``lifecycle_state`` replaces it.
_SEP_PRE_LIFECYCLE_REVISION = "64f10ead74f6"
# The add_lifecycle_state_to_app_state revision under test.
_SEP_LIFECYCLE_REVISION = "a7c4e9f1b2d3"

_ORPHAN_HEADS_LOGGER = "app.sep.migrations._orphan_heads"

_SKIP_NOTICE = (
    "Skipping 2 revision(s) recorded in alembic_version_sep with no migration "
    "script: a1b2c3d4e5f6, 9f8e7d6c5b4a. Configured version_locations that "
    "contributed no revisions: app/sep/apps/alerts/migrations/versions, "
    "app/sep/apps/dipper/migrations/versions."
)
_SKEW_NOTICE = (
    "1 revision(s) recorded in alembic_version_sep do not resolve "
    f"({UNKNOWN_REVISION}) while every configured version_locations entry is "
    "present on disk and contributes at least one revision. That is version "
    "skew or a squashed revision, not a stripped app, so they are left in "
    "place for Alembic to reject."
)


@contextmanager
def _app_then_alembic_logging(stream: io.StringIO) -> Iterator[logging.Logger]:
    """Install app Rich logging, then alembic fileConfig, redirect console to ``stream``.

    Reproduces the real order: settings-driven ``dictConfig`` runs during env
    imports, then ``fileConfig(..., disable_existing_loggers=False)`` runs in
    ``env.py``. Redirect the alembic console handler stream so assertions see
    rendered bytes, not ``caplog`` records. Restore ``LOGGING_CONFIG`` on exit so
    handlers/levels do not leak into later tests.
    """
    try:
        dictConfig(LOGGING_CONFIG)
        fileConfig(str(ALEMBIC_INI), disable_existing_loggers=False)
        root = logging.getLogger()
        for handler in root.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(
                handler, RichHandler
            ):
                handler.setStream(stream)
        app_logger = logging.getLogger("app")
        for handler in app_logger.handlers:
            if isinstance(handler, logging.StreamHandler):
                handler.setStream(stream)
        yield logging.getLogger(_ORPHAN_HEADS_LOGGER)
    finally:
        dictConfig(LOGGING_CONFIG)


def test_app_logger_after_alembic_fileconfig_uses_console_not_rich():
    """Assert alembic fileConfig replaces RichHandler with the console StreamHandler."""
    stream = io.StringIO()
    with _app_then_alembic_logging(stream):
        app_logger = logging.getLogger("app")
        assert not app_logger.propagate
        assert app_logger.handlers, "app logger must keep an explicit handler"
        assert not any(isinstance(h, RichHandler) for h in app_logger.handlers)
        assert any(isinstance(h, logging.StreamHandler) for h in app_logger.handlers)


def test_orphan_skip_warning_renders_as_single_greppable_line():
    """Skip notice stays one line with every revision id and path greppable."""
    stream = io.StringIO()
    with _app_then_alembic_logging(stream) as logger:
        logger.warning(_SKIP_NOTICE)
    output = stream.getvalue()
    matching = [line for line in output.splitlines() if "a1b2c3d4e5f6" in line]
    assert len(matching) == 1, output
    line = matching[0]
    assert "\n" not in line
    for token in (
        "a1b2c3d4e5f6",
        "9f8e7d6c5b4a",
        "app/sep/apps/alerts/migrations/versions",
        "app/sep/apps/dipper/migrations/versions",
        "app.sep.migrations._orphan_heads",
    ):
        assert token in line, (token, line)
    # generic formatter: levelname truncated to 5 chars
    assert "WARNI" in line


def test_version_skew_error_renders_as_single_greppable_line():
    """Render the version-skew ERROR as one greppable console line."""
    stream = io.StringIO()
    with _app_then_alembic_logging(stream) as logger:
        logger.error(_SKEW_NOTICE)
    output = stream.getvalue()
    matching = [line for line in output.splitlines() if UNKNOWN_REVISION in line]
    assert len(matching) == 1, output
    line = matching[0]
    assert UNKNOWN_REVISION in line
    assert "present on disk" in line
    assert "app.sep.migrations._orphan_heads" in line
    assert "ERROR" in line


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


@pytest.fixture
def sep_alembic_config_empty_alerts_versions(sep_alembic_config, tmp_path):
    """Return a Config whose alerts location exists on disk but has no revisions.

    The configured ``versions/`` directory is present (so ``Path.is_dir()``
    would have left the filter fail-closed), yet it contributes no scripts to
    the revision map — the shared evidence for both a package that lost its
    ``__init__.py`` while leaving ``versions/``, and a package left intact
    with an empty ``versions/``.

    :param sep_alembic_config: The full-config fixture whose database is shared.
    :param tmp_path: Pytest's per-test temporary directory.
    :return: A tuple of (Config, sync sqlite URL, the empty alerts path).
    """
    _, sync_url = sep_alembic_config
    empty = tmp_path / "empty" / "alerts" / "migrations" / "versions"
    empty.mkdir(parents=True)
    cfg = Config(str(ALEMBIC_INI), ini_section="sep")
    locations = ScriptDirectory.from_config(cfg).version_locations
    cfg.set_main_option(
        "version_locations",
        ":".join(
            str(empty) if "alerts" in location else location for location in locations
        ),
    )
    return cfg, sync_url, str(empty)


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

    assert ALERTS_HEAD in _get_stamped_revisions(sync_url)


def test_upgrade_logs_every_skipped_revision_id(
    sep_alembic_config, sep_alembic_config_stripped_alerts, capsys
):
    """Name each skipped revision, and the absent location, in one warning."""
    full_cfg, _ = sep_alembic_config
    stripped_cfg, _, absent_path = sep_alembic_config_stripped_alerts
    command.upgrade(full_cfg, "heads")
    capsys.readouterr()

    command.upgrade(stripped_cfg, "heads")
    err = capsys.readouterr().err
    matching = [
        line
        for line in err.splitlines()
        if _ORPHAN_HEADS_LOGGER in line and "Skipping" in line
    ]
    assert len(matching) == 1, err
    assert ALERTS_HEAD in matching[0]
    assert absent_path in matching[0]


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
    assert ALERTS_HEAD in _get_stamped_revisions(sync_url)


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
    assert ALERTS_HEAD in _get_stamped_revisions(sync_url)


def test_fresh_db_with_every_branch_present_logs_nothing(sep_alembic_config, capsys):
    """Leave a full-image upgrade on its existing code path, silently."""
    cfg, sync_url = sep_alembic_config

    command.upgrade(cfg, "heads")
    err = capsys.readouterr().err

    table_names = _get_table_names(sync_url)
    assert "alert_backup" in table_names
    assert "snippet" in table_names
    assert not any(_ORPHAN_HEADS_LOGGER in line for line in err.splitlines())


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
    _stamp_extra_revision(sync_url, UNKNOWN_REVISION)

    with pytest.raises(CommandError, match=UNKNOWN_REVISION):
        command.upgrade(cfg, "heads")


def test_refusal_to_skip_is_explained_before_alembic_raises(sep_alembic_config, capsys):
    """Log an error naming the unresolved id and why it was left in place."""
    cfg, sync_url = sep_alembic_config
    command.upgrade(cfg, "heads")
    _stamp_extra_revision(sync_url, UNKNOWN_REVISION)
    capsys.readouterr()

    with pytest.raises(CommandError):
        command.upgrade(cfg, "heads")

    err = capsys.readouterr().err
    matching = [
        line
        for line in err.splitlines()
        if _ORPHAN_HEADS_LOGGER in line and UNKNOWN_REVISION in line
    ]
    assert len(matching) == 1, err
    assert "present on disk" in matching[0]
    assert "ERROR" in matching[0]


def test_a_stripped_app_and_version_skew_are_skipped_together(
    sep_alembic_config, sep_alembic_config_stripped_alerts, capsys
):
    """Skip both orphan kinds once a configured location is missing, naming each."""
    full_cfg, sync_url = sep_alembic_config
    stripped_cfg, _, _ = sep_alembic_config_stripped_alerts
    command.upgrade(full_cfg, "heads")
    _stamp_extra_revision(sync_url, UNKNOWN_REVISION)
    capsys.readouterr()

    command.upgrade(stripped_cfg, "heads")
    err = capsys.readouterr().err
    matching = [
        line
        for line in err.splitlines()
        if _ORPHAN_HEADS_LOGGER in line and "Skipping" in line
    ]
    assert len(matching) == 1, err
    assert ALERTS_HEAD in matching[0]
    assert UNKNOWN_REVISION in matching[0]
    stamped = _get_stamped_revisions(sync_url)
    assert {ALERTS_HEAD, UNKNOWN_REVISION} <= stamped


def test_upgrade_succeeds_when_versions_dir_exists_but_is_empty(
    sep_alembic_config, sep_alembic_config_empty_alerts_versions
):
    """Upgrade when alerts' versions/ is present on disk but contributes nothing."""
    full_cfg, _ = sep_alembic_config
    empty_cfg, _, _ = sep_alembic_config_empty_alerts_versions
    command.upgrade(full_cfg, "heads")

    command.upgrade(empty_cfg, "heads")


def test_upgrade_preserves_the_unresolvable_row_when_versions_dir_is_empty(
    sep_alembic_config, sep_alembic_config_empty_alerts_versions
):
    """Keep the orphaned alerts row when the filter arms on an empty versions/."""
    full_cfg, sync_url = sep_alembic_config
    empty_cfg, _, _ = sep_alembic_config_empty_alerts_versions
    command.upgrade(full_cfg, "heads")

    command.upgrade(empty_cfg, "heads")

    assert ALERTS_HEAD in _get_stamped_revisions(sync_url)


def test_upgrade_logs_empty_location_that_armed_the_filter(
    sep_alembic_config, sep_alembic_config_empty_alerts_versions, capsys
):
    """Name the empty versions/ location in the skip WARNING."""
    full_cfg, _ = sep_alembic_config
    empty_cfg, _, empty_path = sep_alembic_config_empty_alerts_versions
    command.upgrade(full_cfg, "heads")
    capsys.readouterr()

    command.upgrade(empty_cfg, "heads")
    err = capsys.readouterr().err
    matching = [
        line
        for line in err.splitlines()
        if _ORPHAN_HEADS_LOGGER in line and "Skipping" in line
    ]
    assert len(matching) == 1, err
    assert ALERTS_HEAD in matching[0]
    assert empty_path in matching[0]
    assert "contributed no revisions" in matching[0]


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
