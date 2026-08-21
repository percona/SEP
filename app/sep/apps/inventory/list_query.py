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

The shared ``GET /{entity}/`` route serves four entities, so the dependency
reads the path segment, dispatches to the matching spec, and validates
``sort`` / ``search`` against that entity alone. OpenAPI documents the union of
every entity's allowlist; per-entity validation still rejects a key that is
legal for another entity but not this one. The upstream adapter maps the
validated query back to the inventory service's ``sort`` / ``search`` query
params so the proxy never forwards raw, unvalidated client strings.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy import column

from app.core.db.list_query import (
    ListQuerySpec,
    search_query_param,
    SORT_PARAM_DESCRIPTION,
)
from app.sep.apps.framework.list_query import (
    build_in_memory_list_query,
    InMemoryListQuery,
)
from app.sep.apps.inventory.deps import require_inventory_plugin_entity

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

# ``inventory_list_query`` always advertises ``?search=`` (one shared signature
# cannot gate per entity the way ``make_in_memory_list_query_dep`` does). Fail
# at import if a future entity ships with an empty searchable set so OpenAPI
# and the client cannot advertise a param upstream would ignore.
_non_searchable = [
    entity
    for entity, spec in ENTITY_LIST_QUERY_SPECS.items()
    if not spec.search_enabled
]
if _non_searchable:
    raise ValueError(
        "inventory list-query specs must all be searchable because the shared "
        f"route always declares ?search=; got empty searchable for {_non_searchable!r}"
    )

# Union of every entity's public sort keys (both directions). Documents the
# shared route's OpenAPI enum; runtime validation still uses the per-entity
# allowlist so a schemas-only key is rejected on nodes.
_UNION_SORT_ENUM = [
    value
    for key in sorted(
        {key for spec in ENTITY_LIST_QUERY_SPECS.values() for key in spec.sortable}
    )
    for value in (key, f"-{key}")
]


def inventory_list_query(
    entity: str,
    sort: str | None = Query(
        default=None,
        description=SORT_PARAM_DESCRIPTION,
        json_schema_extra={"enum": _UNION_SORT_ENUM},
    ),
    search: str | None = search_query_param(),
) -> InMemoryListQuery:
    """Resolve ``sort`` / ``search`` against the entity's list-query allowlist.

    ``sort`` defaults to ``None`` rather than a single shared default because one
    OpenAPI declaration cannot carry four different entity defaults; an omitted
    ``sort`` resolves to the matching spec's ``default_sort``.

    :param entity: Inventory entity URL segment (``nodes``, ``services``,
        ``schemas``, or ``tables``).
    :param sort: Requested public sort key, optionally ``-`` prefixed, or
        ``None`` for the entity default.
    :param search: Raw search term, or ``None`` when unset.
    :return: The allowlist-vetted in-memory list query.
    :raises HTTPNotFoundException: When ``entity`` is unknown.
    :raises HTTPUnprocessableEntityException: When ``sort`` is outside the
        entity's allowlist.
    """
    entity = require_inventory_plugin_entity(entity)
    spec = ENTITY_LIST_QUERY_SPECS[entity]
    return build_in_memory_list_query(spec, sort or spec.default_sort, search)


InventoryListQueryDep = Annotated[InMemoryListQuery, Depends(inventory_list_query)]


def list_query_upstream_params(query: InMemoryListQuery) -> dict[str, str]:
    """Map a validated list query to inventory upstream query params.

    Always emits ``sort`` (re-prefixed when descending) so the proxy's
    per-entity default reaches upstream rather than the inventory service's
    own default. Emits ``search`` only when a non-blank term is present.

    :param query: The allowlist-vetted list query from the request boundary.
    :return: Query params to merge into the upstream inventory list request.
    """
    sort = f"-{query.sort_key}" if query.descending else query.sort_key
    params = {"sort": sort}
    if query.search is not None and query.search.strip():
        params["search"] = query.search
    return params


__all__ = [
    "ENTITY_LIST_QUERY_SPECS",
    "InventoryListQueryDep",
    "inventory_list_query",
    "list_query_upstream_params",
]
