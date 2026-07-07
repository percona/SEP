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

"""Define tests for the app.sep.apps.alters.schema module."""

import pytest
from pydantic import ValidationError

from app.sep.apps.alters.models import AltersCreate
from app.sep.apps.alters.schema import alters_schema
from app.sep.apps.framework.schema import EXECUTION_HOST_LABEL

INVENTORY_SCHEMA_ID = 10
INVENTORY_TABLE_ID = 20


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


def test_alters_schema_execution_section_host_labels():
    """Test detail_view Execution section distinguishes execution vs database host."""
    assert alters_schema.detail_view is not None
    execution = next(
        section
        for section in alters_schema.detail_view.sections
        if section.title == "Execution"
    )
    fields = {field.label: field.path for field in execution.fields}
    assert fields[EXECUTION_HOST_LABEL] == "data.meta.target"
    assert fields["Database Host"] == "data.meta._service_host"
    assert "Target" not in fields


def test_alters_schema_form_hostname_label():
    """Test create form hostname field uses the global execution-host label."""
    task_section = next(
        section for section in alters_schema.forms if section.title == "Task"
    )
    hostname = next(field for field in task_section.fields if field.name == "hostname")
    assert hostname.label == EXECUTION_HOST_LABEL


def test_alters_schema_data_free_solo_reference_fields():
    """Test Data section exposes collapsed free-solo schema/table reference fields."""
    data_section = next(
        section for section in alters_schema.forms if section.title == "Data"
    )
    field_names = {field.name for field in data_section.fields}
    assert field_names == {"db_schema", "db_table"}

    schema_field = next(f for f in data_section.fields if f.name == "db_schema")
    table_field = next(f for f in data_section.fields if f.name == "db_table")

    assert schema_field.field_type == "schema"
    assert schema_field.allow_custom is True
    assert schema_field.depends_on == "service_id"
    assert schema_field.required is True

    assert table_field.field_type == "table"
    assert table_field.allow_custom is True
    assert table_field.depends_on == "db_schema"
    assert table_field.required is True


@pytest.mark.parametrize(
    ("db_schema", "db_table"),
    [
        ("a,b", "users"),
        ("a=b", "users"),
        ("app", "a,b"),
        ("app", "a=b"),
    ],
)
def test_alters_create_rejects_dsn_delimiter_in_free_typed_target(db_schema, db_table):
    """AltersCreate rejects DSN delimiters (, or =) in either free-typed target field."""
    with pytest.raises(ValidationError, match="DSN delimiters"):
        AltersCreate(
            task_name="t1",
            hostname="host1",
            service_id=1,
            db_schema=db_schema,
            db_table=db_table,
            alter="ADD COLUMN x INT",
        )


def test_alters_create_requires_schema_and_table():
    """AltersCreate requires both schema and table."""
    with pytest.raises(ValidationError, match="db_schema"):
        AltersCreate(
            task_name="t1",
            hostname="host1",
            service_id=1,
            alter="ADD COLUMN x INT",
        )


def test_alters_create_accepts_inventory_ids_and_free_typed_names():
    """AltersCreate accepts an inventory id or a free-typed name per target field."""
    by_id = AltersCreate(
        task_name="t1",
        hostname="host1",
        service_id=1,
        db_schema=INVENTORY_SCHEMA_ID,
        db_table=INVENTORY_TABLE_ID,
        alter="ADD COLUMN x INT",
    )
    assert by_id.db_schema == INVENTORY_SCHEMA_ID
    assert by_id.db_table == INVENTORY_TABLE_ID

    by_name = AltersCreate(
        task_name="t1",
        hostname="host1",
        service_id=1,
        db_schema="app",
        db_table="users",
        alter="ADD COLUMN x INT",
    )
    assert by_name.db_schema == "app"
    assert by_name.db_table == "users"


def test_alters_create_numeric_string_target_stays_free_typed_name():
    """Keep a purely-numeric free-typed name a string, not coerced to an inventory id."""
    body = AltersCreate(
        task_name="t1",
        hostname="host1",
        service_id=1,
        db_schema="123",
        db_table="42",
        alter="ADD COLUMN x INT",
    )
    assert body.db_schema == "123"
    assert isinstance(body.db_schema, str)
    assert body.db_table == "42"
    assert isinstance(body.db_table, str)


def test_alters_create_strips_free_typed_target_whitespace():
    """Trim surrounding whitespace on a free-typed name at the model boundary."""
    body = AltersCreate(
        task_name="t1",
        hostname="host1",
        service_id=1,
        db_schema=" app ",
        db_table=" users ",
        alter="ADD COLUMN x INT",
    )
    assert body.db_schema == "app"
    assert body.db_table == "users"


@pytest.mark.parametrize("field", ["db_schema", "db_table"])
def test_alters_create_rejects_whitespace_only_target(field):
    """Reject a whitespace-only free-typed name that fails min_length after stripping."""
    kwargs = {
        "task_name": "t1",
        "hostname": "host1",
        "service_id": 1,
        "db_schema": "app",
        "db_table": "users",
        "alter": "ADD COLUMN x INT",
    }
    kwargs[field] = "   "
    with pytest.raises(ValidationError):
        AltersCreate(**kwargs)


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
        db_schema="app",
        db_table="users",
        alter="ADD COLUMN x INT",
        recursion_method="dsn",
        dsn_table="D=percona,t=dsns",
    )
    assert explicit.dsn_table == "D=percona,t=dsns"

    blank_auto_filled = AltersCreate(
        task_name="t1",
        hostname="host1",
        service_id=1,
        db_schema="app",
        db_table="users",
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
        db_schema="app",
        db_table="users",
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
        db_schema="app",
        db_table="users",
        alter="ADD COLUMN x INT",
        recursion_method="dsn",
    )
    assert body.dsn_table == "D=percona,t=dsns"


def test_alters_create_rejects_multiline_alter():
    """AltersCreate rejects an alter command spanning multiple lines."""
    with pytest.raises(ValidationError, match="must not contain newline"):
        AltersCreate(
            task_name="t1",
            hostname="host1",
            service_id=1,
            db_schema="app",
            db_table="users",
            alter="ADD COLUMN x INT\nDROP COLUMN y",
        )


def test_alters_create_rejects_empty_recursion_method():
    """Reject an empty recursion_method."""
    with pytest.raises(ValidationError, match="recursion_method"):
        AltersCreate(
            task_name="t1",
            hostname="host1",
            service_id=1,
            db_schema="app",
            db_table="users",
            alter="ADD COLUMN x INT",
            recursion_method="",
        )


def test_alters_create_continue_on_pre_check_failure_default_false():
    """Keep continue_on_pre_check_failure False by default."""
    body = AltersCreate(
        task_name="t1",
        hostname="host1",
        service_id=1,
        db_schema="app",
        db_table="users",
        alter="ADD COLUMN x INT",
    )
    assert body.continue_on_pre_check_failure is False
