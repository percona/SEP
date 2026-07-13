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

"""Tests for the Checksums create form model."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.sep.apps.checksums.models import ChecksumsForm
from app.sep.apps.checksums.views import checksums_views
from app.sep.apps.framework.form_dsl import derive_app_schema


def _minimal_body(**overrides) -> dict[str, Any]:
    """Return a minimal valid ``ChecksumsForm`` payload."""
    body = {
        "task_name": "chk",
        "hostname": "executor-1",
        "service_id": 1,
        "recursion_method": "processlist",
    }
    body.update(overrides)
    return body


class TestChecksumsFormTargets:
    """Cover multi-value target fields and legacy coercion."""

    def test_legacy_comma_separated_strings_coerce_to_lists(self) -> None:
        """Accept legacy comma-separated ``databases`` / ``tables`` strings."""
        form = ChecksumsForm.model_validate(
            _minimal_body(databases="db1,db2", tables="db1.t1,db1.t2")
        )

        assert form.databases == ["db1", "db2"]
        assert form.tables == ["db1.t1", "db1.t2"]

    def test_legacy_string_with_space_stays_single_entry(self) -> None:
        """Do not split a database name that contains whitespace."""
        form = ChecksumsForm.model_validate(_minimal_body(databases="reporting db"))

        assert form.databases == ["reporting db"]

    def test_list_shape_accepts_inventory_ids_and_custom_names(self) -> None:
        """Accept the new list wire shape with ids and free-typed strings."""
        form = ChecksumsForm.model_validate(
            _minimal_body(databases=[1, "custom_db"], tables=[2, "other.t1"])
        )

        assert form.databases == [1, "custom_db"]
        assert form.tables == [2, "other.t1"]

    def test_free_typed_name_rejects_cli_delimiters(self) -> None:
        """Reject free-typed values that would break comma-separated CLI args."""
        with pytest.raises(ValidationError):
            ChecksumsForm.model_validate(_minimal_body(databases=["bad,name"]))

    def test_schema_derivation_emits_multi_value_free_solo_fields(self) -> None:
        """Derive ``multi_schema`` / ``multi_table`` fields with ``allow_custom`` on ``GET /schema``."""
        schema = derive_app_schema(
            ChecksumsForm,
            checksums_views.layout,
            name="checksums",
            display_name="Checksums",
            list_view=checksums_views.list_view,
        )
        data_fields = {
            field.name: field
            for section in schema.forms
            for field in section.fields
            if field.name in ("databases", "tables")
        }

        assert data_fields["databases"].field_type == "multi_schema"
        assert data_fields["databases"].allow_custom is True
        assert data_fields["databases"].depends_on == "service_id"
        assert data_fields["tables"].field_type == "multi_table"
        assert data_fields["tables"].allow_custom is True
        assert data_fields["tables"].depends_on == "databases"
