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

"""Define database operations for the Inventory API."""

from sqlmodel import col

from app.core.db import ListQuerySpec
from app.core.db.crud import BaseSQLModelChildManager, BaseSQLModelManager
from app.inventory.models import (
    HostSystemObservation,
    Node,
    Schema,
    Service,
    ServiceSystemObservation,
    Table,
)


class NodeManager(BaseSQLModelManager):
    """Manage Node operations, including retrieval, listing, and deletion.

    :ivar Model: The SQLModel class this manager is responsible for (`Node`).
    :vartype Model: type[Node]
    :cvar list_query_spec: The list-query spec declaring this entity's sortable
        allowlist, searchable columns, and default sort.
    """

    Model = Node
    list_query_spec = ListQuerySpec(
        sortable={
            "name": col(Node.name),
            "created_at": col(Node.created_at),
        },
        default_sort="name",
        tie_breaker=col(Node.id),
        searchable=[col(Node.name)],
    )


class ServiceManager(BaseSQLModelChildManager):
    """Manage Service operations, including retrieval, listing, and deletion.

    :ivar Model: The SQLModel class this manager is responsible for (`Service`).
    :vartype Model: type[Service]
    :ivar ParentManager: The manager class responsible for handling the parent model
        (`NodeManager`).
    :vartype ParentManager: type[NodeManager]
    :ivar connected_by: The field name that connects the child model to the parent
        model (`node_id`).
    :vartype connected_by: str
    :cvar list_query_spec: The list-query spec declaring this entity's sortable
        allowlist, searchable columns, and default sort.
    """

    Model = Service
    ParentManager = NodeManager
    connected_by = "node_id"
    list_query_spec = ListQuerySpec(
        sortable={
            "name": col(Service.name),
            "created_at": col(Service.created_at),
        },
        default_sort="name",
        tie_breaker=col(Service.id),
        searchable=[col(Service.name)],
    )


class SchemaManager(BaseSQLModelChildManager):
    """Manage Schema operations, including retrieval, listing, and deletion.

    :ivar Model: The SQLModel class this manager is responsible for (`Schema`).
    :vartype Model: type[Schema]
    :ivar ParentManager: The manager class responsible for handling the parent model
        (`ServiceManager`).
    :vartype ParentManager: type[ServiceManager]
    :ivar connected_by: The field name that connects the child model to the parent
        model (`service_id`).
    :vartype connected_by: str
    :cvar list_query_spec: The list-query spec declaring this entity's sortable
        allowlist, searchable columns, and default sort.
    """

    Model = Schema
    ParentManager = ServiceManager
    connected_by = "service_id"
    list_query_spec = ListQuerySpec(
        sortable={
            "name": col(Schema.name),
            "created_at": col(Schema.created_at),
        },
        default_sort="name",
        tie_breaker=col(Schema.id),
        searchable=[col(Schema.name)],
    )


class TableManager(BaseSQLModelChildManager):
    """Manage Table operations, including retrieval, listing, and deletion.

    :ivar Model: The SQLModel class this manager is responsible for (`Table`).
    :vartype Model: type[Table]
    :ivar ParentManager: The manager class responsible for handling the parent model
        (`SchemaManager`).
    :vartype ParentManager: type[SchemaManager]
    :ivar connected_by: The field name that connects the child model to the parent
        model (`schema_id`).
    :vartype connected_by: str
    :cvar list_query_spec: The list-query spec declaring this entity's sortable
        allowlist, searchable columns, and default sort.
    """

    Model = Table
    ParentManager = SchemaManager
    connected_by = "schema_id"
    list_query_spec = ListQuerySpec(
        sortable={
            "name": col(Table.name),
            "created_at": col(Table.created_at),
        },
        default_sort="name",
        tie_breaker=col(Table.id),
        searchable=[col(Table.name)],
    )


class HostSystemObservationManager(BaseSQLModelChildManager):
    """Manage host system observation operations.

    :ivar Model: The SQLModel class this manager is responsible for
        (`HostSystemObservation`).
    :vartype Model: type[HostSystemObservation]
    :ivar ParentManager: The manager class responsible for handling the parent model
        (`NodeManager`).
    :vartype ParentManager: type[NodeManager]
    :ivar connected_by: The field name that connects the child model to the parent
        model (`node_id`).
    :vartype connected_by: str
    """

    Model = HostSystemObservation
    ParentManager = NodeManager
    connected_by = "node_id"


class ServiceSystemObservationManager(BaseSQLModelChildManager):
    """Manage service system observation operations.

    :ivar Model: The SQLModel class this manager is responsible for
        (`ServiceSystemObservation`).
    :vartype Model: type[ServiceSystemObservation]
    :ivar ParentManager: The manager class responsible for handling the parent model
        (`ServiceManager`).
    :vartype ParentManager: type[ServiceManager]
    :ivar connected_by: The field name that connects the child model to the parent
        model (`service_id`).
    :vartype connected_by: str
    """

    Model = ServiceSystemObservation
    ParentManager = ServiceManager
    connected_by = "service_id"
