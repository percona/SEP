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

"""Define tests for the app.sep.plugins.alters.schema module."""

import pytest
from pydantic import ValidationError

from app.sep.plugins.alters.models import AltersCreate
from app.sep.plugins.alters.schema import alters_schema

DATA_SECTION_FAIL_WHEN_RULE_COUNT = 2
LEGACY_FORM_SCHEMA_ID = 10
LEGACY_FORM_TABLE_ID = 20
TASK_WRITE_SCHEMA_ID = 1
TASK_WRITE_TABLE_ID = 2


def test_alters_schema_declares_cascade_primitives():
    """Test alters_schema declares derived dry-run and chained pre-checks predecessors."""
    assert alters_schema.derived is not None
    assert len(alters_schema.derived) == 1
    assert alters_schema.derived[0].name_suffix == "-dry-run"
    assert alters_schema.derived[0].arg_substitutions == {"--execute": "--dry-run"}

    assert alters_schema.predecessors is not None
    assert len(alters_schema.predecessors) == 1
    assert alters_schema.predecessors[0].name_suffix == "-pre-checks"
    assert alters_schema.predecessors[0].on_failure == "halt"


def test_alters_schema_data_target_mutual_exclusion_gates():
    """Test Data section gates hide inventory vs manual target fields."""
    data_section = next(
        section for section in alters_schema.forms if section.title == "Data"
    )
    schema_id = next(f for f in data_section.fields if f.name == "schema_id")
    table_id = next(f for f in data_section.fields if f.name == "table_id")
    schema_name = next(f for f in data_section.fields if f.name == "schema_name")
    table_name = next(f for f in data_section.fields if f.name == "table_name")

    assert schema_id.forbidden is not None
    assert table_id.forbidden is not None
    assert schema_name.forbidden is not None
    assert table_name.forbidden is not None
    assert data_section.fail_when is not None
    assert len(data_section.fail_when) == DATA_SECTION_FAIL_WHEN_RULE_COUNT


def test_alters_schema_dsn_table_conditional_gates():
    """Test dsn_table declares requires + forbidden gates for recursion_method dsn."""
    recursion_section = next(
        section for section in alters_schema.forms if section.title == "Recursion"
    )
    dsn_field = next(
        field for field in recursion_section.fields if field.name == "dsn_table"
    )
    assert dsn_field.requires is not None
    assert len(dsn_field.requires) == 1
    assert dsn_field.forbidden is not None
    assert len(dsn_field.forbidden) == 1


def test_alters_schema_alter_is_single_line_string():
    """Test the alter field renders as a single-line string input, not a textarea."""
    alter_section = next(
        section for section in alters_schema.forms if section.title == "Alter"
    )
    alter_field = next(field for field in alter_section.fields if field.name == "alter")
    assert alter_field.field_type == "string"


def test_alters_schema_serialises_snake_case():
    """Test alters_schema JSON export uses snake_case wire format."""
    payload = alters_schema.model_dump(mode="json", by_alias=False)
    assert "display_name" in payload
    assert "list_view" in payload
    assert payload["name"] == "alters"
    assert payload["derived"][0]["name_suffix"] == "-dry-run"
    assert payload["predecessors"][0]["on_failure"] == "halt"


def test_alters_create_dsn_table_for_dsn_recursion():
    """Accept an explicit dsn_table and auto-fill a blank one for dsn recursion."""
    explicit = AltersCreate(
        task_name="t1",
        hostname="host1",
        service_id=1,
        schema_name="app",
        table_name="users",
        alter="ADD COLUMN x INT",
        recursion_method="dsn",
        dsn_table="D=percona,t=dsns",
    )
    assert explicit.dsn_table == "D=percona,t=dsns"

    blank_auto_filled = AltersCreate(
        task_name="t1",
        hostname="host1",
        service_id=1,
        schema_name="app",
        table_name="users",
        alter="ADD COLUMN x INT",
        recursion_method="dsn",
        dsn_table="",
    )
    assert blank_auto_filled.dsn_table == "D=percona,t=dsns"


def test_alters_create_dsn_table_accepts_explicit_value():
    """Keep an explicit dsn_table when recursion_method is dsn."""
    body = AltersCreate(
        task_name="t1",
        hostname="host1",
        service_id=1,
        schema_name="app",
        table_name="users",
        alter="ADD COLUMN x INT",
        recursion_method="dsn",
        dsn_table="D=custom,t=dsns",
    )
    assert body.dsn_table == "D=custom,t=dsns"


def test_alters_create_dsn_recursion_uses_schema_default_dsn_table() -> None:
    """Apply the schema dsn_table default when a dsn client omits it, not a 422."""
    body = AltersCreate(
        task_name="t1",
        hostname="host1",
        service_id=1,
        schema_name="app",
        table_name="users",
        alter="ADD COLUMN x INT",
        recursion_method="dsn",
    )
    assert body.dsn_table == "D=percona,t=dsns"


def test_alters_create_rejects_dual_target_fields():
    """AltersCreate rejects input that provides both inventory IDs and manual names."""
    with pytest.raises(ValidationError, match="Cannot use both schema_id/table_id"):
        AltersCreate.model_validate(
            {
                "task_name": "t1",
                "hostname": "host1",
                "service_id": 1,
                "schema_id": str(LEGACY_FORM_SCHEMA_ID),
                "table_id": str(LEGACY_FORM_TABLE_ID),
                "schema_name": "app",
                "table_name": "users",
                "alter": "ADD COLUMN x INT",
                "recursion_method": "processlist",
            }
        )


def test_alters_create_rejects_dual_target_fields_from_kwargs():
    """AltersCreate rejects kwargs that provide both inventory IDs and manual names."""
    with pytest.raises(ValidationError, match="Cannot use both schema_id/table_id"):
        AltersCreate(
            task_name="t1",
            hostname="host1",
            service_id=1,
            schema_id=TASK_WRITE_SCHEMA_ID,
            table_id=TASK_WRITE_TABLE_ID,
            schema_name="app",
            table_name="users",
            alter="ADD COLUMN x INT",
        )


def test_alters_create_rejects_multiline_alter():
    """AltersCreate rejects an alter command spanning multiple lines."""
    with pytest.raises(ValidationError, match="must not contain newline"):
        AltersCreate(
            task_name="t1",
            hostname="host1",
            service_id=1,
            schema_name="app",
            table_name="users",
            alter="ADD COLUMN x INT\nDROP COLUMN y",
        )


def test_alters_create_rejects_empty_recursion_method():
    """Reject an empty recursion_method."""
    with pytest.raises(ValidationError, match="recursion_method"):
        AltersCreate(
            task_name="t1",
            hostname="host1",
            service_id=1,
            schema_name="app",
            table_name="users",
            alter="ADD COLUMN x INT",
            recursion_method="",
        )


def test_alters_create_continue_on_pre_check_failure_default_false():
    """Keep continue_on_pre_check_failure False by default."""
    body = AltersCreate(
        task_name="t1",
        hostname="host1",
        service_id=1,
        schema_name="app",
        table_name="users",
        alter="ADD COLUMN x INT",
    )
    assert body.continue_on_pre_check_failure is False
