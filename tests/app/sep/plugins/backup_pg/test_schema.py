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

"""Tests for the backup_pg PluginSchema."""

from app.sep.plugins.backup_pg.models import PgBackRestBackupType
from app.sep.plugins.backup_pg.schema import backup_pg_schema

EXPECTED_FIELDS = {
    "task_name",
    "hostname",
    "service_id",
    "alert_on_fail",
    "logging_dir",
    "backup_dir",
    "pgbackrest_bin",
    "pgbackrest_config_file",
    "pgbackrest_backup_type",
    "pgbackrest_datadir",
    "pgbackrest_retention_full",
    "pgbackrest_retention_archive",
    "pgbackrest_incremental_cycle",
}

EXPECTED_LIST_COLUMNS = {"name", "status", "hostname", "created_at"}


def _all_field_names() -> set[str]:
    return {
        field.name for section in backup_pg_schema.forms for field in section.fields
    }


def test_schema_name_is_backup_pg() -> None:
    """Schema name is ``backup_pg`` so plugins_router mounts it correctly."""
    assert backup_pg_schema.name == "backup_pg"


def test_schema_lists_pgbackrest_fields() -> None:
    """Schema exposes every pgBackRest configuration field from the AC."""
    missing = EXPECTED_FIELDS - _all_field_names()
    assert not missing, f"Missing fields: {missing}"


def test_list_view_columns_present() -> None:
    """ListView exposes the parity columns for the React table."""
    assert backup_pg_schema.list_view is not None
    keys = {column.key for column in backup_pg_schema.list_view.columns}
    assert keys >= EXPECTED_LIST_COLUMNS


def test_capabilities_match_jinja_parity() -> None:
    """Capabilities match the Jinja2 chained-tasks/alert/schedule flow."""
    assert backup_pg_schema.capabilities is not None
    assert backup_pg_schema.capabilities.scheduling is True
    assert backup_pg_schema.capabilities.chaining is True
    assert backup_pg_schema.capabilities.alert_on_fail is True


def test_schema_does_not_expose_host_or_port() -> None:
    """Schema does not advertise editable host/port fields.

    The payload pins ``host="localhost"`` and reads ``port`` from the inventory
    service; exposing them on the form would let the FE render editable fields
    that vanish silently on submit.
    """
    field_names = _all_field_names()
    assert "host" not in field_names
    assert "port" not in field_names


def test_schema_has_no_derived_cascade() -> None:
    """No DerivedTask cascade: INCR/DIFF is a single config-driven task."""
    assert not backup_pg_schema.derived


def test_pgbackrest_backup_type_choice_values() -> None:
    """pgbackrest_backup_type offers exactly INCR and DIFF as choices."""
    for section in backup_pg_schema.forms:
        for field in section.fields:
            if field.name == "pgbackrest_backup_type":
                values = {choice.value for choice in field.choices}
                assert values == {
                    PgBackRestBackupType.INCR.value,
                    PgBackRestBackupType.DIFF.value,
                }
                return
    raise AssertionError("pgbackrest_backup_type field not found")
