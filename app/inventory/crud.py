"""Define database operations for the Inventory API."""

from app.core.db.crud import BaseChildManager
from app.core.db.crud import BaseManager
from app.inventory.models import Node
from app.inventory.models import Schema
from app.inventory.models import Service
from app.inventory.models import Table


class NodeManager(BaseManager):
    """Manage Node operations, including retrieval, listing, and deletion.

    :param Model: The SQLModel class this manager is responsible for (`Node`).
    :type Model: type[Node]
    """

    Model = Node


class ServiceManager(BaseChildManager):
    """Manage Service operations, including retrieval, listing, and deletion.

    :param Model: The SQLModel class this manager is responsible for (`Service`).
    :type Model: type[Service]
    :param ParentManager: The manager class responsible for handling the parent model
        (`NodeManager`).
    :type ParentManager: type[NodeManager]
    :param connected_by: The field name that connects the child model to the parent
        model (`node_id`).
    :type connected_by: str
    """

    Model = Service
    ParentManager = NodeManager
    connected_by = "node_id"


class SchemaManager(BaseChildManager):
    """Manage Schema operations, including retrieval, listing, and deletion.

    :param Model: The SQLModel class this manager is responsible for (`Schema`).
    :type Model: type[Schema]
    :param ParentManager: The manager class responsible for handling the parent model
        (`ServiceManager`).
    :type ParentManager: type[ServiceManager]
    :param connected_by: The field name that connects the child model to the parent
        model (`service_id`).
    :type connected_by: str
    """

    Model = Schema
    ParentManager = ServiceManager
    connected_by = "service_id"


class TableManager(BaseChildManager):
    """Manage Table operations, including retrieval, listing, and deletion.

    :param Model: The SQLModel class this manager is responsible for (`Table`).
    :type Model: type[Table]
    :param ParentManager: The manager class responsible for handling the parent model
        (`SchemaManager`).
    :type ParentManager: type[SchemaManager]
    :param connected_by: The field name that connects the child model to the parent
        model (`schema_id`).
    :type connected_by: str
    """

    Model = Table
    ParentManager = SchemaManager
    connected_by = "schema_id"
