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

"""Tests for the snippets plugin schema synthesiser."""

import pytest

from app.sep.plugins.framework.schema import (
    BoolField,
    ChoiceField,
    HostField,
    IntegerField,
    ScriptPreviewField,
    StringField,
)
from app.sep.plugins.snippets.schema import (
    build_snippet_schema,
    SNIPPETS_PLUGIN_SCHEMA,
)


def test_static_schema_has_no_forms_and_keyed_columns():
    """The static plugin schema declares no forms and lists snippet columns."""
    assert SNIPPETS_PLUGIN_SCHEMA.name == "snippets"
    assert SNIPPETS_PLUGIN_SCHEMA.forms == []
    column_keys = [column.key for column in SNIPPETS_PLUGIN_SCHEMA.list_view.columns]
    assert "filename" in column_keys
    assert "isApproved" in column_keys


def _execution_section(schema):
    return next(section for section in schema.forms if section.title == "Execution")


@pytest.mark.asyncio
async def test_per_snippet_schema_includes_host_and_preview(create_snippet):
    """Every per-snippet schema includes a host selector and the preview pane."""
    snippet = await create_snippet("hello.sh", approved=True)

    schema = build_snippet_schema(snippet)

    section = _execution_section(schema)
    field_types = {type(field) for field in section.fields}
    assert HostField in field_types
    assert ScriptPreviewField in field_types
    preview = next(f for f in section.fields if isinstance(f, ScriptPreviewField))
    assert preview.endpoint_url == (
        f"/api/plugins/snippets/{snippet.filename}/script-preview"
    )


@pytest.mark.asyncio
async def test_per_snippet_schema_omits_sudo_field_when_sudo_never(create_snippet):
    """A NEVER-sudo snippet's execution section excludes the sudo toggle."""
    snippet = await create_snippet("hello.sh", approved=True)
    snippet.__dict__.pop("sudo", None)
    snippet.meta = {**snippet.meta, "sudo": "never"}
    snippet.__dict__.pop("sudo", None)

    schema = build_snippet_schema(snippet)

    section = _execution_section(schema)
    sudo_fields = [f for f in section.fields if f.name == "sudo"]
    assert sudo_fields == []


@pytest.mark.asyncio
async def test_per_snippet_schema_includes_optional_sudo_toggle(create_snippet):
    """A snippet with optional sudo includes a default-False sudo BoolField."""
    snippet = await create_snippet("hello.sh", approved=True)
    snippet.__dict__.pop("sudo", None)
    snippet.meta = {**snippet.meta, "sudo": "optional"}
    snippet.__dict__.pop("sudo", None)

    schema = build_snippet_schema(snippet)

    section = _execution_section(schema)
    sudo_field = next(f for f in section.fields if f.name == "sudo")
    assert isinstance(sudo_field, BoolField)
    assert sudo_field.default is False


@pytest.mark.asyncio
async def test_per_snippet_schema_maps_str_parameter_to_string_field(create_snippet):
    """STR parameters surface as StringField with their declared constraints."""
    snippet = await create_snippet("hello.sh", approved=True)
    snippet.__dict__.pop("validated_parameters", None)
    snippet.meta = {
        **snippet.meta,
        "parameters": [
            {
                "name": "username",
                "type": "str",
                "label": "Username",
                "min_length": 3,
                "max_length": 32,
                "pattern": "^[a-z]+$",
            },
        ],
    }
    snippet.__dict__.pop("validated_parameters", None)

    schema = build_snippet_schema(snippet)

    parameters_section = next(s for s in schema.forms if s.title == "Parameters")
    field = parameters_section.fields[0]
    assert isinstance(field, StringField)
    assert field.name == "username"
    assert field.label == "Username"
    expected_min_length = 3
    expected_max_length = 32
    assert field.min_length == expected_min_length
    assert field.max_length == expected_max_length
    assert field.pattern == "^[a-z]+$"


@pytest.mark.asyncio
async def test_per_snippet_schema_maps_int_parameter_with_gt_to_ge_plus_one(
    create_snippet,
):
    """INT parameters with gt/lt translate to ge/le inclusive bounds."""
    snippet = await create_snippet("hello.sh", approved=True)
    snippet.__dict__.pop("validated_parameters", None)
    snippet.meta = {
        **snippet.meta,
        "parameters": [
            {
                "name": "count",
                "type": "int",
                "label": "Count",
                "gt": 0,
                "lt": 101,
                "step": 5,
            },
        ],
    }
    snippet.__dict__.pop("validated_parameters", None)

    schema = build_snippet_schema(snippet)

    parameters_section = next(s for s in schema.forms if s.title == "Parameters")
    field = parameters_section.fields[0]
    assert isinstance(field, IntegerField)
    expected_le = 100
    expected_step = 5
    assert field.ge == 1
    assert field.le == expected_le
    assert field.step == expected_step


@pytest.mark.asyncio
async def test_per_snippet_schema_maps_choices_to_choice_field(create_snippet):
    """A parameter with declared choices becomes a ChoiceField regardless of py_type."""
    snippet = await create_snippet("hello.sh", approved=True)
    snippet.__dict__.pop("validated_parameters", None)
    snippet.meta = {
        **snippet.meta,
        "parameters": [
            {
                "name": "level",
                "type": "str",
                "label": "Level",
                "choices": [
                    {"value": "info", "label": "Info"},
                    {"value": "debug"},
                ],
            },
        ],
    }
    snippet.__dict__.pop("validated_parameters", None)

    schema = build_snippet_schema(snippet)

    parameters_section = next(s for s in schema.forms if s.title == "Parameters")
    field = parameters_section.fields[0]
    assert isinstance(field, ChoiceField)
    values = [choice.value for choice in field.choices]
    assert values == ["info", "debug"]
    labels = [choice.label for choice in field.choices]
    assert labels == ["Info", "debug"]
