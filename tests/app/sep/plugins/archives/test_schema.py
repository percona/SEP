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

from app.sep.plugins.archives.constants import SwapDropEnum
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
        """All field names must match the Write-model attribute names (snake_case).

        ``alert_on_fail`` is intentionally absent: it is rendered by the
        capability-driven control (``capabilities.alert_on_fail``), not as an
        explicit form field, so the form shows exactly one alert-on-fail toggle.
        """
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
        }
        assert expected.issubset(all_names), f"Missing fields: {expected - all_names}"
        assert "alert_on_fail" not in all_names

    def test_no_explicit_alert_on_fail_form_field(self):
        """Only the capability-driven alert-on-fail control renders (no duplicate).

        The schema declares ``capabilities.alert_on_fail=True`` (auto-rendered by
        SchemaFormRenderer); an explicit ``alert_on_fail`` BoolField would render
        a second, duplicate control. Assert the explicit field is gone while the
        capability stays on.
        """
        form_field_names = [
            field.name for section in archives_schema.forms for field in section.fields
        ]
        assert "alert_on_fail" not in form_field_names
        assert archives_schema.capabilities is not None
        assert archives_schema.capabilities.alert_on_fail is True

    def test_advanced_section_collapsed_by_default(self):
        """Rarely-used knobs live in a collapsible 'Advanced' section, collapsed.

        WHERE stays in the visible Options section so the common filter is not
        hidden behind the toggle.
        """
        advanced = next(
            (s for s in archives_schema.forms if s.title == "Advanced"), None
        )
        assert advanced is not None, "Expected an 'Advanced' form section"
        assert advanced.collapsible is True
        assert advanced.collapsed_by_default is True
        advanced_names = {f.name for f in advanced.fields}
        assert advanced_names == {
            "use_index",
            "extra_args",
            "limit",
            "sleep",
            "disable_binlog",
            "disable_bulk_insert",
            "delete_data",
        }
        assert "where" not in advanced_names
        options = next((s for s in archives_schema.forms if s.title == "Options"), None)
        assert options is not None
        assert "where" in {f.name for f in options.fields}

    def test_delete_data_label_and_description(self):
        """Assert delete_data is labelled to disambiguate purge-vs-archive."""
        field = next(
            f
            for section in archives_schema.forms
            for f in section.fields
            if f.name == "delete_data"
        )
        assert field.label == "Delete Without Archiving"
        assert "without being written to any destination" in field.description


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
        fields = [f for form in body["forms"] for f in form["fields"]]
        delete_data = next(f for f in fields if f["name"] == "delete_data")
        assert delete_data["label"] == "Delete Without Archiving"


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
        assert swp_field.requires[0].when.to_dict() == {
            "equals": {"swap_drop": SwapDropEnum.SWAP_ARCHIVE_DROP.value}
        }

    def test_swp_table_suffix_hidden_unless_swap_archive_drop(self):
        """swp_table_suffix is hidden (forbidden) unless swap_drop == 2.

        A requires gate governs required-ness, not visibility; without an
        explicit forbidden gate the field renders for every archive type. Only
        Purge Only is selectable in the current scope, so the gate
        (swap_drop != SWAP_ARCHIVE_DROP) keeps the field from ever rendering.
        """
        swp_field = next(
            f
            for section in archives_schema.forms
            for f in section.fields
            if f.name == "swp_table_suffix"
        )
        assert swp_field.forbidden is not None
        gates = [g.when.to_dict() for g in swp_field.forbidden]
        assert {
            "not_equals": {"swap_drop": SwapDropEnum.SWAP_ARCHIVE_DROP.value}
        } in gates

    def test_where_required_for_purge_only(self):
        """WHERE is required for Purge Only (swap_drop == 0) and not hidden.

        The requires gate (swap_drop != SWAP_DROP) fires for PURGE_ONLY, so WHERE
        is mandatory; the only forbidden gate targets SWAP_DROP, so WHERE is
        never hidden for Purge Only. There is no forbidden-for-Purge-Only gate.
        """
        where_field = next(
            f
            for section in archives_schema.forms
            for f in section.fields
            if f.name == "where"
        )
        assert where_field.requires is not None
        requires_gates = [g.when.to_dict() for g in where_field.requires]
        assert {
            "not_equals": {"swap_drop": SwapDropEnum.SWAP_DROP.value}
        } in requires_gates
        forbidden_gates = [g.when.to_dict() for g in (where_field.forbidden or [])]
        assert {
            "equals": {"swap_drop": SwapDropEnum.SWAP_DROP.value}
        } in forbidden_gates
        assert {
            "equals": {"swap_drop": SwapDropEnum.PURGE_ONLY.value}
        } not in forbidden_gates

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
        all_fail_whens = []
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

    def test_destination_section_hidden_when_delete_data(self):
        """Destination section is hidden when delete_data is truthy."""
        section = next(s for s in archives_schema.forms if s.title == "Destination")
        assert section.forbidden is not None
        gates = [g.when.to_dict() for g in section.forbidden]
        assert {"truthy": "delete_data"} in gates

    def test_destination_host_section_hidden_when_delete_data(self):
        """Destination Host section is hidden when delete_data is truthy."""
        section = next(
            s for s in archives_schema.forms if s.title == "Destination Host"
        )
        assert section.forbidden is not None
        gates = [g.when.to_dict() for g in section.forbidden]
        assert {"truthy": "delete_data"} in gates

    @pytest.mark.parametrize("section_title", ["Destination", "Destination Host"])
    def test_destination_sections_forbidden_gate_in_wire_schema(
        self, section_title: str
    ):
        """Preserve delete_data section forbidden gates in wire schema payload."""
        wire_schema = archives_schema.model_dump(by_alias=True, exclude_none=True)
        section = next(s for s in wire_schema["forms"] if s["title"] == section_title)
        assert {"when": {"truthy": "delete_data"}} in section["forbidden"]

    def test_dest_required_fail_rule_present(self):
        """FailRule fires when no dest and not SWAP_DROP and not delete_data."""
        all_fail_rules = []
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
        all_fail_rules = []
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
        all_fail_rules = []
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
        all_fail_rules = []
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
        all_fail_rules = []
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
