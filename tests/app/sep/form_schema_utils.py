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

"""Traverse the form sections of a built :class:`AppSchema`.

Shared by the per-script schema suites -- snippets, Dipper and the disk-script
source -- which each assert the same two things about their builder's output:
which field names it emits, and which field type renders each of them.
"""

from app.sep.apps.framework.schema import AnyField, AppSchema


def form_field_names(schema: AppSchema) -> list[str]:
    """Return every form field name across a schema's sections, sorted.

    A list rather than a set, so a duplicate wire name -- the failure the
    reserved-name tests exist to catch -- stays visible instead of collapsing
    into a single entry.

    :param schema: The built schema whose form sections are traversed.
    :return: Every field name, repeats included, in sorted order.
    """
    return sorted(field.name for section in schema.forms for field in section.fields)


def form_fields_by_name(schema: AppSchema) -> dict[str, AnyField]:
    """Return every form field across a schema's sections, keyed by field name.

    :param schema: The built schema whose form sections are traversed.
    :return: Each field keyed by its wire name.
    """
    return {field.name: field for section in schema.forms for field in section.fields}


def form_field_types(schema: AppSchema) -> dict[str, type]:
    """Map every form field name to the field class that renders it.

    Pairs with :func:`form_field_names`: that one pins which names a builder
    emits, this one pins that each name is still rendered by the widget its
    users expect, so a field silently retyped fails as loudly as one dropped.

    :param schema: The built schema whose form sections are traversed.
    :return: Each field's class keyed by its wire name.
    """
    return {name: type(field) for name, field in form_fields_by_name(schema).items()}
