"""Define database operations for the Inventory API."""

from app.core.db.crud import BaseChildManager
from app.core.db.crud import BaseManager
from app.inventory.models import Node
from app.inventory.models import Schema
from app.inventory.models import Service
from app.inventory.models import Table


class NodeManager(BaseManager):
    """Manage Node operations, including retrieval, listing, and deletion.

    :ivar Model: The SQLModel class this manager is responsible for (`Node`).
    :vartype Model: type[Node]
    """

    Model = Node


class ServiceManager(BaseChildManager):
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


class SchemaManager(BaseChildManager):
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


class TableManager(BaseChildManager):
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
