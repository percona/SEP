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

"""Unit tests for the archives plugin schema declaration."""

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.sep.plugins.archives.schema import archives_schema


class TestArchivesSchemaStructure:
    """Static metadata checks: capabilities and field name set."""

    def test_capabilities(self):
        """archives_schema must have chaining, alert_on_fail, scheduling, stats."""
        caps = archives_schema.capabilities
        assert caps is not None
        assert caps.chaining is True
        assert caps.alert_on_fail is True
        assert caps.scheduling is True
        assert caps.stats is True

    def test_field_names_are_snake_case(self):
        """All field names must match the Write-model attribute names (snake_case)."""
        all_names = {
            field.name for section in archives_schema.forms for field in section.fields
        }
        expected = {
            "alias",
            "hostname",
            "service_id",
            "source_db_id",
            "source_db_name",
            "source_table_id",
            "source_table_name",
            "source_query",
            "where",
            "swap_drop",
            "dest_file",
            "dest_table_id",
            "dest_table_name",
            "swp_table_suffix",
            "use_index",
            "extra_args",
            "limit",
            "sleep",
            "disable_binlog",
            "disable_bulk_insert",
            "delete_data",
            "dest_service_id",
            "dest_host",
            "dest_port",
            "dest_db_id",
            "dest_db_name",
            "alert_on_fail",
        }
        assert expected.issubset(all_names), f"Missing fields: {expected - all_names}"


class TestArchivesSchemaEndpoint:
    """HTTP-level checks for GET /api/plugins/archives/schema."""

    def test_requires_auth(self, unauthenticated_client: TestClient):
        """GET /api/plugins/archives/schema returns 401 without auth."""
        response = unauthenticated_client.get("/api/plugins/archives/schema")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_authenticated(self, test_client: TestClient):
        """GET /api/plugins/archives/schema returns 200 when authenticated."""
        response = test_client.get("/api/plugins/archives/schema")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["name"] == "archives"
        assert body["capabilities"]["stats"] is True
        assert body["capabilities"]["chaining"] is True


class TestArchivesSchemaFieldGates:
    """Field-level requires/forbidden gate assertions (validators 4, 5, 6)."""

    def test_swp_table_suffix_requires_swap_archive_drop(self):
        """swp_table_suffix.requires gates on swap_drop == 2."""
        swp_field = next(
            f
            for section in archives_schema.forms
            for f in section.fields
            if f.name == "swp_table_suffix"
        )
        assert swp_field.requires is not None
        assert len(swp_field.requires) == 1
        assert swp_field.requires[0].when.to_dict() == {"equals": {"swap_drop": 2}}

    def test_where_requires_when_not_swap_drop(self):
        """where.requires fires when swap_drop != 1 (SWAP_DROP)."""
        where_field = next(
            f
            for section in archives_schema.forms
            for f in section.fields
            if f.name == "where"
        )
        assert where_field.requires is not None
        gates = [g.when.to_dict() for g in where_field.requires]
        assert {"not_equals": {"swap_drop": 1}} in gates

    def test_where_forbidden_when_swap_drop(self):
        """where.forbidden fires when swap_drop == 1 (SWAP_DROP)."""
        where_field = next(
            f
            for section in archives_schema.forms
            for f in section.fields
            if f.name == "where"
        )
        assert where_field.forbidden is not None
        gates = [g.when.to_dict() for g in where_field.forbidden]
        assert {"equals": {"swap_drop": 1}} in gates

    @pytest.mark.parametrize(
        "field_name",
        ["source_db_id", "source_table_id", "source_db_name", "source_table_name"],
    )
    def test_source_fields_forbidden_when_source_query(self, field_name: str):
        """source_db/table fields are forbidden when source_query is truthy."""
        field = next(
            f
            for section in archives_schema.forms
            for f in section.fields
            if f.name == field_name
        )
        assert field.forbidden is not None
        gates = [g.when.to_dict() for g in field.forbidden]
        assert {"truthy": "source_query"} in gates


class TestArchivesSchemaFailRules:
    """Section- and schema-level FailRule assertions (validators 1, 2, 3)."""

    def test_source_query_missing_sources_fail_rule(self):
        """FailRule fires when source_query absent and no IDs/names are provided."""
        all_fail_whens: list[dict] = []
        for section in archives_schema.forms:
            if section.fail_when:
                all_fail_whens.extend(r.fail_when.to_dict() for r in section.fail_when)
        if archives_schema.fail_when:
            all_fail_whens.extend(
                r.fail_when.to_dict() for r in archives_schema.fail_when
            )

        # At least one FailRule references source_db_id AND source_table_id in its predicate
        found = any(
            "source_db_id" in str(fw) and "source_table_id" in str(fw)
            for fw in all_fail_whens
        )
        assert found, (
            "Expected a FailRule for missing source IDs/names when no source_query"
        )

    @pytest.mark.parametrize(
        "field_name", ["dest_file", "dest_table_id", "dest_table_name"]
    )
    def test_dest_fields_forbidden_when_swap_drop_or_delete_data(self, field_name: str):
        """dest_file/dest_table_id/dest_table_name are forbidden with SWAP_DROP or delete_data."""
        field = next(
            f
            for section in archives_schema.forms
            for f in section.fields
            if f.name == field_name
        )
        assert field.forbidden is not None
        gates = [g.when.to_dict() for g in field.forbidden]

        expected = {"any": [{"equals": {"swap_drop": 1}}, {"truthy": "delete_data"}]}
        assert expected in gates

    def test_dest_required_fail_rule_present(self):
        """FailRule fires when no dest and not SWAP_DROP and not delete_data."""
        all_fail_rules: list = []
        for section in archives_schema.forms:
            if section.fail_when:
                all_fail_rules.extend(section.fail_when)
        if archives_schema.fail_when:
            all_fail_rules.extend(archives_schema.fail_when)

        error_fields_sets = [set(r.error_fields) for r in all_fail_rules]
        dest_fields = {"dest_file", "dest_table_id", "dest_table_name"}
        assert any(dest_fields.issubset(s) for s in error_fields_sets), (
            "Expected a FailRule with error_fields covering all dest fields"
        )

    def test_same_table_id_fail_rule_present(self):
        """FailRule fires when source_table_id == dest_table_id (both present)."""
        all_fail_rules: list = []
        for section in archives_schema.forms:
            if section.fail_when:
                all_fail_rules.extend(section.fail_when)
        if archives_schema.fail_when:
            all_fail_rules.extend(archives_schema.fail_when)

        error_field_sets = [set(r.error_fields) for r in all_fail_rules]
        assert any("dest_table_id" in s for s in error_field_sets), (
            "Expected a FailRule with dest_table_id in error_fields for same-table check"
        )

    def test_same_table_id_fail_rule_wire_format(self):
        """FailRule for same IDs must use all_equal wire shape."""
        all_fail_rules: list = []
        for section in archives_schema.forms:
            if section.fail_when:
                all_fail_rules.extend(section.fail_when)
        if archives_schema.fail_when:
            all_fail_rules.extend(archives_schema.fail_when)

        table_id_rules = [
            r
            for r in all_fail_rules
            if "dest_table_id" in r.error_fields and "source_table_id" in r.error_fields
        ]
        assert table_id_rules, (
            "Expected a FailRule with source_table_id+dest_table_id in error_fields"
        )
        wire = table_id_rules[0].fail_when.to_dict()
        wire_str = str(wire)
        assert "all_equal" in wire_str
        assert "source_table_id" in wire_str
        assert "dest_table_id" in wire_str

    def test_dest_service_id_and_host_mutual_exclusion_fail_rule(self):
        """FailRule for dest_service_id + dest_host conflict is present."""
        all_fail_rules: list = []
        for section in archives_schema.forms:
            if section.fail_when:
                all_fail_rules.extend(section.fail_when)
        if archives_schema.fail_when:
            all_fail_rules.extend(archives_schema.fail_when)

        found = any(
            "dest_service_id" in r.error_fields and "dest_host" in r.error_fields
            for r in all_fail_rules
        )
        assert found, (
            "Expected a FailRule for dest_service_id + dest_host mutual exclusion"
        )

    def test_swap_archive_drop_forbids_dest_host_fail_rule(self):
        """FailRule fires when swap_drop==2 and dest host is set."""
        all_fail_rules: list = []
        for section in archives_schema.forms:
            if section.fail_when:
                all_fail_rules.extend(section.fail_when)
        if archives_schema.fail_when:
            all_fail_rules.extend(archives_schema.fail_when)

        found = any(
            "dest_host" in r.error_fields
            and "equals" in str(r.fail_when.to_dict())
            and "swap_drop" in str(r.fail_when.to_dict())
            and "2" in str(r.fail_when.to_dict())
            for r in all_fail_rules
        )
        assert found, "Expected a FailRule for SWAP_ARCHIVE_DROP + dest_host"


class TestArchivesSchemaCardinality:
    """CardinalityRule assertions for mutually exclusive destination fields."""

    def test_dest_cardinality_rule_max_one(self):
        """Destination section has CardinalityRule(max=1) over dest fields."""
        found = False
        for section in archives_schema.forms:
            if section.cardinality_rules:
                for rule in section.cardinality_rules:
                    dest_set = {"dest_file", "dest_table_id", "dest_table_name"}
                    if dest_set.issubset(set(rule.fields)) and rule.max == 1:
                        found = True
        assert found, (
            "Expected CardinalityRule(max=1) covering dest_file/dest_table_id/dest_table_name"
        )
