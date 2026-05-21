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

"""Define the static plugin schema and per-snippet schema synthesiser.

Snippets are entity-centric rather than task-centric: the plugin-level
schema describes the snippet list view but declares no forms (snippets are
discovered by ``update_snippets()`` rather than created via this API). The
per-snippet schema is synthesised at request time from the snippet's YAML
frontmatter and served at
``GET /api/plugins/snippets/snippet/schema?snippet_filename=...``.
"""

__all__ = ["SNIPPETS_PLUGIN_SCHEMA", "build_snippet_schema"]

from typing import cast
from urllib.parse import urlencode

from app.sep.plugins.framework.schema import (
    AnyField,
    BoolField,
    Choice,
    ChoiceField,
    Column,
    ColumnFormat,
    FloatField,
    FormSection,
    HostField,
    IntegerField,
    ListView,
    PluginSchema,
    ScriptPreviewField,
    StringField,
)
from app.sep.snippets.config import SnippetSudoOption
from app.sep.snippets.models.meta import (
    SnippetMetaParameter,
    SnippetMetaParameterType,
)
from app.sep.snippets.models.snippet import Snippet

_EXECUTOR_HOST_FIELD_NAME = "executor_host"
_SUDO_FIELD_NAME = "sudo"
_SCRIPT_PREVIEW_FIELD_NAME = "script_preview"


SNIPPETS_PLUGIN_SCHEMA = PluginSchema(
    name="snippets",
    display_name="Snippet Manager",
    description=(
        "Discover and execute pre-approved support snippets against "
        "registered executor hosts."
    ),
    forms=[],
    list_view=ListView(
        columns=[
            Column(key="filename", label="Filename", sortable=True),
            Column(key="title", label="Title", sortable=True),
            Column(key="description", label="Description"),
            Column(key="isApproved", label="Approved", format=ColumnFormat.STATUS),
            Column(key="reason", label="Reason"),
            Column(key="createdAt", label="Added", format=ColumnFormat.RELATIVE),
        ],
        default_sort="filename",
    ),
)


def _choice_field_for(parameter: SnippetMetaParameter) -> ChoiceField:
    """Build a :class:`ChoiceField` from a parameter's normalised choices."""
    choices = []
    for entry in parameter.choices or []:
        value = entry["value"]
        label = entry.get("label") or value
        choices.append(Choice(value=value, label=label))
    default = None if parameter.default is None else str(parameter.default)
    return ChoiceField(
        name=parameter.name,
        label=parameter.label or parameter.name,
        required=parameter.required,
        description=parameter.description,
        default=default,
        choices=choices,
    )


def _string_field_for(parameter: SnippetMetaParameter) -> StringField:
    """Build a :class:`StringField` from a STR-typed parameter."""
    return StringField(
        name=parameter.name,
        label=parameter.label or parameter.name,
        required=parameter.required,
        description=parameter.description,
        default=parameter.default,
        min_length=parameter.min_length if parameter.min_length > 1 else None,
        max_length=parameter.max_length,
        pattern=parameter.pattern,
        placeholder=parameter.placeholder,
    )


def _int_field_for(parameter: SnippetMetaParameter) -> IntegerField:
    """Build an :class:`IntegerField` from an INT-typed parameter."""
    ge = parameter.ge
    if ge is None and parameter.gt is not None:
        ge = int(parameter.gt) + 1
    le = parameter.le
    if le is None and parameter.lt is not None:
        le = int(parameter.lt) - 1
    return IntegerField(
        name=parameter.name,
        label=parameter.label or parameter.name,
        required=parameter.required,
        description=parameter.description,
        default=parameter.default,
        ge=int(ge) if ge is not None else None,
        le=int(le) if le is not None else None,
        step=int(parameter.step) if parameter.step is not None else None,
    )


def _float_field_for(parameter: SnippetMetaParameter) -> FloatField:
    """Build a :class:`FloatField` from a FLOAT-typed parameter."""
    ge = parameter.ge if parameter.ge is not None else parameter.gt
    le = parameter.le if parameter.le is not None else parameter.lt
    return FloatField(
        name=parameter.name,
        label=parameter.label or parameter.name,
        required=parameter.required,
        description=parameter.description,
        default=parameter.default,
        ge=float(ge) if ge is not None else None,
        le=float(le) if le is not None else None,
        step=parameter.step,
    )


def _bool_field_for(parameter: SnippetMetaParameter) -> BoolField:
    """Build a :class:`BoolField` from a BOOL-typed parameter."""
    return BoolField(
        name=parameter.name,
        label=parameter.label or parameter.name,
        required=parameter.required,
        description=parameter.description,
        default=parameter.default,
    )


_FIELD_BUILDERS = {
    SnippetMetaParameterType.STR: _string_field_for,
    SnippetMetaParameterType.INT: _int_field_for,
    SnippetMetaParameterType.FLOAT: _float_field_for,
    SnippetMetaParameterType.BOOL: _bool_field_for,
}


def field_for(parameter: SnippetMetaParameter) -> AnyField:
    """Map a snippet meta parameter to its framework field counterpart.

    A parameter declaring ``choices`` always maps to :class:`ChoiceField`
    regardless of ``py_type``.

    :param parameter: The validated snippet meta parameter.
    :type parameter: SnippetMetaParameter
    :return: The corresponding framework field instance.
    :rtype: AnyField
    """
    if parameter.choices:
        return cast(AnyField, _choice_field_for(parameter))
    return cast(AnyField, _FIELD_BUILDERS[parameter.py_type](parameter))


def build_snippet_schema(snippet: Snippet) -> PluginSchema:
    """Synthesise the per-snippet form schema for a single snippet.

    The schema includes one form section per parameter group declared in
    the snippet metadata (or a single ``"Parameters"`` section if no
    groups are declared), plus a trailing ``"Execution"`` section for
    dispatch controls and a separate collapsible ``"Script preview"``
    section rendered after submit.

    :param snippet: The snippet whose schema to synthesise.
    :type snippet: Snippet
    :return: The fully-validated plugin schema for this single snippet.
    :rtype: PluginSchema
    """
    parameter_sections: dict[str, list[AnyField]] = {}
    for parameter in snippet.validated_parameters.parameters:
        section_title = parameter.group or "Parameters"
        parameter_sections.setdefault(section_title, []).append(field_for(parameter))

    forms = [
        FormSection(title=title, fields=fields)
        for title, fields in parameter_sections.items()
    ]

    execution_fields: list[AnyField] = [
        cast(
            AnyField,
            HostField(
                name=_EXECUTOR_HOST_FIELD_NAME,
                label="Executor Host",
                required=True,
            ),
        ),
    ]
    if snippet.sudo.is_optional:
        execution_fields.append(
            cast(
                AnyField,
                BoolField(
                    name=_SUDO_FIELD_NAME,
                    label="Run with sudo",
                    default=snippet.sudo.sudo_default,
                    description="Prepend sudo to the interpreter when the snippet is executed.",
                ),
            ),
        )
    elif snippet.sudo == SnippetSudoOption.ALWAYS:
        execution_fields.append(
            cast(
                AnyField,
                BoolField(
                    name=_SUDO_FIELD_NAME,
                    label="Run with sudo",
                    default=True,
                    description=("This snippet is configured to always run with sudo."),
                ),
            ),
        )
    forms.append(FormSection(title="Execution", fields=execution_fields))
    forms.append(
        FormSection(
            title="Script preview",
            fields=[
                cast(
                    AnyField,
                    ScriptPreviewField(
                        name=_SCRIPT_PREVIEW_FIELD_NAME,
                        label="Snippet file",
                        endpoint_url=(
                            "/plugins/snippets/snippet/preview?"
                            + urlencode({"snippet_filename": snippet.filename})
                        ),
                    ),
                )
            ],
            collapsible=True,
            collapsed_by_default=True,
            render_after_submit=True,
        )
    )

    return PluginSchema(
        name="snippets",
        display_name=snippet.title,
        description=snippet.description or None,
        forms=forms,
        list_view=SNIPPETS_PLUGIN_SCHEMA.list_view,
    )
