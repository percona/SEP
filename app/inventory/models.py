"""Define models for the Inventory API."""

from enum import auto, StrEnum
from typing import Any, Self

from pydantic import model_validator
from sqlalchemy import Column, Index, JSON, Text
from sqlalchemy import Enum as EnumField
from sqlmodel import Field as SQLField
from sqlmodel import Relationship, SQLModel

from app.core.db import BaseSQLModel
from app.core.utils.fields import RequiredStr


class SourceEnum(StrEnum):
    """Enumeration of possible data sources for a node.

    :cvar PMM: Represents the PMM data source.
    :vartype PMM: str
    """

    PMM = auto()


class ServiceTypeEnum(StrEnum):
    """Enumeration of supported service types.

    :cvar MYSQL: Represents the MySQL service type.
    :vartype MYSQL: str
    :cvar POSTGRESQL: Represents the PostgreSQL service type.
    :vartype POSTGRESQL: str
    :cvar MONGODB: Represents the MongoDB service type.
    :vartype MONGODB: str
    :cvar PROXYSQL: Represents the ProxySQL service type.
    :vartype PROXYSQL: str
    :cvar HAPROXY: Represents the HAProxy service type.
    :vartype HAPROXY: str
    :cvar EXTERNAL: Represents an external service type.
    :vartype EXTERNAL: str
    """

    MYSQL = auto()
    POSTGRESQL = auto()
    MONGODB = auto()
    PROXYSQL = auto()
    HAPROXY = auto()
    EXTERNAL = auto()


class NodeBase(SQLModel):
    """Define the base structure for node-related operations.

    :param address: The network address of the node.
    :type address: RequiredStr
    :param name: The name of the node.
    :type name: RequiredStr
    :param external_id: An external identifier for the node, indexed for quick lookup.
        Defaults to None.
    :type external_id: RequiredStr | None
    :param source: The source from which the node information is derived. Indexed for
        quick lookup. Defaults to None.
    :type source: SourceEnum | None
    :param type: The type of the node (e.g., remote, generic). Defaults to "generic".
    :type type: RequiredStr
    """

    address: RequiredStr
    name: RequiredStr
    external_id: RequiredStr | None = SQLField(default=None, index=True)
    source: SourceEnum | None = SQLField(
        default=None,
        sa_column=Column(EnumField(SourceEnum)),
    )
    type: RequiredStr = SQLField(
        default="generic"
    )  # TODO: Enum with allowed values  # noqa: TD002, TD003

    @model_validator(mode="after")
    def validate_external_id_source(self) -> Self:
        """Ensure that external_id is set only if source is provided.

        Raises
        ------
        ValueError
            If `external_id` is provided without a corresponding `source`.

        :return: The validated instance.
        :rtype: Self

        """
        if self.external_id is not None and self.source is None:
            raise ValueError("Can't set external_id if source is None")
        return self


class Node(NodeBase, BaseSQLModel, table=True):
    """Represent a node in the inventory.

    :param address: The network address of the node.
    :type address: RequiredStr
    :param name: The name of the node.
    :type name: RequiredStr
    :param external_id: An external identifier for the node. Must be unique for source,
        as defined by composite index ix_node_external_id_source.
    :type external_id: RequiredStr | None
    :param source: The source from which the node information is derived. Must be unique
        for external_id, as defined by composite index ix_node_external_id_source.
    :type source: SourceEnum | None
    :param type: The type of the node (e.g., remote, generic).
    :type type: RequiredStr
    :param services: A list of services associated with the node.
    :type services: list[Service]
    """

    __table_args__ = (
        Index("ix_node_external_id_source", "external_id", "source", unique=True),
    )
    services: list["Service"] = Relationship(back_populates="node", cascade_delete=True)


class NodeWrite(NodeBase):
    """Define the model for writing node data to the inventory.

    :param address: The network address of the node.
    :type address: RequiredStr
    :param name: The name of the node.
    :type name: RequiredStr
    :param external_id: An external identifier for the node, indexed for quick lookup.
        Defaults to None.
    :type external_id: RequiredStr | None
    :param source: The source from which the node information is derived. Indexed for
        quick lookup. Defaults to None.
    :type source: SourceEnum | None
    :param type: The type of the node (e.g., remote, generic). Defaults to "generic".
    :type type: RequiredStr
    """


class NodeResponse(BaseSQLModel, NodeBase):
    """Represent a node API response.

    :param id: The primary key for the table. Auto-incremented and not nullable.
    :type id: int | None
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :type created_at: UTCDatetime
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :type updated_at: UTCDatetime | None
    :param address: The network address of the node.
    :type address: RequiredStr
    :param name: The name of the node.
    :type name: RequiredStr
    :param external_id: An external identifier for the node.
    :type external_id: RequiredStr | None
    :param source: The source from which the node information is derived.
    :type source: SourceEnum | None
    :param type: The type of the node (e.g., remote, generic).
    :type type: RequiredStr
    :param services: A list of services associated with the node.
    :type services: list[Service]
    """

    services: list["Service"]


class ServiceBase(SQLModel):
    """Define the base structure for service-related operations.

    :param external_id: An external identifier for the service, indexed for quick
        lookup. Defaults to None.
    :type external_id: RequiredStr | None
    :param name: The name of the service.
    :type name: RequiredStr
    :param type: The type of the service (e.g., MYSQL, POSTGRESQL).
    :type type: ServiceTypeEnum
    :param port: The port number on which the service is running. Defaults to None.
    :type port: int | None
    :param environment: The environment in which the service is running (e.g.,
        production, staging). Defaults to None.
    :type environment: str | None
    :param node_id: The foreign key referencing the node to which the service belongs.
    :type node_id: int
    """

    external_id: RequiredStr | None = SQLField(
        default=None,
        index=True,
    )  # TODO: validate external_id not null if node source is defined  # noqa: TD002, TD003
    name: RequiredStr
    type: ServiceTypeEnum = SQLField(
        sa_column=Column(EnumField(ServiceTypeEnum), nullable=False),
    )
    port: int | None = None
    environment: str | None = (
        None  # TODO: Enum with allowed values  # noqa: TD002, TD003
    )
    node_id: int = SQLField(foreign_key="node.id", index=True, ondelete="CASCADE")


class ServiceWrite(ServiceBase):
    """Define the model for writing service data to the inventory.

    :param external_id: An external identifier for the service, indexed for quick
        lookup. Defaults to None.
    :type external_id: RequiredStr | None
    :param name: The name of the service.
    :type name: RequiredStr
    :param type: The type of the service (e.g., MYSQL, POSTGRESQL).
    :type type: ServiceTypeEnum
    :param port: The port number on which the service is running. Defaults to None.
    :type port: int | None
    :param environment: The environment in which the service is running (e.g.,
        production, staging). Defaults to None.
    :type environment: str | None
    :param node_id: The foreign key referencing the node to which the service belongs.
        Defaults to None.
    :type node_id: int | None
    """

    node_id: int | None = SQLField(
        default=None,
        foreign_key="node.id",
        index=True,
        ondelete="CASCADE",
    )


class Service(BaseSQLModel, ServiceBase, table=True):
    """Represent a service running on a node in the inventory.

    :param id: The primary key for the table. Auto-incremented and not nullable.
    :type id: int | None
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :type created_at: UTCDatetime
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :type updated_at: UTCDatetime | None
    :param external_id: An external identifier for the service. Must be unique for
        node_id, as defined by composite index ix_service_external_id_node_id.
    :type external_id: RequiredStr | None
    :param name: The name of the service.
    :type name: RequiredStr
    :param type: The type of the service (e.g., MYSQL, POSTGRESQL).
    :type type: ServiceTypeEnum
    :param port: The port number on which the service is running. Must be unique for
        node_id, as defined by composite index ix_service_port_node_id.
    :type port: int | None
    :param environment: The environment in which the service is running, if set.
    :type environment: str | None
    :param node_id: The unique identifier of the node on which the service is running.
        Must be unique for external_id, as defined by composite index
        ix_service_external_id_node_id, and for port, as defined by composite index
        ix_service_port_node_id.
    :type node_id: int
    :param node: The node to which the service is associated.
    :type node: Node
    :param schemas: A list of schemas associated with the service.
    :type schemas: list[Schema]
    """

    __table_args__ = (
        Index("ix_service_external_id_node_id", "external_id", "node_id", unique=True),
        Index("ix_service_port_node_id", "port", "node_id", unique=True),
    )

    node: Node = Relationship(back_populates="services")
    schemas: list["Schema"] = Relationship(
        back_populates="service",
        cascade_delete=True,
    )


class ServiceResponse(BaseSQLModel, ServiceBase):
    """Define the service API response.

    :param id: The primary key for the table. Auto-incremented and not nullable.
    :type id: int | None
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :type created_at: UTCDatetime
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :type updated_at: UTCDatetime | None
    :param external_id: An external identifier for the service.
    :type external_id: RequiredStr | None
    :param name: The name of the service.
    :type name: RequiredStr
    :param type: The type of the service (e.g., MYSQL, POSTGRESQL).
    :type type: ServiceTypeEnum
    :param port: The port number on which the service is running.
    :type port: int | None
    :param environment: The environment in which the service is running, if set.
    :type environment: str | None
    :param node_id: The unique identifier of the node on which the service is running.
    :type node_id: int
    :param schemas: A list of schemas associated with the service.
    :type schemas: list[Schema]
    """

    schemas: list["Schema"]


class ServiceDetailResponse(ServiceResponse):
    """Define the service retrieve API response.

    :param id: The primary key for the table. Auto-incremented and not nullable.
    :type id: int | None
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :type created_at: UTCDatetime
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :type updated_at: UTCDatetime | None
    :param external_id: An external identifier for the service.
    :type external_id: RequiredStr | None
    :param name: The name of the service.
    :type name: RequiredStr
    :param type: The type of the service (e.g., MYSQL, POSTGRESQL).
    :type type: ServiceTypeEnum
    :param port: The port number on which the service is running.
    :type port: int | None
    :param environment: The environment in which the service is running, if set.
    :type environment: str | None
    :param node_id: The unique identifier of the node on which the service is running.
    :type node_id: int
    :param schemas: A list of schemas associated with the service.
    :type schemas: list[Schema]
    :param node: The service's node.
    :type node: Node
    """

    node: Node


class SchemaBase(SQLModel):
    """Define the base structure for schema-related operations.

    :param name: The name of the schema.
    :type name: RequiredStr
    :param service_id: The foreign key referencing the service to which the schema
        belongs.
    :type service_id: int
    """

    name: RequiredStr
    service_id: int = SQLField(foreign_key="service.id", index=True, ondelete="CASCADE")


class Schema(BaseSQLModel, SchemaBase, table=True):
    """Represent a database schema within a service.

    :param id: The primary key for the table. Auto-incremented and not nullable.
    :type id: int | None
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :type created_at: UTCDatetime
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :type updated_at: UTCDatetime | None
    :param name: The name of the schema. Must be unique for service_id, as defined by
        composite index ix_schema_name_service_id.
    :type name: RequiredStr
    :param service_id: The unique identifier of the service to which the schema belongs.
        Must be unique for name, as defined by composite index
        ix_schema_name_service_id.
    :type service_id: int
    :param service: The service to which the schema is associated.
    :type service: Service
    :param tables: A list of tables within the schema.
    :type tables: list[Table]
    """

    __table_args__ = (
        Index("ix_schema_name_service_id", "name", "service_id", unique=True),
    )
    service: Service = Relationship(back_populates="schemas")
    tables: list["Table"] = Relationship(back_populates="database", cascade_delete=True)


class SchemaWrite(SchemaBase):
    """Define the model for writing schema data to the inventory.

    :param name: The name of the schema.
    :type name: RequiredStr
    :param service_id: The foreign key referencing the service to which the schema
        belongs. Defaults to None.
    :type service_id: int | None
    """

    service_id: int | None = SQLField(
        default=None,
        foreign_key="service.id",
        index=True,
        ondelete="CASCADE",
    )


class SchemaResponse(BaseSQLModel, SchemaBase):
    """Define the schema API response.

    :param id: The primary key for the table. Auto-incremented and not nullable.
    :type id: int | None
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :type created_at: UTCDatetime
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :type updated_at: UTCDatetime | None
    :param name: The name of the schema.
    :type name: RequiredStr
    :param service_id: The unique identifier of the service to which the schema belongs.
    :type service_id: int
    :param tables: A list of tables within the schema.
    :type tables: list[Table]
    """

    tables: list["Table"]


class SchemaDetailResponse(SchemaResponse):
    """Define the schema retrieve API response.

    :param id: The primary key for the table. Auto-incremented and not nullable.
    :type id: int | None
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :type created_at: UTCDatetime
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :type updated_at: UTCDatetime | None
    :param name: The name of the schema.
    :type name: RequiredStr
    :param service_id: The unique identifier of the service to which the schema belongs.
    :type service_id: int
    :param service: The schema's service.
    :type service: Service
    """

    service: Service


class TableBase(SQLModel):
    """Define the base structure for table-related operations.

    :param name: The name of the table.
    :type name: RequiredStr
    :param create: The SQL statement used to create the table.
    :type create: RequiredStr
    :param schema_id: The foreign key referencing the schema to which the table belongs.
    :type schema_id: int
    :param keys: A dictionary containing details about table keys (e.g., primary,
        unique).
    :type keys: Dict[str, Any]
    """

    name: RequiredStr
    create: RequiredStr = SQLField(sa_type=Text)
    schema_id: int = SQLField(foreign_key="schema.id", index=True, ondelete="CASCADE")
    # TODO(yan): Make keys a Pydantic model
    # SEP-203
    keys: dict[str, Any] = SQLField(
        sa_column=Column(JSON, nullable=False),
    )


class Table(BaseSQLModel, TableBase, table=True):
    """Represent a table within a schema.

    :param id: The primary key for the table. Auto-incremented and not nullable.
    :type id: int | None
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :type created_at: UTCDatetime
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :type updated_at: UTCDatetime | None
    :param name: The name of the table. Must be unique for schema_id, as defined by
        composite index ix_table_name_schema_id.
    :type name: RequiredStr
    :param create: The SQL statement used to create the table.
    :type create: RequiredStr
    :param schema_id: The unique identifier of the schema to which the table belongs.
        Must be unique for name, as defined by composite index ix_table_name_schema_id.
    :type schema_id: int
    :param database: The schema to which the table is associated.
    :type database: Schema
    """

    __table_args__ = (
        Index("ix_table_name_schema_id", "name", "schema_id", unique=True),
    )
    database: Schema = Relationship(back_populates="tables")


class TableWrite(TableBase):
    """Define the model for writing table data to the inventory.

    :param name: The name of the table.
    :type name: RequiredStr
    :param create: The SQL statement used to create the table.
    :type create: RequiredStr
    :param schema_id: The foreign key referencing the schema to which the table belongs.
    :type schema_id: int | None
    """

    schema_id: int | None = SQLField(
        default=None,
        foreign_key="schema.id",
        index=True,
        ondelete="CASCADE",
    )


class TableResponse(BaseSQLModel, TableBase):
    """Define the table API response.

    :param id: The primary key for the table. Auto-incremented and not nullable.
    :type id: int | None
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :type created_at: UTCDatetime
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :type updated_at: UTCDatetime | None
    :param name: The name of the table.
    :type name: RequiredStr
    :param create: The SQL statement used to create the table.
    :type create: RequiredStr
    :param schema_id: The foreign key referencing the schema to which the table belongs.
    :type schema_id: int
    """


class TableDetailResponse(TableResponse):
    """Define the schema retrieve API response.

    :param id: The primary key for the table. Auto-incremented and not nullable.
    :type id: int | None
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :type created_at: UTCDatetime
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :type updated_at: UTCDatetime | None
    :param name: The name of the table.
    :type name: RequiredStr
    :param create: The SQL statement used to create the table.
    :type create: RequiredStr
    :param schema_id: The foreign key referencing the schema to which the table belongs.
    :type schema_id: int
    :param database: The table's schema.
    :type database: Schema
    """

    database: Schema
