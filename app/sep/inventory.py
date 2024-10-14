"""Define models for interacting with the Inventory API."""

from typing import Self

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

from app.core.db import BaseSQLModel
from app.core.fields import EmptyStrToNone
from app.core.fields import RequiredStr
from app.inventory.models import SourceEnum


class BaseInventoryModel(BaseModel):
    """Define the base structure for inventory-related data.

    This model serves as a foundation for all inventory-related operations,
    providing common configuration settings that ensure consistency across
    derived models.
    """

    model_config = ConfigDict(populate_by_name=True)


class Node(BaseInventoryModel):
    """Represent an inventory node.

    This model represents a node within the Inventory API, including its network
    address, external identifier, name, and type.

    :param address: The network address of the node.
    :type address: RequiredStr
    :param external_id: The external identifier for the node, aliased as "node_id".
        Defaults to None.
    :type external_id: RequiredStr | EmptyStrToNone
    :param name: The name of the node, aliased as "node_name".
    :type name: RequiredStr
    :param type: The type of the node (e.g., "generic"), aliased as "node_type".
        Defaults to "generic".
    :type type: RequiredStr
    :param source: The source of the node information. Defaults to None.
    :type source: SourceEnum | EmptyStrToNone
    """

    address: RequiredStr
    external_id: RequiredStr | EmptyStrToNone = Field(
        default=None,
        validation_alias="node_id",
    )
    name: RequiredStr = Field(validation_alias="node_name")
    type: RequiredStr = Field(default="generic", validation_alias="node_type")
    source: SourceEnum | EmptyStrToNone = None


class CreatedNode(BaseSQLModel, Node):
    """Represent an existent node from the inventory database.

    This model extends `Node` and `BaseSQLModel` to integrate attributes from an
    existent database node.

    :param id: The primary key of the node in the inventory database.
    :type id: UUID4
    :param created_at: The timestamp when the node was created. Defaults to the current
        time in UTC.
    :type created_at: datetime
    :param updated_at: The timestamp when the record was last updated. Automatically
        updated on changes.
    :type updated_at: datetime | None
    :param address: The network address of the node.
    :type address: RequiredStr
    :param external_id: The external identifier for the node, aliased as "node_id".
        Defaults to None.
    :type external_id: RequiredStr | EmptyStrToNone
    :param name: The name of the node, aliased as "node_name".
    :type name: RequiredStr
    :param type: The type of the node (e.g., "generic"), aliased as "node_type".
        Defaults to "generic".
    :type type: RequiredStr
    :param source: The source of the node information. Defaults to None.
    :type source: SourceEnum | EmptyStrToNone
    :param services: A list of existent services associated with the node.
    :type services: list[CreatedService]
    """

    services: list["CreatedService"] = []

    @property
    def children(self) -> list["CreatedService"]:
        """Retrieve the list of services associated with the node.

        :return: The services associated with the node.
        :rtype: list[CreatedService]
        """
        return self.services

    @model_validator(mode="after")
    def add_node_to_services(self) -> Self:
        """Assign the node instance to each associated service.

        Iterate through the list of services and set the `node` attribute
        of each service to reference this node instance.

        :return: The node instance with services updated to reference it.
        :rtype: CreatedNode
        """
        for service in self.services:
            service.node = CreatedServiceNode.model_validate(self)
        return self


class CreatedServiceNode(BaseSQLModel, Node):
    """Represent a node from a created service.

    This model extends `Node` and `BaseSQLModel` to integrate attributes from an
    existent database node.

    :param id: The primary key of the node in the inventory database.
    :type id: UUID4
    :param created_at: The timestamp when the node was created. Defaults to the current
        time in UTC.
    :type created_at: datetime
    :param updated_at: The timestamp when the record was last updated. Automatically
        updated on changes.
    :type updated_at: datetime | None
    :param address: The network address of the node.
    :type address: RequiredStr
    :param external_id: The external identifier for the node, aliased as "node_id".
        Defaults to None.
    :type external_id: RequiredStr | EmptyStrToNone
    :param name: The name of the node, aliased as "node_name".
    :type name: RequiredStr
    :param type: The type of the node (e.g., "generic"), aliased as "node_type".
        Defaults to "generic".
    :type type: RequiredStr
    :param source: The source of the node information. Defaults to None.
    :type source: SourceEnum | EmptyStrToNone
    """


class Service(BaseInventoryModel):
    """Represent an inventory service.

    This model represents a service within the Inventory API, including its environment,
    external identifier, name, port, and type.

    :param environment: The environment in which the service is running (e.g.,
        "production", "staging"). Defaults to None.
    :type environment: str | None
    :param external_id: The external identifier for the service, aliased as
        "service_id". Defaults to None.
    :type external_id: RequiredStr | EmptyStrToNone
    :param name: The name of the service, aliased as "service_name".
    :type name: RequiredStr
    :param port: The port number on which the service is running, aliased as
        "service_port". Defaults to None.
    :type port: int | EmptyStrToNone
    :param type: The type of the service (e.g., "service_type"), aliased as
        "service_type". Defaults to "generic".
    :type type: RequiredStr
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

    :param id: The primary key of the service in the inventory database.
    :type id: UUID4
    :param created_at: The timestamp when the service was created. Defaults to the
        current time in UTC.
    :type created_at: datetime
    :param updated_at: The timestamp when the record was last updated. Automatically
        updated on changes.
    :type updated_at: datetime | None
    :param environment: The environment in which the service is running (e.g.,
        "production", "staging").
    :type environment: str | None
    :param external_id: The external identifier for the service, aliased as
        "service_id". Defaults to None.
    :type external_id: RequiredStr | EmptyStrToNone
    :param name: The name of the service, aliased as "service_name".
    :type name: RequiredStr
    :param port: The port number on which the service is running, aliased as
        "service_port".
    :type port: int | EmptyStrToNone
    :param type: The type of the service (e.g., "service_type"), aliased as
        "service_type". Defaults to "generic".
    :type type: RequiredStr
    :param node: The node to which the service is associated. Defaults to None.
    :type node: CreatedServiceNode | None
    :param schemas: A list of existent schemas associated with the service.
    :type schemas: list[CreatedSchema]
    """

    node: CreatedServiceNode | None = None
    schemas: list["CreatedSchema"] = []

    @property
    def children(self) -> list["CreatedSchema"]:
        """Retrieve the list of schemas associated with the service.

        :return: The schemas associated with the service.
        :rtype: list[CreatedSchema]
        """
        return self.schemas


class Schema(BaseInventoryModel):
    """Represent an inventory schema.

    :param name: The name of the schema.
    :type name: RequiredStr
    """

    name: RequiredStr


class CreatedSchema(BaseSQLModel, Schema):
    """Represent an existent schema from the inventory database.

    This model extends `Schema` and `BaseSQLModel` to integrate attributes from an
    existent database schema.

    :param id: The primary key of the schema in the inventory database.
    :type id: UUID4
    :param created_at: The timestamp when the schema was created. Defaults to the
        current time in UTC.
    :type created_at: datetime
    :param updated_at: The timestamp when the record was last updated. Automatically
        updated on changes.
    :type updated_at: datetime | None
    :param name: The name of the schema.
    :type name: RequiredStr
    :param tables: A list of existent tables associated with the schema.
    :type tables: list[CreatedTable]
    """

    name: RequiredStr
    tables: list["CreatedTable"] = []

    @property
    def children(self) -> list["CreatedTable"]:
        """Retrieve the list of tables associated with the schema.

        :return: The tables associated with the schema.
        :rtype: list[CreatedTable]
        """
        return self.tables


class Table(BaseInventoryModel):
    """Represent an inventory table.

    This model represents a table within a schema in the Inventory API, including its
    name and the SQL statement used to create the table.

    :param name: The name of the table.
    :type name: RequiredStr
    :param create: The SQL statement used to create the table.
    :type create: RequiredStr
    """

    name: RequiredStr
    create: RequiredStr


class CreatedTable(BaseSQLModel, Table):
    """Represent an existent table from the inventory database.

    This model extends `Table` and `BaseSQLModel` to integrate attributes from an
    existent database table.

    :param id: The primary key of the table in the inventory database.
    :type id: UUID4
    :param created_at: The timestamp when the table was created. Defaults to the current
        time in UTC.
    :type created_at: datetime
    :param updated_at: The timestamp when the record was last updated. Automatically
        updated on changes.
    :type updated_at: datetime | None
    :param name: The name of the table.
    :type name: RequiredStr
    :param create: The SQL statement used to create the table.
    :type create: RequiredStr
    """

    name: RequiredStr
    create: RequiredStr

    @property
    def children(self) -> list:
        """Retrieve the list of child entities associated with the table.

        Returns an empty list as tables do not have child entities.

        :return: An empty list.
        :rtype: list
        """
        return []


CreatedEntity = CreatedNode | CreatedService | CreatedSchema | CreatedTable
