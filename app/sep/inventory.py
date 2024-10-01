"""Define models for interacting with the Inventory API."""

from typing import Self

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

from app.core.db import BaseSQLModel
from app.core.fields import EmptyStrToNone
from app.core.fields import RequiredStr


class BaseInventoryModel(BaseModel):
    """Define the base structure for inventory-related data.

    This model serves as a foundation for all inventory-related operations,
    providing common configuration settings that ensure consistency across
    derived models.
    """

    model_config = ConfigDict(populate_by_name=True)


class NodeBase(BaseInventoryModel):
    """Define the base structure for node-related data.

    This model serves as a foundation for node-related operations, including the
    network address, external identifier, name, and type of the node.

    Attributes
    ----------
    address : RequiredStr
        The network address of the node.
    external_id : RequiredStr or EmptyStrToNone, optional
        The external identifier for the node, aliased as "node_id". Defaults to None.
    name : RequiredStr
        The name of the node, aliased as "node_name".
    type : RequiredStr, optional
        The type of the node (e.g., "generic"), aliased as "node_type".
        Defaults to "generic".

    """

    address: RequiredStr
    external_id: RequiredStr | EmptyStrToNone = Field(
        default=None,
        validation_alias="node_id",
    )
    name: RequiredStr = Field(validation_alias="node_name")
    type: RequiredStr = Field(default="generic", validation_alias="node_type")


class Node(NodeBase):
    """Represent an inventory node.

    This model extends `NodeBase` by including additional attributes specific to
    the node's source. It represents a complete node entity within the Inventory API.

    Attributes
    ----------
    address : RequiredStr
        The network address of the node.
    external_id : RequiredStr or EmptyStrToNone, optional
        The external identifier for the node, aliased as "node_id". Defaults to None.
    name : RequiredStr
        The name of the node, aliased as "node_name".
    type : RequiredStr, optional
        The type of the node (e.g., "generic"), aliased as "node_type".
        Defaults to "generic".
    source : RequiredStr or EmptyStrToNone, optional
        The source of the node information. Defaults to None.

    """

    source: RequiredStr | EmptyStrToNone = None  # TODO: Create redundant source enum


class CreatedServiceNode(BaseSQLModel, Node):
    """Represent a node from a created service.

    This model extends `Node` and `BaseSQLModel` to integrate attributes from an
    existent database node.

    Attributes
    ----------
    id : int or None
        The primary key of the node in the inventory database.
    created_at : datetime, optional
        The timestamp when the node was created. Defaults to the current time in UTC.
    updated_at : datetime or None
        The timestamp when the record was last updated.
    address : RequiredStr
        The network address of the node.
    external_id : RequiredStr or EmptyStrToNone, optional
        The external identifier for the node, aliased as "node_id". Defaults to None.
    name : RequiredStr
        The name of the node, aliased as "node_name".
    type : RequiredStr, optional
        The type of the node (e.g., "generic"), aliased as "node_type".
        Defaults to "generic".
    source : RequiredStr or EmptyStrToNone, optional
        The source of the node information. Defaults to None.

    """


class CreatedNode(BaseSQLModel, Node):
    """Represent an existent node from the inventory database.

    This model extends `Node` and `BaseSQLModel` to integrate attributes from an
    existent database node.

    Attributes
    ----------
    id : int or None
        The primary key of the node in the inventory database.
    created_at : datetime, optional
        The timestamp when the node was created. Defaults to the current time in UTC.
    updated_at : datetime or None
        The timestamp when the record was last updated.
    address : RequiredStr
        The network address of the node.
    external_id : RequiredStr or EmptyStrToNone, optional
        The external identifier for the node, aliased as "node_id". Defaults to None.
    name : RequiredStr
        The name of the node, aliased as "node_name".
    type : RequiredStr, optional
        The type of the node (e.g., "generic"), aliased as "node_type".
        Defaults to "generic".
    source : RequiredStr or EmptyStrToNone, optional
        The source of the node information. Defaults to None.
    services : list[CreatedService]
        A list of existent services associated with the node.

    """

    services: list["CreatedService"] = []

    @model_validator(mode="after")
    def add_node_to_services(self) -> Self:
        """Assign the node instance to each associated service.

        Iterate through the list of services and set the `node` attribute
        of each service to reference this node instance.

        Returns
        -------
        Self
            The node instance with services updated to reference it.

        """
        for service in self.services:
            service.node = CreatedServiceNode.model_validate(self)
        return self


class Service(BaseInventoryModel):
    """Represent an inventory service.

    This model represents a service within the Inventory API, including its environment,
    external identifier, name, port, and type.

    Attributes
    ----------
    environment : str or None, optional
        The environment in which the service is running (e.g., "production", "staging").
        Defaults to None.
    external_id : RequiredStr or EmptyStrToNone, optional
        The external identifier for the service. Defaults to None.
    name : RequiredStr
        The name of the service.
    port : int or EmptyStrToNone, optional
        The port number on which the service is running. Defaults to None.
    type : RequiredStr, optional
        The type of the service (e.g., "service_type"), aliased as "service_type".
        Defaults to "generic".

    """

    environment: str | None = None
    external_id: RequiredStr | EmptyStrToNone = Field(
        default=None,
        validation_alias="service_id",
    )
    name: RequiredStr = Field(validation_alias="service_name")
    port: int | EmptyStrToNone = None
    type: RequiredStr = Field(validation_alias="service_type")


class CreatedService(BaseSQLModel, Service):
    """Represent an existent service from the inventory database.

    This model extends `Service` and `BaseSQLModel` to integrate attributes from an
    existent database service.

    Attributes
    ----------
    id : int or None
        The primary key of the node in the inventory database.
    created_at : datetime, optional
        The timestamp when the node was created. Defaults to the current time in UTC.
    updated_at : datetime or None
        The timestamp when the record was last updated.
    environment : str or None, optional
        The environment in which the service is running (e.g., "production", "staging").
        Defaults to None.
    external_id : RequiredStr or EmptyStrToNone, optional
        The external identifier for the service. Defaults to None.
    name : RequiredStr
        The name of the service.
    port : int or EmptyStrToNone, optional
        The port number on which the service is running. Defaults to None.
    type : RequiredStr, optional
        The type of the service (e.g., "service_type"), aliased as "service_type".
        Defaults to "generic".
    node : CreatedServiceNode or None, optional
        The node to which the service is associated. Defaults to None.

    """

    node: CreatedServiceNode | None = None


class Schema(BaseModel):
    """Represent an inventory schema.

    Attributes
    ----------
    name : RequiredStr
        The name of the schema.

    """

    name: RequiredStr


class Table(BaseModel):
    """Represent an inventory table.

    This model represents a table within a schema in the Inventory API, including its
    name and the SQL statement used to create the table.

    Attributes
    ----------
    name : RequiredStr
        The name of the table.
    create : RequiredStr
        The SQL statement used to create the table.

    """

    name: RequiredStr
    create: RequiredStr
