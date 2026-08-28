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

from app.core.utils.fields import TCP_PORT_MAX, TCP_PORT_MIN
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.framework.schema import (
    AppEntitySchema,
    AppSchema,
    Capabilities,
    Choice,
    ChoiceField,
    Column,
    ColumnFormat,
    DetailHighlightLanguage,
    FormSection,
    IntegerField,
    ListView,
    StringField,
    TextAreaField,
    YamlField,
)

_SERVICE_TYPE_CHOICES = [
    Choice(label=t.value.replace("_", " ").title(), value=t.value)
    for t in ServiceTypeEnum
]

_nodes_entity = AppEntitySchema(
    name="nodes",
    display_name="Nodes",
    description="Physical or logical hosts tracked in inventory.",
    forms=[
        FormSection(
            title="Node",
            fields=[
                StringField(name="address", label="Address", required=True),
                StringField(name="name", label="Name", required=True),
                StringField(
                    name="external_id",
                    label="External ID",
                    required=True,
                    description="Identifier of the entity in PMM.",
                ),
                ChoiceField(
                    name="source",
                    label="Source",
                    required=True,
                    choices=[Choice(label="PMM", value="pmm")],
                ),
                StringField(
                    name="type",
                    label="Type",
                    default="generic",
                    description="Node classification (for example generic, remote).",
                ),
            ],
        ),
    ],
    list_view=ListView(
        columns=[
            Column(key="name", label="Name", sortable=True),
            Column(key="address", label="Address"),
            Column(key="type", label="Type", format=ColumnFormat.CHIP),
            Column(key="source", label="Source", format=ColumnFormat.CHIP),
            Column(key="created_at", label="Created", format=ColumnFormat.RELATIVE),
            Column(
                key="_actions",
                label="Actions",
                format=ColumnFormat.ACTIONS,
            ),
        ],
        default_sort="-created_at",
        server_side_query=True,
    ),
)

_services_entity = AppEntitySchema(
    name="services",
    display_name="Services",
    description="Database services attached to nodes.",
    forms=[
        FormSection(
            title="Service",
            fields=[
                IntegerField(name="node_id", label="Node ID", required=True, ge=1),
                StringField(name="name", label="Name", required=True),
                ChoiceField(
                    name="type",
                    label="Service type",
                    required=True,
                    choices=_SERVICE_TYPE_CHOICES,
                ),
                IntegerField(
                    name="port", label="Port", ge=TCP_PORT_MIN, le=TCP_PORT_MAX
                ),
                StringField(name="external_id", label="External ID", required=True),
                StringField(name="environment", label="Environment"),
                StringField(name="cluster", label="Cluster"),
                StringField(name="replication_set", label="Replication set"),
                YamlField(
                    name="custom_labels",
                    label="Custom labels",
                    description="Optional YAML/JSON object of labels.",
                ),
            ],
        ),
    ],
    list_view=ListView(
        columns=[
            Column(key="name", label="Name", sortable=True),
            Column(key="type", label="Type", format=ColumnFormat.CHIP),
            Column(key="port", label="Port"),
            Column(key="environment", label="Environment"),
            Column(key="cluster", label="Cluster"),
            Column(key="replication_set", label="Replication set"),
            Column(
                key="_actions",
                label="Actions",
                format=ColumnFormat.ACTIONS,
            ),
        ],
        default_sort="-name",
        server_side_query=True,
    ),
)

_schemas_entity = AppEntitySchema(
    name="schemas",
    display_name="Schemas",
    description="Database schemas within a service.",
    forms=[
        FormSection(
            title="Schema",
            fields=[
                IntegerField(
                    name="service_id", label="Service ID", required=True, ge=1
                ),
                StringField(name="name", label="Schema name", required=True),
            ],
        ),
    ],
    list_view=ListView(
        columns=[
            Column(key="name", label="Name", sortable=True),
            Column(key="service_id", label="Service ID", sortable=True),
            Column(key="created_at", label="Created", format=ColumnFormat.RELATIVE),
            Column(
                key="_actions",
                label="Actions",
                format=ColumnFormat.ACTIONS,
            ),
        ],
        default_sort="-created_at",
        server_side_query=True,
    ),
)

_tables_entity = AppEntitySchema(
    name="tables",
    display_name="Tables",
    description="Tables within a schema.",
    forms=[
        FormSection(
            title="Table",
            fields=[
                IntegerField(name="schema_id", label="Schema ID", required=True, ge=1),
                StringField(name="name", label="Table name", required=True),
                TextAreaField(
                    name="create",
                    label="CREATE statement",
                    required=True,
                    rows=6,
                    description="DDL used to define the table.",
                ),
                YamlField(
                    name="keys",
                    label="Keys",
                    required=True,
                    description="JSON describing primary / unique keys.",
                ),
            ],
        ),
    ],
    list_view=ListView(
        columns=[
            Column(key="name", label="Name", sortable=True),
            Column(key="schema_id", label="Schema ID", sortable=True),
            Column(key="created_at", label="Created", format=ColumnFormat.RELATIVE),
            Column(
                key="_actions",
                label="Actions",
                format=ColumnFormat.ACTIONS,
            ),
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
