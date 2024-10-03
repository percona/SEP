"""Define models for the Inventory API."""

from enum import auto
from enum import StrEnum
from typing import Self

from pydantic import model_validator
from sqlalchemy import Column
from sqlalchemy import Enum as EnumField
from sqlalchemy import Index
from sqlalchemy import Text
from sqlmodel import Field as SQLField
from sqlmodel import Relationship
from sqlmodel import SQLModel

from app.core.db import BaseSQLModel
from app.core.fields import RequiredStr


class SourceEnum(StrEnum):
    """Enumeration of possible data sources for a node."""

    PMM = auto()


class ServiceTypeEnum(StrEnum):
    """Enumeration of supported service types."""

    MYSQL = auto()
    POSTGRESQL = auto()
    MONGODB = auto()
    EXTERNAL = auto()


class NodeBase(SQLModel):
    """Define the base structure for node-related operations.

    Attributes
    ----------
    address : RequiredStr
        The network address of the node.
    name : RequiredStr
        The name of the node.
    external_id : RequiredStr or None, optional
        An external identifier for the node, indexed for quick lookup. Defaults to None.
    source : SourceEnum or None, optional
        The source from which the node information is derived. Indexed for quick lookup.
        Defaults to None.
    type : RequiredStr
        The type of the node (e.g., remote, generic). Defaults to "generic".

    """

    address: RequiredStr
    name: RequiredStr
    external_id: RequiredStr | None = SQLField(default=None, index=True)
    source: SourceEnum | None = SQLField(
        default=None,
        sa_column=Column(EnumField(SourceEnum)),
    )
    type: RequiredStr = SQLField(default="generic")  # TODO: Enum with allowed values

    @model_validator(mode="after")
    def validate_external_id_source(self) -> Self:
        """Ensure that external_id is set only if source is provided.

        Raises
        ------
        ValueError
            If `external_id` is provided without a corresponding `source`.

        Returns
        -------
        Self
            The validated instance.

        """
        if self.external_id is not None and self.source is None:
            raise ValueError("Can't set external_id if source is None")
        return self


class Node(NodeBase, BaseSQLModel, table=True):
    """Represent a node in the inventory.

    Attributes
    ----------
    address : RequiredStr
        The network address of the node.
    name : RequiredStr
        The name of the node.
    external_id : RequiredStr or None
        An external identifier for the node. Must be unique for source, as defined by
        composite index ix_node_external_id_source.
    source : SourceEnum or None
        The source from which the node information is derived. Must be unique for
        external_id, as defined by composite index ix_node_external_id_source.
    type : RequiredStr
        The type of the node (e.g., remote, generic).
    services : list[Service]
        A list of services associated with the node.

    """

    __table_args__ = (
        Index("ix_node_external_id_source", "external_id", "source", unique=True),
    )
    services: list["Service"] = Relationship(back_populates="node", cascade_delete=True)


class NodeWrite(NodeBase):
    """Define the model for writing node data to the inventory."""


class NodeResponse(NodeBase, BaseSQLModel):
    """Represent a node API response.

    Attributes
    ----------
    address : RequiredStr
        The network address of the node.
    name : RequiredStr
        The name of the node.
    external_id : RequiredStr or None
        An external identifier for the node.
    source : SourceEnum or None
        The source from which the node information is derived.
    type : RequiredStr
        The type of the node (e.g., remote, generic).
    services : list[Service]
        A list of services associated with the node.

    """

    services: list["Service"]


class ServiceBase(SQLModel):
    """Define the base structure for service-related operations.

    Attributes
    ----------
    external_id : RequiredStr or None, optional
        An external identifier for the service, indexed for quick lookup.
        Defaults to None.
    name : RequiredStr
        The name of the service.
    type : ServiceTypeEnum
        The type of the service (e.g., MYSQL, POSTGRESQL).
    port : int or None, optional
        The port number on which the service is running. Defaults to None.
    environment : str or None, optional
        The environment in which the service is running (e.g., production, staging).
        Defaults to None.
    node_id : int
        The foreign key referencing the node to which the service belongs.

    """

    external_id: RequiredStr | None = SQLField(
        default=None,
        index=True,
    )  # TODO: validate external_id not null if node source is defined
    name: RequiredStr
    type: ServiceTypeEnum = SQLField(
        sa_column=Column(EnumField(ServiceTypeEnum), nullable=False),
    )
    port: int | None = None
    environment: str | None = None  # TODO: Enum with allowed values
    node_id: int = SQLField(foreign_key="node.id", index=True, ondelete="CASCADE")


class ServiceWrite(ServiceBase):
    """Define the model for writing service data to the inventory."""

    node_id: int | None = SQLField(
        default=None,
        foreign_key="node.id",
        index=True,
        ondelete="CASCADE",
    )


class Service(ServiceBase, BaseSQLModel, table=True):
    """Represent a service running on a node in the inventory.

    Attributes
    ----------
    external_id : RequiredStr or None
        An external identifier for the service. Must be unique for node_id,
        as defined by composite index ix_service_external_id_node_id.
    name : RequiredStr
        The name of the service.
    type : ServiceTypeEnum
        The type of the service (e.g., MYSQL, POSTGRESQL).
    port : int or None
        The port number on which the service is running.
    environment : str or None
        The environment in which the service is running, if set.
    node_id : int
        The unique identifier of the node on which the service is running. Must be
        unique for external_id, as defined by composite index
        ix_service_external_id_node_id.
    node : Node
        The node to which the service is associated.
    schemas : list[Schema]
        A list of schemas associated with the service.

    """

    __table_args__ = (
        Index("ix_service_external_id_node_id", "external_id", "node_id", unique=True),
    )

    node: Node = Relationship(back_populates="services")
    schemas: list["Schema"] = Relationship(
        back_populates="service",
        cascade_delete=True,
    )


class ServiceResponse(ServiceBase, BaseSQLModel):
    """Define the service API response.

    Attributes
    ----------
    external_id : RequiredStr or None
        An external identifier for the service.
    name : RequiredStr
        The name of the service.
    type : ServiceTypeEnum
        The type of the service (e.g., MYSQL, POSTGRESQL).
    port : int or None
        The port number on which the service is running.
    environment : str or None
        The environment in which the service is running, if set.
    node_id : int
        The unique identifier of the node on which the service is running.
    schemas : list[Schema]
        A list of schemas associated with the service.

    """

    schemas: list["Schema"]


class ServiceDetailResponse(ServiceResponse):
    """Define the service retrieve API response.

    Attributes
    ----------
    external_id : RequiredStr or None
        An external identifier for the service.
    name : RequiredStr
        The name of the service.
    type : ServiceTypeEnum
        The type of the service (e.g., MYSQL, POSTGRESQL).
    port : int or None
        The port number on which the service is running.
    environment : str or None
        The environment in which the service is running, if set.
    node_id : int
        The unique identifier of the node on which the service is running.
    schemas : list[Schema]
        A list of schemas associated with the service.
    node: Node
        The service's node.

    """

    node: Node


class SchemaBase(SQLModel):
    """Define the base structure for schema-related operations.

    Attributes
    ----------
    name : RequiredStr
        The name of the schema.
    service_id : int
        The foreign key referencing the service to which the schema belongs.

    """

    name: RequiredStr
    service_id: int = SQLField(foreign_key="service.id", index=True, ondelete="CASCADE")


class Schema(SchemaBase, BaseSQLModel, table=True):
    """Represent a database schema within a service.

    Attributes
    ----------
    name : RequiredStr
        The name of the schema. Must be unique for service_id, as defined by composite
        index ix_schema_name_service_id.
    service_id : int
        The unique identifier of the service to which the schema belongs. Must be unique
        for name, as defined by composite index ix_schema_name_service_id.
    service : Service
        The service to which the schema is associated.
    tables : list[Table]
        A list of tables within the schema.

    """

    __table_args__ = (
        Index("ix_schema_name_service_id", "name", "service_id", unique=True),
    )
    service: Service = Relationship(back_populates="schemas")
    tables: list["Table"] = Relationship(cascade_delete=True)
    # TODO: Investigate why back populates with Table is not working


class SchemaWrite(SchemaBase):
    """Define the model for writing schema data to the inventory.

    Attributes
    ----------
    name : RequiredStr
        The name of the schema.
    service_id : int or None, optional
        The foreign key referencing the service to which the schema belongs.
        Defaults to None.

    """

    service_id: int | None = SQLField(
        default=None,
        foreign_key="service.id",
        index=True,
        ondelete="CASCADE",
    )


class SchemaResponse(SchemaBase, BaseSQLModel):
    """Define the schema API response.

    Attributes
    ----------
    name : RequiredStr
        The name of the schema.
    service_id : int
        The unique identifier of the service to which the schema belongs.
    tables : list[Table]
        A list of tables within the schema.

    """

    tables: list["Table"]


class TableBase(SQLModel):
    """Define the base structure for table-related operations.

    Attributes
    ----------
    name : RequiredStr
        The name of the table.
    create : RequiredStr
        The SQL statement used to create the table.
    schema_id : int
        The foreign key referencing the schema to which the table belongs.

    """

    name: RequiredStr
    create: RequiredStr = SQLField(sa_type=Text)
    schema_id: int = SQLField(foreign_key="schema.id", index=True, ondelete="CASCADE")


class Table(TableBase, BaseSQLModel, table=True):
    """Represent a table within a schema.

    Attributes
    ----------
    name : RequiredStr
        The name of the table. Must be unique for schema_id, as defined by composite
        index ix_table_name_schema_id.
    create : RequiredStr
        The SQL statement used to create the table.
    schema_id : int
        The unique identifier of the schema to which the table belongs. Must be unique
        for name, as defined by composite index ix_table_name_schema_id.
    schema : Schema
        The schema to which the table is associated.

    """

    __table_args__ = (
        Index("ix_table_name_schema_id", "name", "schema_id", unique=True),
    )


class TableWrite(TableBase):
    """Define the model for writing table data to the inventory."""

    schema_id: int | None = SQLField(
        default=None,
        foreign_key="schema.id",
        index=True,
        ondelete="CASCADE",
    )


class TableResponse(TableBase, BaseSQLModel):
    """Define the table API response."""
