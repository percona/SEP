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

"""Declare per-entity list-query specs for the inventory plugin proxy.

The inventory plugin is a hand-written ``BaseApp`` proxy: it has no
``TaskExecutionApp`` list-query field to route through, so the declaration
lives here as plain ``ListQuerySpec`` values the request-boundary dependency
consumes directly. Specs use named ``sqlalchemy.column(...)`` clauses rather
than ORM columns so this module never imports ``app.inventory`` models — the
proxy only needs the public sort keys, searchable attribute names, and
defaults, which must match the upstream inventory managers' allowlists and
the inventory plugin ``ListView.default_sort`` values.
"""

from __future__ import annotations

from types import MappingProxyType

from sqlalchemy import column

from app.core.db.list_query import ListQuerySpec

_NODES_SPEC = ListQuerySpec(
    sortable={
        "name": column("name"),
        "created_at": column("created_at"),
    },
    default_sort="-created_at",
    tie_breaker=column("id"),
    searchable=(column("name"),),
)

_SERVICES_SPEC = ListQuerySpec(
    sortable={
        "name": column("name"),
        "created_at": column("created_at"),
    },
    default_sort="-name",
    tie_breaker=column("id"),
    searchable=(column("name"),),
)

_SCHEMAS_SPEC = ListQuerySpec(
    sortable={
        "name": column("name"),
        "created_at": column("created_at"),
        "service_id": column("service_id"),
    },
    default_sort="-created_at",
    tie_breaker=column("id"),
    searchable=(column("name"),),
)

_TABLES_SPEC = ListQuerySpec(
    sortable={
        "name": column("name"),
        "created_at": column("created_at"),
        "schema_id": column("schema_id"),
    },
    default_sort="-created_at",
    tie_breaker=column("id"),
    searchable=(column("name"),),
)

#: Per-entity list-query specs keyed by the plugin URL segment
#: (``nodes`` / ``services`` / ``schemas`` / ``tables``).
ENTITY_LIST_QUERY_SPECS: MappingProxyType[str, ListQuerySpec] = MappingProxyType(
    {
        "nodes": _NODES_SPEC,
        "services": _SERVICES_SPEC,
        "schemas": _SCHEMAS_SPEC,
        "tables": _TABLES_SPEC,
    }
)

__all__ = ["ENTITY_LIST_QUERY_SPECS"]
