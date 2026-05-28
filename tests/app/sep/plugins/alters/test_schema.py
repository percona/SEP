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

from app.sep.plugins.alters.models import AltersTaskWrite
from app.sep.plugins.alters.schema import alters_schema

DATA_SECTION_FAIL_WHEN_RULE_COUNT = 2


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


def test_alters_schema_serialises_snake_case():
    """Test alters_schema JSON export uses snake_case wire format."""
    payload = alters_schema.model_dump(mode="json", by_alias=False)
    assert "display_name" in payload
    assert "list_view" in payload
    assert payload["name"] == "alters"
    assert payload["derived"][0]["name_suffix"] == "-dry-run"
    assert payload["predecessors"][0]["on_failure"] == "halt"


def test_alters_task_write_dsn_table_required_when_recursion_dsn():
    """Test AltersTaskWrite requires dsn_table when recursion_method is dsn."""
    AltersTaskWrite(
        task_name="t1",
        hostname="host1",
        service_id=1,
        alter="ADD COLUMN x INT",
        recursion_method="dsn",
        dsn_table="D=percona,t=dsns",
    )
    with pytest.raises(ValidationError, match="dsn_table"):
        AltersTaskWrite(
            task_name="t1",
            hostname="host1",
            service_id=1,
            alter="ADD COLUMN x INT",
            recursion_method="dsn",
            dsn_table="",
        )


def test_alters_task_write_rejects_both_inventory_and_manual_targets():
    """Test AltersTaskWrite rejects mixed inventory IDs and manual names."""
    with pytest.raises(ValidationError, match="schema_name"):
        AltersTaskWrite(
            task_name="t1",
            hostname="host1",
            service_id=1,
            schema_id=1,
            table_id=2,
            schema_name="app",
            table_name="users",
            alter="ADD COLUMN x INT",
        )


def test_alters_task_write_continue_on_pre_check_failure_default_false():
    """Test continue_on_pre_check_failure defaults to False on AltersTaskWrite."""
    body = AltersTaskWrite(
        task_name="t1",
        hostname="host1",
        service_id=1,
        alter="ADD COLUMN x INT",
    )
    assert body.continue_on_pre_check_failure is False
