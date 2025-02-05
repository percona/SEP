"""Define database operations for the Inventory API."""

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db.crud import BaseSQLModelChildManager, BaseSQLModelManager
from app.core.exceptions import HTTPNotFoundException
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

    @classmethod
    async def get_by_node_address_and_port(
        cls, session: AsyncSession, address: str, port: int
    ) -> Service:
        """Retrieve a Service using the node's address and the service's port.

        The combination of the node's address and the service's port is unique.

        :param session: The asynchronous session to use for the query.
        :param address: The node's address.
        :param port: The service's port.
        :return: The matching Service instance.
        :raises HTTPNotFoundException: If no matching service is found.
        """
        stmt = (
            select(cls.Model)
            .join(Node, cls.Model.node_id == Node.id)
            .where(Node.address == address, cls.Model.port == port)
        )
        result = await session.exec(stmt)
        service = result.one_or_none()
        if service is None:
            raise HTTPNotFoundException(
                f"No service found for node address '{address}' and port {port}"
            )
        return service


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
