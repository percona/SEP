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

"""Unit tests for the plugin schema DSL."""

import pytest
from pydantic import ValidationError

from app.inventory.models import ServiceTypeEnum
from app.sep.plugins.framework.schema import (
    BoolField,
    Capabilities,
    Choice,
    ChoiceField,
    Column,
    ColumnFormat,
    DateTimeField,
    FileField,
    FloatField,
    FormSection,
    HostField,
    IntegerField,
    ListView,
    MultiChoiceField,
    PluginEntitySchema,
    PluginSchema,
    SchemaField,
    ServiceField,
    StringField,
    TableField,
    TextAreaField,
    YamlField,
)


def _minimal_list_view() -> ListView:
    return ListView(columns=[Column(key="id", label="ID")])


_CHECKSUMS_LIKE_SCHEMA = PluginSchema(
    name="checksums",
    display_name="Checksums",
    description="Run pt-table-checksum to verify data consistency.",
    task_type="pt-table-checksum",
    forms=[
        FormSection(
            title="Target",
            description="Select the MySQL service to run checksums against.",
            fields=[
                ServiceField(
                    name="serviceId",
                    label="MySQL Service",
                    required=True,
                    service_types=[ServiceTypeEnum.MYSQL],
                ),
                StringField(
                    name="schema",
                    label="Schema",
                    placeholder="Leave empty for all schemas",
                    description="Optionally filter to a specific database schema.",
                ),
            ],
        ),
        FormSection(
            title="Options",
            fields=[
                ChoiceField(
                    name="chunkSize",
                    label="Chunk Size",
                    default="1000",
                    choices=[
                        Choice(label="1,000", value="1000"),
                        Choice(label="5,000", value="5000"),
                    ],
                ),
                BoolField(
                    name="replicateCheck",
                    label="Replicate check",
                    default=True,
                ),
                IntegerField(
                    name="checkInterval",
                    label="Check interval (seconds)",
                    default=1,
                    ge=1,
                    le=3600,
                ),
            ],
        ),
    ],
    capabilities=Capabilities(alert_on_fail=True, scheduling=True),
    list_view=ListView(
        columns=[
            Column(key="id", label="ID", sortable=True),
            Column(key="service", label="Service", format=ColumnFormat.CHIP),
            Column(key="schema", label="Schema", format=ColumnFormat.CODE),
            Column(
                key="status",
                label="Status",
                format=ColumnFormat.STATUS,
                sortable=True,
            ),
            Column(key="differences", label="Differences"),
            Column(
                key="lastRun",
                label="Last Run",
                format=ColumnFormat.RELATIVE,
                sortable=True,
            ),
        ],
        default_sort="-lastRun",
    ),
)


# ── Construction ─────────────────────────────────────────────────────────


def test_plugin_schema_constructs_with_minimal_fields():
    """Construct a minimal ``PluginSchema`` with no forms and one column."""
    schema = PluginSchema(
        name="minimal",
        display_name="Minimal",
        forms=[],
        list_view=_minimal_list_view(),
    )

    assert schema.name == "minimal"
    assert schema.capabilities is None
    assert schema.forms == []


def test_plugin_schema_entities_mode_omits_root_list_view():
    """Construct a ``PluginSchema`` with ``entities`` set and no root ``list_view``."""
    entity = PluginEntitySchema(
        name="things",
        display_name="Things",
        forms=[
            FormSection(
                title="T",
                fields=[StringField(name="title", label="Title", required=True)],
            )
        ],
        list_view=_minimal_list_view(),
    )
    schema = PluginSchema(
        name="multi",
        display_name="Multi",
        entities=[entity],
    )
    assert schema.entities is not None
    assert len(schema.entities) == 1
    assert schema.list_view is None


def test_plugin_entity_schema_rejects_duplicate_field_names():
    """Reject a ``PluginEntitySchema`` with duplicate field ``name`` values across sections."""
    with pytest.raises(ValueError, match="duplicate field name"):
        PluginEntitySchema(
            name="dup",
            display_name="Dup",
            forms=[
                FormSection(
                    title="A",
                    fields=[StringField(name="x", label="X")],
                ),
                FormSection(
                    title="B",
                    fields=[StringField(name="x", label="X2")],
                ),
            ],
            list_view=_minimal_list_view(),
        )


def test_plugin_schema_constructs_with_all_capabilities_on():
    """Construct a ``PluginSchema`` with every capability flag enabled."""
    schema = PluginSchema(
        name="caps",
        display_name="Caps",
        forms=[],
        capabilities=Capabilities(chaining=True, alert_on_fail=True, scheduling=True),
        list_view=_minimal_list_view(),
    )

    assert schema.capabilities is not None
    assert schema.capabilities.chaining is True
    assert schema.capabilities.alert_on_fail is True
    assert schema.capabilities.scheduling is True


@pytest.mark.parametrize(
    ("field_cls", "field_type", "extra_kwargs"),
    [
        (BoolField, "bool", {}),
        (
            ChoiceField,
            "choice",
            {"choices": [Choice(label="A", value="a")]},
        ),
        (DateTimeField, "datetime", {}),
        (FileField, "file", {}),
        (FloatField, "float", {}),
        (HostField, "host", {}),
        (IntegerField, "integer", {}),
        (
            MultiChoiceField,
            "multi_choice",
            {"choices": [Choice(label="A", value="a")]},
        ),
        (SchemaField, "schema", {"depends_on": "serviceId"}),
        (
            ServiceField,
            "service",
            {"service_types": [ServiceTypeEnum.MYSQL]},
        ),
        (StringField, "string", {}),
        (TableField, "table", {"depends_on": "schemaId"}),
        (TextAreaField, "textarea", {}),
        (YamlField, "yaml", {}),
    ],
)
def test_each_field_class_constructs_with_defaults(field_cls, field_type, extra_kwargs):
    """Construct every concrete field class with its required defaults."""
    field = field_cls(name="foo", label="Foo", **extra_kwargs)

    assert field.field_type == field_type
    assert field.name == "foo"
    assert field.label == "Foo"
    assert field.required is False
    assert field.description is None
    assert field.default is None


def test_choice_field_rejects_empty_choices():
    """Reject a ``ChoiceField`` declared with an empty ``choices`` list."""
    with pytest.raises(ValidationError, match="at least 1 item"):
        ChoiceField(name="c", label="C", choices=[])


def test_multi_choice_field_rejects_empty_choices():
    """Reject a ``MultiChoiceField`` declared with an empty ``choices`` list."""
    with pytest.raises(ValidationError, match="at least 1 item"):
        MultiChoiceField(name="c", label="C", choices=[])


def test_service_field_service_types_accepts_enum_values():
    """Accept ``ServiceTypeEnum`` members in ``ServiceField.service_types``."""
    field = ServiceField(
        name="svc", label="Service", service_types=[ServiceTypeEnum.MYSQL]
    )

    assert field.service_types == [ServiceTypeEnum.MYSQL]


def test_service_field_service_types_accepts_lowercase_strings():
    """Accept lowercase string values in ``ServiceField.service_types``."""
    field = ServiceField(name="svc", label="Service", service_types=["mysql"])

    assert field.service_types == [ServiceTypeEnum.MYSQL]


@pytest.mark.parametrize(
    "invalid_name",
    [
        "-foo",
        "foo bar",
        "foo!",
        "foo-",
        "",
        "1foo",
        "9",
    ],
)
def test_base_field_name_pattern_rejects_invalid_identifiers(invalid_name):
    """Reject field ``name`` values that violate the identifier pattern."""
    with pytest.raises(ValidationError):
        StringField(name=invalid_name, label="L")


@pytest.mark.parametrize(
    "valid_name",
    [
        "foo",
        "foo_bar",
        "foo-bar",
        "foo_bar_01",
        "a",
    ],
)
def test_base_field_name_pattern_accepts_valid_identifiers(valid_name):
    """Accept field ``name`` values that match the identifier pattern."""
    field = StringField(name=valid_name, label="L")

    assert field.name == valid_name


@pytest.mark.parametrize("invalid_name", ["-foo", "foo bar", "", "1foo", "9"])
def test_plugin_schema_name_pattern_rejects_invalid_identifiers(invalid_name):
    """Reject ``PluginSchema.name`` values that violate the identifier pattern."""
    with pytest.raises(ValidationError):
        PluginSchema(
            name=invalid_name,
            display_name="X",
            forms=[],
            list_view=_minimal_list_view(),
        )


def test_string_field_min_length_rejects_zero():
    """Reject ``StringField.min_length`` values below one."""
    with pytest.raises(ValidationError):
        StringField(name="x", label="L", min_length=0)


def test_schema_base_model_rejects_unknown_keys():
    """Reject unknown keys in schema inputs to surface typos at validation time."""
    with pytest.raises(ValidationError):
        StringField(name="x", label="L", minLenght=5)


# ── JSON serialisation round-trip ────────────────────────────────────────


def test_plugin_schema_serialises_to_camel_case_json():
    """Serialise ``PluginSchema`` to camelCase JSON matching the React contract."""
    dumped = _CHECKSUMS_LIKE_SCHEMA.model_dump(mode="json", by_alias=True)

    assert "displayName" in dumped
    assert "taskType" in dumped
    assert "listView" in dumped
    assert "defaultSort" in dumped["listView"]
    assert "alertOnFail" in dumped["capabilities"]

    service_field = dumped["forms"][0]["fields"][0]
    assert service_field["type"] == "service"
    assert "serviceTypes" in service_field
    assert "fieldType" not in service_field
    assert "field_type" not in service_field

    string_field = dumped["forms"][0]["fields"][1]
    assert string_field["type"] == "string"
    assert "minLength" in string_field
    assert "maxLength" in string_field


@pytest.mark.parametrize(
    ("field_cls", "discriminator", "extra_kwargs"),
    [
        (BoolField, "bool", {}),
        (
            ChoiceField,
            "choice",
            {"choices": [Choice(label="A", value="a")]},
        ),
        (DateTimeField, "datetime", {}),
        (FileField, "file", {}),
        (FloatField, "float", {}),
        (HostField, "host", {}),
        (IntegerField, "integer", {}),
        (
            MultiChoiceField,
            "multi_choice",
            {"choices": [Choice(label="A", value="a")]},
        ),
        (SchemaField, "schema", {"depends_on": "svc"}),
        (
            ServiceField,
            "service",
            {"service_types": [ServiceTypeEnum.MYSQL]},
        ),
        (StringField, "string", {}),
        (TableField, "table", {"depends_on": "schema"}),
        (TextAreaField, "textarea", {}),
        (YamlField, "yaml", {}),
    ],
)
def test_each_field_type_discriminator_serialises_as_type_key(
    field_cls, discriminator, extra_kwargs
):
    """Serialise every concrete field class with ``type`` as the discriminator key."""
    field = field_cls(name="foo", label="Foo", **extra_kwargs)

    dumped = field.model_dump(mode="json", by_alias=True)

    assert dumped["type"] == discriminator
    assert "fieldType" not in dumped
    assert "field_type" not in dumped


def test_plugin_schema_round_trips_through_json():
    """Round-trip ``PluginSchema`` through JSON back into concrete field subclasses."""
    dumped = _CHECKSUMS_LIKE_SCHEMA.model_dump(mode="json", by_alias=True)

    rehydrated = PluginSchema.model_validate(dumped)

    assert isinstance(rehydrated.forms[0].fields[0], ServiceField)
    assert isinstance(rehydrated.forms[0].fields[1], StringField)
    assert isinstance(rehydrated.forms[1].fields[0], ChoiceField)
    assert isinstance(rehydrated.forms[1].fields[1], BoolField)
    assert isinstance(rehydrated.forms[1].fields[2], IntegerField)
    assert rehydrated.list_view.default_sort == "-lastRun"


def test_plugin_schema_accepts_snake_case_python_construction():
    """Accept snake_case Python kwargs when constructing a ``PluginSchema``."""
    expected_min_length = 3
    schema = PluginSchema(
        name="p",
        display_name="P",
        task_type="python",
        forms=[
            FormSection(
                title="T",
                fields=[
                    StringField(name="x", label="X", min_length=expected_min_length),
                ],
            ),
        ],
        list_view=_minimal_list_view(),
    )

    assert schema.display_name == "P"
    assert schema.task_type == "python"
    assert schema.forms[0].fields[0].min_length == expected_min_length


def test_plugin_schema_accepts_camel_case_json_input():
    """Accept camelCase JSON input when validating a ``PluginSchema``."""
    expected_min_length = 3
    schema = PluginSchema.model_validate(
        {
            "name": "p",
            "displayName": "P",
            "taskType": "python",
            "forms": [
                {
                    "title": "T",
                    "fields": [
                        {
                            "name": "x",
                            "label": "X",
                            "type": "string",
                            "minLength": expected_min_length,
                        },
                    ],
                },
            ],
            "listView": {"columns": [{"key": "id", "label": "ID"}]},
        },
    )

    assert schema.display_name == "P"
    assert schema.task_type == "python"
    assert isinstance(schema.forms[0].fields[0], StringField)
    assert schema.forms[0].fields[0].min_length == expected_min_length


def test_column_format_serialises_to_lowercase_string():
    """Serialise ``ColumnFormat`` members to lowercase strings in JSON output."""
    column = Column(key="status", label="Status", format=ColumnFormat.STATUS)

    dumped = column.model_dump(mode="json", by_alias=True)

    assert dumped["format"] == "status"


def test_column_format_actions_serialises_to_lowercase_string():
    """Serialise ``ColumnFormat.ACTIONS`` to ``actions`` in JSON output."""
    column = Column(key="_actions", label="Actions", format=ColumnFormat.ACTIONS)
    dumped = column.model_dump(mode="json", by_alias=True)
    assert dumped["format"] == "actions"


def test_column_format_rejects_unknown_values():
    """Reject ``Column.format`` values that are not ``ColumnFormat`` members."""
    with pytest.raises(ValidationError):
        Column(key="x", label="X", format="nonsense")


def test_service_field_service_types_round_trip():
    """Round-trip ``ServiceField.service_types`` through JSON back to enum members."""
    field = ServiceField(name="svc", label="S", service_types=[ServiceTypeEnum.MYSQL])

    dumped = field.model_dump(mode="json", by_alias=True)
    assert dumped["serviceTypes"] == ["mysql"]

    rehydrated = ServiceField.model_validate(dumped)
    assert rehydrated.service_types == [ServiceTypeEnum.MYSQL]


# ── Cross-field validators ───────────────────────────────────────────────


def test_plugin_schema_rejects_duplicate_field_names_across_sections():
    """Reject a ``PluginSchema`` with duplicate field ``name`` values across sections."""
    with pytest.raises(ValidationError, match="duplicate field name"):
        PluginSchema(
            name="p",
            display_name="P",
            forms=[
                FormSection(
                    title="A",
                    fields=[StringField(name="foo", label="F1")],
                ),
                FormSection(
                    title="B",
                    fields=[StringField(name="foo", label="F2")],
                ),
            ],
            list_view=_minimal_list_view(),
        )


def test_plugin_schema_accepts_unique_names_across_sections():
    """Accept a ``PluginSchema`` whose field ``name`` values are unique across sections."""
    schema = PluginSchema(
        name="p",
        display_name="P",
        forms=[
            FormSection(
                title="A",
                fields=[StringField(name="foo", label="F1")],
            ),
            FormSection(
                title="B",
                fields=[StringField(name="bar", label="F2")],
            ),
        ],
        list_view=_minimal_list_view(),
    )

    assert schema.forms[0].fields[0].name == "foo"
    assert schema.forms[1].fields[0].name == "bar"


def test_list_view_rejects_default_sort_referencing_missing_column():
    """Reject a ``ListView`` whose ``default_sort`` does not match any column key."""
    with pytest.raises(ValidationError, match="references unknown column key"):
        ListView(
            columns=[Column(key="id", label="ID")],
            default_sort="foo",
        )


def test_list_view_accepts_default_sort_with_leading_minus():
    """Accept ``ListView.default_sort`` with a leading ``-`` descending prefix."""
    view = ListView(
        columns=[Column(key="id", label="ID")],
        default_sort="-id",
    )

    assert view.default_sort == "-id"


def test_list_view_accepts_default_sort_without_prefix():
    """Accept ``ListView.default_sort`` without any prefix."""
    view = ListView(
        columns=[Column(key="id", label="ID")],
        default_sort="id",
    )

    assert view.default_sort == "id"


def test_list_view_accepts_missing_default_sort():
    """Accept a ``ListView`` without a ``default_sort`` value."""
    view = ListView(columns=[Column(key="id", label="ID")])

    assert view.default_sort is None


def test_list_view_rejects_descending_prefix_for_unknown_column():
    """Reject a ``-``-prefixed ``default_sort`` that references a missing column."""
    with pytest.raises(ValidationError, match="references unknown column key"):
        ListView(
            columns=[Column(key="id", label="ID")],
            default_sort="-missing",
        )


def test_list_view_rejects_double_dash_prefix():
    """Reject ``default_sort`` with multiple leading dashes to match the React consumer.

    The React renderer strips exactly one leading ``-`` from ``defaultSort``
    (``replace(/^-/, '')``), so a backend that strips more than one would
    silently disable the default sort at render time.
    """
    with pytest.raises(ValidationError, match="references unknown column key"):
        ListView(
            columns=[Column(key="id", label="ID")],
            default_sort="--id",
        )


# ── Discriminated-union rejection ────────────────────────────────────────


def test_unknown_field_type_raises_validation_error():
    """Reject a ``FormSection`` field with an unknown ``type`` discriminator."""
    with pytest.raises(ValidationError):
        FormSection.model_validate(
            {
                "title": "T",
                "fields": [{"name": "x", "label": "X", "type": "nonsense"}],
            },
        )


def test_missing_discriminator_raises_validation_error():
    """Reject a ``FormSection`` field missing the ``type`` discriminator key."""
    with pytest.raises(ValidationError):
        FormSection.model_validate(
            {
                "title": "T",
                "fields": [{"name": "x", "label": "X"}],
            },
        )


def test_field_type_mismatch_with_concrete_class_raises():
    """Reject constructing a subclass with a ``field_type`` that does not match its literal."""
    with pytest.raises(ValidationError):
        StringField(name="x", label="X", field_type="integer")
