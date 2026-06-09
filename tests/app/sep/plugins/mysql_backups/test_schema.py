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

"""Tests for the mysql_backups plugin schema."""

from app.sep.plugins.framework.rules import F, FieldGate
from app.sep.plugins.framework.schema import (
    Capabilities,
    ChoiceField,
    ColumnFormat,
    MultiChoiceField,
    PluginSchema,
)
from app.sep.plugins.mysql_backups.models import BackupCreate
from app.sep.plugins.mysql_backups.schema import mysql_backups_schema


class TestMysqlBackupsSchema:
    """Tests for the ``mysql_backups_schema`` PluginSchema definition."""

    def test_schema_is_plugin_schema(self):
        """The exported schema is a ``PluginSchema``."""
        assert isinstance(mysql_backups_schema, PluginSchema)
        assert mysql_backups_schema.name == "mysql_backups"

    def test_capabilities(self):
        """Capabilities mirror the Jinja2 backups (chaining, alerts, scheduling)."""
        assert mysql_backups_schema.capabilities == Capabilities(
            chaining=True, alert_on_fail=True, scheduling=True
        )
        assert mysql_backups_schema.capabilities.stats is False

    def test_list_view_columns(self):
        """List view exposes the per-ticket column set."""
        columns = {col.key: col for col in mysql_backups_schema.list_view.columns}
        assert {
            "name",
            "status",
            "backup_type",
            "hostname",
            "created_at",
            "created_by",
        } <= set(columns)
        assert columns["status"].format == ColumnFormat.STATUS
        assert columns["backup_type"].format == ColumnFormat.CHIP
        assert columns["created_at"].format == ColumnFormat.RELATIVE
        # name is sortable for the standard "Name" header treatment
        assert columns["name"].sortable is True

    def test_form_sections_present(self):
        """All six required form sections exist."""
        titles = [section.title for section in mysql_backups_schema.forms]
        expected = {"Task", "Mydumper", "XtraBackup", "Binlog", "Encryption", "Upload"}
        assert expected <= set(titles), (
            f"Missing form sections: {expected - set(titles)}"
        )

    def test_backup_type_is_choice_field(self):
        """``backup_type`` is a ChoiceField with M/X/B values."""
        fields = {
            field.name: field
            for section in mysql_backups_schema.forms
            for field in section.fields
        }
        bt = fields["backup_type"]
        assert isinstance(bt, ChoiceField)
        assert {choice.value for choice in bt.choices} == {"M", "X", "B"}
        assert bt.required is True

    def test_upload_is_multi_choice_field(self):
        """``upload`` is a required MultiChoiceField with the three upload providers."""
        fields = {
            field.name: field
            for section in mysql_backups_schema.forms
            for field in section.fields
        }
        upload = fields["upload"]
        assert isinstance(upload, MultiChoiceField)
        assert {choice.value for choice in upload.choices} == {"RSYNC", "S3", "GSUTIL"}
        assert upload.required is True

    def test_upload_destination_fields_gated_on_upload(self):
        """``s3_bucket``/``gs_bucket``/``rsync_path`` are hidden when their provider is absent.

        Each destination field declares a ``forbidden`` gate keyed off the
        ``upload`` MultiChoice via the ``Contains`` predicate. This pins the
        explicit-MultiChoice contract: the React renderer hides the
        field (and unregisters it from RHF) when the matching provider is
        not selected, and the backend's conditional-rule plan rejects a
        present value in the same case.
        """
        fields = {
            field.name: field
            for section in mysql_backups_schema.forms
            for field in section.fields
        }
        cases = [
            ("s3_bucket", "S3"),
            ("s3_storage_class", "S3"),
            ("awscli_s3_upload_extra_args", "S3"),
            ("gs_bucket", "GSUTIL"),
            ("rsync_path", "RSYNC"),
        ]
        for name, provider in cases:
            gates = fields[name].forbidden or []
            wire_shapes = [gate.when.to_dict() for gate in gates]
            assert wire_shapes == [{"not": {"contains": {"upload": provider}}}], (
                f"unexpected forbidden gate on {name}: {wire_shapes}"
            )

    def test_mode_sections_carry_forbidden_gates(self):
        """Mode sections gate themselves off when ``backup_type`` is not theirs.

        Each mode section declares a single ``forbidden`` gate keyed off the
        shared ``backup_type`` ChoiceField. Mode-owned bool fields rely on
        this section-level gate rather than per-field gating — see the
        module docstring for the rationale.
        """
        sections = {section.title: section for section in mysql_backups_schema.forms}
        for title, owner_mode in [
            ("Mydumper", "M"),
            ("XtraBackup", "X"),
            ("Binlog", "B"),
        ]:
            gates = sections[title].forbidden or []
            wire_shapes = [gate.when.to_dict() for gate in gates]
            expected = [FieldGate(when=F("backup_type") != owner_mode).when.to_dict()]
            assert wire_shapes == expected, (
                f"unexpected forbidden gate on {title} section: {wire_shapes}"
            )

    def test_schema_field_names_match_backup_create_attrs(self):
        """Every schema field name must resolve to a ``BackupCreate`` attribute.

        ``apply_conditional_rules`` validates this at decoration time, but
        keep the assertion in tests so a drift between schema and model
        surfaces immediately.
        """
        model_fields = set(BackupCreate.model_fields)
        schema_field_names = {
            field.name
            for section in mysql_backups_schema.forms
            for field in section.fields
        }
        assert schema_field_names - model_fields == set(), (
            f"Schema fields missing on BackupCreate: "
            f"{schema_field_names - model_fields}"
        )
