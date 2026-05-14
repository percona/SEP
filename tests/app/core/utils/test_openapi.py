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

"""Define tests for the app.core.utils.openapi module."""

from enum import Enum
from types import SimpleNamespace

from app.core.utils.openapi import generate_tag_prefixed_unique_id


def _make_route(name, path, tags):
    """Build a minimal stand-in for a FastAPI ``APIRoute`` for ID generation.

    ``generate_unique_id`` only reads ``name``, ``path_format``, ``tags``, and
    ``methods`` — a ``SimpleNamespace`` with those attributes is enough and
    keeps the test free of a full FastAPI app setup.
    """
    return SimpleNamespace(
        name=name,
        path_format=path,
        tags=tags,
        methods={"GET"},
        operation_id=None,
    )


def test_untagged_route_falls_back_to_default_id():
    """Routes without tags get FastAPI's default operation ID."""
    route = _make_route("list_things", "/things", [])
    assert generate_tag_prefixed_unique_id(route) == "list_things_things_get"


def test_string_tag_is_prefixed():
    """A plain string tag is slugified and prefixed to the base ID."""
    route = _make_route("list_things", "/things", ["inventory"])
    assert generate_tag_prefixed_unique_id(route) == "inventory_list_things_things_get"


def test_enum_tag_uses_enum_value():
    """``Enum`` tags use their ``.value``, not ``repr``."""

    class TagEnum(str, Enum):
        SEP = "sep"

    route = _make_route("list_things", "/things", [TagEnum.SEP])
    assert generate_tag_prefixed_unique_id(route) == "sep_list_things_things_get"


def test_non_alphanumeric_tag_collapses_to_underscores():
    """Spaces, slashes, and punctuation in a tag collapse to a single ``_``."""
    route = _make_route("list_things", "/things", ["Periodic Tasks / jobs"])
    assert (
        generate_tag_prefixed_unique_id(route)
        == "periodic_tasks_jobs_list_things_things_get"
    )


def test_pure_punctuation_tag_falls_back_to_default():
    """A tag whose slug is empty after sanitization falls back to the default ID."""
    route = _make_route("list_things", "/things", ["---"])
    assert generate_tag_prefixed_unique_id(route) == "list_things_things_get"
