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

"""Define the AppSchema for the Inventory plugin."""

from app.sep.apps.framework.schema import (
    AppEntitySchema,
    AppSchema,
    Capabilities,
    Column,
    ColumnFormat,
    DetailHighlightLanguage,
    ListView,
)

_nodes_entity = AppEntitySchema(
    name="nodes",
    display_name="Nodes",
    description="Physical or logical hosts tracked in inventory.",
    forms=[],
    list_view=ListView(
        columns=[
            Column(key="name", label="Name", sortable=True),
            Column(key="address", label="Address"),
            Column(key="type", label="Type", format=ColumnFormat.CHIP),
            Column(key="source", label="Source", format=ColumnFormat.CHIP),
            Column(key="created_at", label="Created", format=ColumnFormat.RELATIVE),
        ],
        default_sort="-created_at",
        server_side_query=True,
    ),
)

_services_entity = AppEntitySchema(
    name="services",
    display_name="Services",
    description="Database services attached to nodes.",
    forms=[],
    list_view=ListView(
        columns=[
            Column(key="name", label="Name", sortable=True),
            Column(key="type", label="Type", format=ColumnFormat.CHIP),
            Column(key="port", label="Port"),
            Column(key="environment", label="Environment"),
            Column(key="cluster", label="Cluster"),
            Column(key="replication_set", label="Replication set"),
        ],
        default_sort="-name",
        server_side_query=True,
    ),
)

_schemas_entity = AppEntitySchema(
    name="schemas",
    display_name="Schemas",
    description="Database schemas within a service.",
    forms=[],
    list_view=ListView(
        columns=[
            Column(key="name", label="Name", sortable=True),
            Column(key="service_id", label="Service ID", sortable=True),
            Column(key="created_at", label="Created", format=ColumnFormat.RELATIVE),
        ],
        default_sort="-created_at",
        server_side_query=True,
    ),
)

_tables_entity = AppEntitySchema(
    name="tables",
    display_name="Tables",
    description="Tables within a schema.",
    forms=[],
    list_view=ListView(
        columns=[
            Column(key="name", label="Name", sortable=True),
            Column(key="schema_id", label="Schema ID", sortable=True),
            Column(key="created_at", label="Created", format=ColumnFormat.RELATIVE),
        ],
        default_sort="-created_at",
        server_side_query=True,
    ),
    detail_highlights={
        "create": DetailHighlightLanguage.SQL,
        "keys": DetailHighlightLanguage.JSON,
    },
)

inventory_schema = AppSchema(
    name="inventory",
    display_name="Inventory",
    description="Manage nodes, services, database schemas, and tables.",
    entities=[_nodes_entity, _services_entity, _schemas_entity, _tables_entity],
    capabilities=Capabilities(scheduling=True),
)
