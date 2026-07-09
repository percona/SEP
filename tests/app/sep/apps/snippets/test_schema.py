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

from urllib.parse import urlencode

import pytest

from app.sep.apps.dipper.models import DipperScript
from app.sep.apps.framework.schema import (
    BoolField,
    ChoiceField,
    DateTimeField,
    HostField,
    IntegerField,
    ScriptPreviewField,
    StringField,
)
from app.sep.apps.snippets.schema import (
    build_snippet_schema,
    evaluate_visibility_gates,
    field_for,
    SNIPPETS_PLUGIN_SCHEMA,
)
from app.sep.snippets.models.meta import (
    SnippetMetaParameter,
    SnippetMetaParameterType,
)
from app.sep.snippets.models.snippet import (
    EXECUTOR_HOSTS_INPUT_NAME,
    Snippet,
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


def _script_preview_section(schema):
    return next(
        section for section in schema.forms if section.title == "Script preview"
    )


@pytest.mark.asyncio
async def test_per_snippet_schema_includes_host_and_preview(create_snippet):
    """Per-snippet schema keeps host in Execution; preview is a separate collapsible section using the query API."""
    snippet = await create_snippet("hello.sh", approved=True)

    schema = build_snippet_schema(snippet)

    execution = _execution_section(schema)
    field_types = {type(field) for field in execution.fields}
    assert HostField in field_types
    assert ScriptPreviewField not in field_types
    preview_section = _script_preview_section(schema)
    assert preview_section.collapsible is True
    assert preview_section.collapsed_by_default is True
    assert preview_section.render_after_submit is True
    preview = next(
        f for f in preview_section.fields if isinstance(f, ScriptPreviewField)
    )
    assert preview.label == "Snippet file"
    assert preview.endpoint_url == (
        "/apps/snippets/snippet/preview?"
        + urlencode({"snippet_filename": snippet.filename})
    )


@pytest.mark.asyncio
async def test_per_snippet_schema_url_encodes_nested_filenames(create_snippet):
    """Nested relative keys encode ``/`` as ``%2F`` in ``snippet_filename`` only — the preview path segment stays constant."""
    snippet = await create_snippet("diag/slow-query.sh", approved=True)

    schema = build_snippet_schema(snippet)

    preview_section = _script_preview_section(schema)
    preview = next(
        f for f in preview_section.fields if isinstance(f, ScriptPreviewField)
    )
    assert preview.endpoint_url == (
        "/apps/snippets/snippet/preview?"
        + urlencode({"snippet_filename": snippet.filename})
    )
    path, _, _query = preview.endpoint_url.partition("?")
    assert path == "/apps/snippets/snippet/preview"
    assert "%2F" not in path
    assert "diag" not in path
    assert "slow-query" not in path


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


class TestVisibilityGates:
    """Test that field_for lowers visibility conditions onto forbidden gates.

    The React renderer hides the field and drops its value; the gates are also
    enforced server-side on the execute paths (see ``evaluate_visibility_gates``
    and the execute-path tests), which reject a directly-submitted hidden value.
    """

    def test_no_condition_leaves_forbidden_none(self):
        """A parameter without a visibility condition carries no forbidden gate."""
        field = field_for(SnippetMetaParameter(name="start", type="str"))
        assert field.forbidden is None

    def test_visible_when_not_truthy_lowers_to_truthy_gate(self):
        """visible_when_not (truthiness) forbids the field when the ref is truthy."""
        field = field_for(
            SnippetMetaParameter(name="start", type="str", visible_when_not="list")
        )
        assert len(field.forbidden) == 1
        assert field.forbidden[0].when.to_dict() == {"truthy": "list"}

    def test_visible_when_truthy_lowers_to_negated_gate(self):
        """visible_when (truthiness) forbids the field when the ref is NOT truthy."""
        field = field_for(
            SnippetMetaParameter(name="start", type="str", visible_when="list")
        )
        assert len(field.forbidden) == 1
        assert field.forbidden[0].when.to_dict() == {"not": {"truthy": "list"}}

    def test_visible_when_not_equals_lowers_to_equals_gate(self):
        """visible_when_not with equals forbids the field on an equality match."""
        field = field_for(
            SnippetMetaParameter(
                name="region",
                type="str",
                visible_when_not={"parameter": "mode", "equals": "advanced"},
            )
        )
        assert field.forbidden[0].when.to_dict() == {"equals": {"mode": "advanced"}}

    def test_condition_on_choice_field(self):
        """A choice-typed parameter still receives the forbidden gate."""
        field = field_for(
            SnippetMetaParameter(
                name="region",
                type="str",
                choices=["us", "eu"],
                visible_when_not="list",
            )
        )
        assert field.forbidden[0].when.to_dict() == {"truthy": "list"}


@pytest.mark.asyncio
async def test_build_snippet_schema_with_gated_field_validates(create_snippet):
    """Build a valid AppSchema from a gated, identifier-safe parameter.

    Regression guard: ``build_snippet_schema`` constructs an ``AppSchema``,
    whose validator folds each gated field's own name into the gate's reference
    set and rejects hyphenated names. This exercises that full construction so a
    gate that produces an invalid schema fails here rather than as a 500 at
    request time.
    """
    snippet = await create_snippet("hello.sh", approved=True)
    snippet.meta = {
        **snippet.meta,
        "parameters": [
            {"name": "list", "type": "bool", "label": "List services"},
            {
                "name": "start",
                "type": "str",
                "label": "Start",
                "visible_when_not": "list",
            },
        ],
    }
    snippet.__dict__.pop("validated_parameters", None)

    schema = build_snippet_schema(snippet)

    parameters_section = next(s for s in schema.forms if s.title == "Parameters")
    start_field = next(f for f in parameters_section.fields if f.name == "start")
    assert start_field.forbidden[0].when.to_dict() == {"truthy": "list"}


@pytest.mark.asyncio
async def test_per_snippet_schema_omits_hidden_parameter(create_snippet):
    """A ``hidden`` parameter is excluded from the generic snippet schema.

    ``hidden`` is a generic snippet primitive, so the schema-driven snippets form
    must omit it just as ``_to_form`` and the Dipper schema builder do — while a
    sibling non-hidden parameter still renders.
    """
    snippet = await create_snippet("hello.sh", approved=True)
    snippet.__dict__.pop("validated_parameters", None)
    snippet.meta = {
        **snippet.meta,
        "parameters": [
            {"name": "pmmserver", "type": "str", "label": "PMM server"},
            {"name": "apikey", "type": "str", "label": "API key", "hidden": True},
        ],
    }
    snippet.__dict__.pop("validated_parameters", None)

    schema = build_snippet_schema(snippet)

    field_names = {field.name for section in schema.forms for field in section.fields}
    assert "pmmserver" in field_names
    assert "apikey" not in field_names


def _snippet_with_params(params: list[dict]) -> Snippet:
    """Return an unpersisted snippet carrying ``params`` as its meta parameters."""
    snippet = Snippet(filename="gated.sh", size=20, md5_digest="a" * 32)
    snippet.meta = {**snippet.meta, "parameters": params}
    return snippet


def _exec_args(snippet: Snippet, wire: dict):
    """Validate ``wire`` (keyed by parameter wire/alias names) into exec args."""
    return snippet.get_execution_model().model_validate(
        {EXECUTOR_HOSTS_INPUT_NAME: "host1", **wire}
    )


class TestEvaluateVisibilityGates:
    """Direct coverage of the server-side gate evaluator.

    ``evaluate_visibility_gates`` is the security backstop: it rejects a value
    submitted directly for a parameter the client would have hidden. Generated
    execution models name fields with opaque identifiers and expose each
    parameter only through its wire alias, so evaluation MUST run against the
    ``by_alias`` view — these tests pin that and the present/absent boundaries.
    """

    _LIST_START = [
        {"name": "list", "type": "bool", "label": "List"},
        {"name": "start", "type": "str", "label": "Start", "visible_when_not": "list"},
    ]

    def test_gateless_snippet_returns_empty(self) -> None:
        """A snippet with no visibility gate never reports a failure."""
        snippet = _snippet_with_params(
            [{"name": "name", "type": "str", "label": "Name"}]
        )
        assert (
            evaluate_visibility_gates(snippet, _exec_args(snippet, {"name": "x"})) == []
        )

    def test_evaluation_runs_against_alias_view(self) -> None:
        """The gate resolves the wire name even though the python attr differs.

        Regression guard for the ``model_dump(by_alias=True)`` requirement: the
        plain dump is keyed by generated identifiers, so a non-alias evaluation
        would silently never fire — a gate bypass.
        """
        snippet = _snippet_with_params(self._LIST_START)
        args = _exec_args(snippet, {"list": True, "start": "2020"})

        assert "start" not in args.model_dump()  # python attr is opaque
        assert "start" in args.model_dump(by_alias=True)
        assert evaluate_visibility_gates(snippet, args)  # gate fires

    def test_truthy_gate_not_fired_when_trigger_absent(self) -> None:
        """With the trigger falsy, the gated value is allowed."""
        snippet = _snippet_with_params(self._LIST_START)
        args = _exec_args(snippet, {"start": "2020"})
        assert evaluate_visibility_gates(snippet, args) == []

    def test_visible_when_negated_gate_fires(self) -> None:
        """``visible_when`` forbids the field while the trigger is NOT truthy."""
        snippet = _snippet_with_params(
            [
                {"name": "list", "type": "bool", "label": "List"},
                {
                    "name": "start",
                    "type": "str",
                    "label": "Start",
                    "visible_when": "list",
                },
            ]
        )
        # ``list`` falsy -> field is hidden -> a submitted ``start`` is rejected.
        args = _exec_args(snippet, {"start": "2020"})
        assert evaluate_visibility_gates(snippet, args)

    def test_equals_gate_fires(self) -> None:
        """An equals condition rejects the gated value on an equality match."""
        snippet = _snippet_with_params(
            [
                {"name": "mode", "type": "str", "label": "Mode"},
                {
                    "name": "region",
                    "type": "str",
                    "label": "Region",
                    "visible_when_not": {"parameter": "mode", "equals": "advanced"},
                },
            ]
        )
        args = _exec_args(snippet, {"mode": "advanced", "region": "eu"})
        assert evaluate_visibility_gates(snippet, args)

    def test_multiple_gates_fire_yield_multiple_messages(self) -> None:
        """Every fired gate contributes a message."""
        snippet = _snippet_with_params(
            [
                {"name": "list", "type": "bool", "label": "List"},
                {
                    "name": "start",
                    "type": "str",
                    "label": "Start",
                    "visible_when_not": "list",
                },
                {
                    "name": "end",
                    "type": "str",
                    "label": "End",
                    "visible_when_not": "list",
                },
            ]
        )
        args = _exec_args(snippet, {"list": True, "start": "a", "end": "b"})
        expected_failures = 2
        assert len(evaluate_visibility_gates(snippet, args)) == expected_failures

    def test_gated_bool_false_is_allowed(self) -> None:
        """A gated bool submitted ``False`` is absent, so the gate does not reject.

        ``True`` for the same field IS rejected — locking the ``value_is_present``
        ``False``-is-absent convention end-to-end through the evaluator.
        """
        snippet = _snippet_with_params(
            [
                {"name": "list", "type": "bool", "label": "List"},
                {
                    "name": "flag",
                    "type": "bool",
                    "label": "Flag",
                    "visible_when_not": "list",
                },
            ]
        )
        allowed = _exec_args(snippet, {"list": True, "flag": False})
        rejected = _exec_args(snippet, {"list": True, "flag": True})

        assert evaluate_visibility_gates(snippet, allowed) == []
        assert evaluate_visibility_gates(snippet, rejected)


def test_field_for_maps_datetime_parameter_to_datetime_field():
    """Verify DATETIME parameters map directly to DateTimeField via field_for."""
    param = SnippetMetaParameter(
        name="start",
        type="datetime",
        label="Start time (UTC)",
        description="Starting timestamp for graph data.",
    )
    field = field_for(param)
    assert isinstance(field, DateTimeField)
    assert field.name == "start"
    assert field.label == "Start time (UTC)"
    assert field.description == "Starting timestamp for graph data."


@pytest.mark.asyncio
async def test_per_snippet_schema_maps_datetime_parameter_to_datetime_field(
    create_snippet,
):
    """Verify DATETIME parameters surface as DateTimeField in the per-snippet schema."""
    snippet = await create_snippet("hello.sh", approved=True)
    snippet.__dict__.pop("validated_parameters", None)
    snippet.meta = {
        **snippet.meta,
        "parameters": [
            {
                "name": "start",
                "type": "datetime",
                "label": "Start time (UTC)",
                "description": "Starting timestamp for graph data.",
            },
        ],
    }
    snippet.__dict__.pop("validated_parameters", None)

    schema = build_snippet_schema(snippet)

    parameters_section = next(s for s in schema.forms if s.title == "Parameters")
    field = parameters_section.fields[0]
    assert isinstance(field, DateTimeField)
    assert field.name == "start"
    assert field.label == "Start time (UTC)"


@pytest.mark.asyncio
async def test_pmm_mysql_payload_start_end_map_to_datetime_field():
    """Verify PMM MySQL collector start/end params declare datetime and map to DateTimeField."""
    script = await DipperScript.from_path("pcs-collect-pmm-mysql.py", update_meta=True)

    assert script.validated_parameters.errors == []

    for name in ("start", "end"):
        param = next(
            p for p in script.validated_parameters.parameters if p.name == name
        )
        assert param.py_type is SnippetMetaParameterType.DATETIME
        assert isinstance(field_for(param), DateTimeField)
