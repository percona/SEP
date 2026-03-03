# Copyright 2025 Percona LLC
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

from app.core.db.crud import BaseSQLModelChildManager, BaseSQLModelManager
from app.inventory.models import Node, Schema, Service, Table


class NodeManager(BaseSQLModelManager):
    """Manage Node operations, including retrieval, listing, and deletion.

    :ivar Model: The SQLModel class this manager is responsible for (`Node`).
    :vartype Model: type[Node]
    """

    Model = Node


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
    """

    Model = Service
    ParentManager = NodeManager
    connected_by = "node_id"


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
    """

    Model = Schema
    ParentManager = ServiceManager
    connected_by = "service_id"


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
    """

    Model = Table
    ParentManager = SchemaManager
    connected_by = "schema_id"
