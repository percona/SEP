"""Define database operations for the Inventory API."""

from typing import TypeVar

from sqlmodel import SQLModel

from app.core.db import BaseSQLModel
from app.core.db.crud import BaseChildManager
from app.core.db.crud import BaseManager
from app.inventory.models import Node
from app.inventory.models import Schema
from app.inventory.models import Service
from app.inventory.models import Table

T = TypeVar("T", bound=BaseSQLModel)
M = TypeVar("M", bound=SQLModel)


class NodeManager(BaseManager):
    """Manage Node operations, including retrieval, listing, and deletion.

    Attributes
    ----------
    Model : type[Node]
        The SQLModel class this manager is responsible for (`Node`).

    """

    Model = Node


class ServiceManager(BaseChildManager):
    """Manage Service operations, including retrieval, listing, and deletion.

    Attributes
    ----------
    Model : type[Service]
        The SQLModel class this manager is responsible for (`Service`).
    ParentManager : type[NodeManager]
    connected_by: str

    """

    Model = Service
    ParentManager = NodeManager
    connected_by = "node_id"


class SchemaManager(BaseChildManager):
    """Manage Schema operations, including retrieval, listing, and deletion.

    Attributes
    ----------
    Model : type[Schema]
        The SQLModel class this manager is responsible for (`Schema`).
    ParentManager : type[ServiceManager]
    connected_by: str

    """

    Model = Schema
    ParentManager = ServiceManager
    connected_by = "service_id"


class TableManager(BaseChildManager):
    """Manage Table operations, including retrieval, listing, and deletion.

    Attributes
    ----------
    Model : type[Table]
        The SQLModel class this manager is responsible for (`Table`).
    ParentManager : type[SchemaManager]
    connected_by: str

    """

    Model = Table
    ParentManager = SchemaManager
    connected_by = "schema_id"
