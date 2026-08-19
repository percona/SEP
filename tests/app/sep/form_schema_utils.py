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

"""Traverse and assert against the form sections of a built :class:`AppSchema`.

Shared by the per-script schema suites (snippets, Dipper and the disk-script
source), which each assert the same two things about their builder's output:
which field names it emits, and which field type renders each of them.
"""

from app.sep.apps.framework.schema import AnyField, AppSchema, SchemaBaseModel


def form_field_names(schema: AppSchema) -> list[str]:
    """Return every form field name across a schema's sections, sorted.

    A list rather than a set, so a duplicate wire name stays visible instead of
    collapsing into a single entry. A task-style schema cannot carry one this far
    (see :func:`form_fields_by_name`), but the uniqueness validator returns early
    for an entity-style schema, and this is the one helper positioned to show a
    repeat if one ever reaches it.

    :param schema: The built schema whose form sections are traversed.
    :return: Every field name, repeats included, in sorted order.
    """
    return sorted(field.name for section in schema.forms for field in section.fields)


def form_fields_by_name(schema: AppSchema) -> dict[str, AnyField]:
    """Return every form field across a schema's sections, keyed by field name.

    Keying by name cannot mask a duplicate emitted by a task-style builder:
    ``AppSchema`` runs ``_validate_unique_field_names_in_forms`` in a
    ``mode="after"`` validator, so a builder emitting one wire name twice raises
    before any schema object exists for this function to receive. The repeat
    surfaces out of the builder call itself. That validator returns early when
    ``entities`` is set, so the guarantee covers the task-style schemas every
    caller builds today and not the entity-style branch.

    :param schema: The built schema whose form sections are traversed.
    :return: Each field keyed by its wire name.
    """
    return {field.name: field for section in schema.forms for field in section.fields}


def form_field_types(schema: AppSchema) -> dict[str, type[SchemaBaseModel]]:
    """Map every form field name to the field class that renders it.

    Pairs with :func:`form_field_names`: that one pins which names a builder
    emits, this one pins that each name is still rendered by the widget its
    users expect, so a field silently retyped fails as loudly as one dropped.

    :param schema: The built schema whose form sections are traversed.
    :return: Each field's class keyed by its wire name.
    """
    return {name: type(field) for name, field in form_fields_by_name(schema).items()}


def assert_only_synthesized_fields(
    schema: AppSchema, expected: dict[str, type[SchemaBaseModel]]
) -> None:
    """Assert a schema carries the synthesized execution fields and nothing else.

    Shared by the reserved-name suites, where the author's colliding parameter has
    to be dropped. Asserting the whole field set, rather than only that the
    reserved name appears at most once, keeps a build that dropped the
    *synthesized* field as well from passing; asserting each field's type keeps one
    silently retyped (the author's ``str`` parameter shadowing the synthesized
    widget) from passing either.

    :param schema: The built schema whose form sections are traversed.
    :param expected: Each synthesized field's class keyed by its wire name.
    """
    assert not any(  # noqa: S101
        section.title == "Parameters" for section in schema.forms
    )
    assert form_field_names(schema) == sorted(expected)  # noqa: S101
    assert form_field_types(schema) == expected  # noqa: S101
