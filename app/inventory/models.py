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

"""Define models for the Inventory API."""

from enum import auto, StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, model_validator, PositiveInt
from sqlalchemy import Column, Index, JSON, Text, text
from sqlalchemy import Enum as EnumField
from sqlmodel import Field as SQLField
from sqlmodel import Relationship, SQLModel

from app.core.db import BaseSQLModel
from app.core.db.models import DateTimeWithTimezone
from app.core.utils.fields import ArbitraryMapping, NonEmptyStr, UTCDatetime
from app.inventory.constants import ACTIVE_RETIREMENT_KEY, RetirableEntityName

#: Predicate narrowing the collection-scan indexes to the tombstones alone.
#: Active rows are the overwhelming majority and can never be returned by that
#: scan, so keeping them out holds the index size to the retired set.
RETIRED_ROWS_ONLY = text("retired_at IS NOT NULL")


class RetiredAtBase(SQLModel):
    """Expose the retirement timestamp of an entity that can be tombstoned.

    :param retired_at: When the entity stopped being reported by its upstream
        source, or None while it is active.
    """

    retired_at: UTCDatetime | None = SQLField(
        default=None, sa_type=DateTimeWithTimezone
    )


class RetirableSQLModel(RetiredAtBase, BaseSQLModel):
    """Store the retirement state of a tombstoned entity.

    An entity that vanishes upstream is retired rather than deleted, so the
    references SEP persisted to it keep resolving. Because a replacement may
    reuse the retired row's unique key, ``retirement_key`` joins every unique
    index: it holds :data:`ACTIVE_RETIREMENT_KEY` while the row is active and
    the row's own primary key once retired, which keeps active rows mutually
    exclusive while letting any number of tombstones share their key.

    :param retired_at: When the entity stopped being reported by its upstream
        source, or None while it is active.
    :param retirement_key: The discriminator carried inside every unique index.
        Excluded from serialization: the responses nest these table models, and a
        database-internal discriminator has no business in the published schema.
    """

    retirement_key: int = SQLField(
        default=ACTIVE_RETIREMENT_KEY, nullable=False, exclude=True
    )


class SourceEnum(StrEnum):
    """Enumeration of possible data sources for a node.

    :cvar PMM: Represents the PMM data source.
    :vartype PMM: str
    """

    PMM = auto()


class ServiceTypeEnum(StrEnum):
    """Enumerate the supported service types.

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
    :cvar VALKEY: Represents the Valkey service type.
    :vartype VALKEY: str
    """

    MYSQL = auto()
    POSTGRESQL = auto()
    MONGODB = auto()
    PROXYSQL = auto()
    HAPROXY = auto()
    EXTERNAL = auto()
    VALKEY = auto()


class NodeBase(SQLModel):
    """Define the base structure for node-related operations.

    :param address: The network address of the node.
    :type address: NonEmptyStr
    :param name: The name of the node.
    :type name: NonEmptyStr
    :param external_id: An external identifier for the node, indexed for quick lookup.
        Defaults to None.
    :type external_id: NonEmptyStr | None
    :param source: The source from which the node information is derived. Indexed for
        quick lookup. Defaults to None.
    :type source: SourceEnum | None
    :param type: The type of the node (e.g., remote, generic). Defaults to "generic".
    :type type: NonEmptyStr
    """

    address: NonEmptyStr
    name: NonEmptyStr
    external_id: NonEmptyStr | None = SQLField(default=None, index=True)
    source: SourceEnum | None = SQLField(
        default=None,
        sa_column=Column(EnumField(SourceEnum)),
    )
    type: NonEmptyStr = SQLField(
        default="generic"
    )  # TODO: Enum with allowed values  # noqa: TD002, TD003

    @model_validator(mode="after")
    def validate_external_id_source(self) -> Self:
        """Ensure that external_id is set only if source is provided.

        Raises
        ------
        ValueError
            If ``external_id`` is provided without a corresponding ``source``.

        :return: The validated instance.
        :rtype: Self

        """
        if self.external_id is not None and self.source is None:
            raise ValueError("Can't set external_id if source is None")
        return self


class Node(NodeBase, RetirableSQLModel, table=True):
    """Represent a node in the inventory.

    :param address: The network address of the node.
    :param name: The name of the node.
    :param external_id: An external identifier for the node. Must be unique for source,
        as defined by composite index ix_node_external_id_source.
    :param source: The source from which the node information is derived. Must be unique
        for external_id, as defined by composite index ix_node_external_id_source.
    :param type: The type of the node (e.g., remote, generic).
    :param retired_at: When the node stopped being reported upstream, or None while
        it is active.
    :param retirement_key: The discriminator carried inside every unique index.
    :param services: A list of services associated with the node.
    """

    __table_args__ = (
        Index(
            "ix_node_external_id_source",
            "external_id",
            "source",
            "retirement_key",
            unique=True,
        ),
        Index(
            "ix_node_retired_at_not_null",
            "retired_at",
            postgresql_where=RETIRED_ROWS_ONLY,
            sqlite_where=RETIRED_ROWS_ONLY,
        ),
    )
    services: list["Service"] = Relationship(back_populates="node", cascade_delete=True)


class NodeWrite(NodeBase):
    """Define the model for writing node data to the inventory.

    :param address: The network address of the node.
    :param name: The name of the node.
    :param external_id: An external identifier for the node, indexed for quick lookup.
        Defaults to None.
    :param source: The source from which the node information is derived. Indexed for
        quick lookup. Defaults to None.
    :param type: The type of the node (e.g., remote, generic). Defaults to "generic".
    """


class NodeResponse(BaseSQLModel, RetiredAtBase, NodeBase):
    """Represent a node API response.

    :param id: The primary key for the table. Auto-incremented and not nullable.
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :param address: The network address of the node.
    :param name: The name of the node.
    :param external_id: An external identifier for the node.
    :param source: The source from which the node information is derived.
    :param type: The type of the node (e.g., remote, generic).
    :param retired_at: When the node stopped being reported upstream, or None while
        it is active.
    :param services: A list of services associated with the node.
    """

    services: list["Service"]


class ServiceBase(SQLModel):
    """Define the base structure for service-related operations.

    :param external_id: An external identifier for the service, indexed for quick
        lookup. Defaults to None.
    :param name: The name of the service.
    :param type: The type of the service (e.g., MYSQL, POSTGRESQL).
    :param port: The port number on which the service is running. Defaults to None.
    :param environment: The environment in which the service is running (e.g.,
        production, staging). Defaults to None.
    :param cluster: The cluster in which the service is running. Defaults to None.
    :param replication_set: The replication set in which the service is running. Defaults to None.
    :param custom_labels: Custom labels associated with the service. Defaults to None.
    :param node_id: The foreign key referencing the node to which the service belongs.
    """

    external_id: NonEmptyStr | None = SQLField(
        default=None,
        index=True,
    )  # TODO: validate external_id not null if node source is defined  # noqa: TD002, TD003
    name: NonEmptyStr
    type: ServiceTypeEnum = SQLField(
        sa_column=Column(EnumField(ServiceTypeEnum, native_enum=False), nullable=False),
    )
    port: int | None = None
    environment: str | None = (
        None  # TODO: Enum with allowed values  # noqa: TD002, TD003
    )
    cluster: str | None = None
    replication_set: str | None = None
    custom_labels: ArbitraryMapping | None = SQLField(
        default=None,
        sa_column=Column(JSON),
    )
    node_id: int = SQLField(foreign_key="node.id", index=True, ondelete="CASCADE")


class ServiceWrite(ServiceBase):
    """Define the model for writing service data to the inventory.

    :param external_id: An external identifier for the service, indexed for quick
        lookup. Defaults to None.
    :type external_id: NonEmptyStr | None
    :param name: The name of the service.
    :type name: NonEmptyStr
    :param type: The type of the service (e.g., MYSQL, POSTGRESQL).
    :type type: ServiceTypeEnum
    :param port: The port number on which the service is running. Defaults to None.
    :type port: int | None
    :param environment: The environment in which the service is running (e.g.,
        production, staging). Defaults to None.
    :type environment: str | None
    :param cluster: The cluster in which the service is running. Defaults to None.
    :type cluster: str | None
    :param replication_set: The replication set in which the service is running. Defaults to None.
    :type replication_set: str | None
    :param custom_labels: Custom labels associated with the service. Defaults to None.
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


class Service(RetirableSQLModel, ServiceBase, table=True):
    """Represent a service running on a node in the inventory.

    :param id: The primary key for the table. Auto-incremented and not nullable.
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :param external_id: An external identifier for the service. Must be unique for
        node_id, as defined by composite index ix_service_external_id_node_id.
    :param name: The name of the service.
    :param type: The type of the service (e.g., MYSQL, POSTGRESQL).
    :param port: The port number on which the service is running. Must be unique for
        node_id, as defined by composite index ix_service_port_node_id.
    :param environment: The environment in which the service is running, if set.
    :param cluster: The cluster in which the service is running, if set.
    :param replication_set: The replication set in which the service is running, if set.
    :param custom_labels: Custom labels associated with the service, if set.
    :param node_id: The unique identifier of the node on which the service is running.
        Must be unique for external_id, as defined by composite index
        ix_service_external_id_node_id, and for port, as defined by composite index
        ix_service_port_node_id.
    :param node: The node to which the service is associated.
    :param retired_at: When the service stopped being reported upstream, or None
        while it is active.
    :param retirement_key: The discriminator carried inside every unique index.
    :param schemas: A list of schemas associated with the service.
    """

    __table_args__ = (
        Index(
            "ix_service_external_id_node_id",
            "external_id",
            "node_id",
            "retirement_key",
            unique=True,
        ),
        Index(
            "ix_service_port_node_id",
            "port",
            "node_id",
            "retirement_key",
            unique=True,
        ),
        Index(
            "ix_service_retired_at_not_null",
            "retired_at",
            postgresql_where=RETIRED_ROWS_ONLY,
            sqlite_where=RETIRED_ROWS_ONLY,
        ),
    )

    node: Node = Relationship(back_populates="services")
    schemas: list["Schema"] = Relationship(
        back_populates="service",
        cascade_delete=True,
    )


class ServiceResponse(BaseSQLModel, RetiredAtBase, ServiceBase):
    """Define the service API response.

    :param id: The primary key for the table. Auto-incremented and not nullable.
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :param external_id: An external identifier for the service.
    :param name: The name of the service.
    :param type: The type of the service (e.g., MYSQL, POSTGRESQL).
    :param port: The port number on which the service is running.
    :param environment: The environment in which the service is running, if set.
    :param cluster: The cluster in which the service is running, if set.
    :param replication_set: The replication set in which the service is running, if set.
    :param custom_labels: Custom labels associated with the service, if set.
    :param node_id: The unique identifier of the node on which the service is running.
    :param schemas: A list of schemas associated with the service.
    :param node: The node to which the service is associated.
    :param retired_at: When the service stopped being reported upstream, or None
        while it is active.
    """

    schemas: list["Schema"]
    node: Node


class ServiceDetailResponse(ServiceResponse):
    """Define the service retrieve API response.

    :param id: The primary key for the table. Auto-incremented and not nullable.
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :param external_id: An external identifier for the service.
    :param name: The name of the service.
    :param type: The type of the service (e.g., MYSQL, POSTGRESQL).
    :param port: The port number on which the service is running.
    :param environment: The environment in which the service is running, if set.
    :param cluster: The cluster in which the service is running, if set.
    :param replication_set: The replication set in which the service is running, if set.
    :param custom_labels: Custom labels associated with the service, if set.
    :param node_id: The unique identifier of the node on which the service is running.
    :param schemas: A list of schemas associated with the service.
    :param node: The service's node.
    """

    node: Node


class SchemaBase(SQLModel):
    """Define the base structure for schema-related operations.

    :param name: The name of the schema.
    :param service_id: The foreign key referencing the service to which the schema
        belongs.
    """

    name: NonEmptyStr
    service_id: int = SQLField(foreign_key="service.id", index=True, ondelete="CASCADE")


class Schema(RetirableSQLModel, SchemaBase, table=True):
    """Represent a database schema within a service.

    :param id: The primary key for the table. Auto-incremented and not nullable.
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :param name: The name of the schema. Must be unique for service_id, as defined by
        composite index ix_schema_name_service_id.
    :param service_id: The unique identifier of the service to which the schema belongs.
        Must be unique for name, as defined by composite index
        ix_schema_name_service_id.
    :param service: The service to which the schema is associated.
    :param retired_at: When the schema stopped being reported upstream, or None
        while it is active.
    :param retirement_key: The discriminator carried inside every unique index.
    :param tables: A list of tables within the schema.
    """

    __table_args__ = (
        Index(
            "ix_schema_name_service_id",
            "name",
            "service_id",
            "retirement_key",
            unique=True,
        ),
        Index(
            "ix_schema_retired_at_not_null",
            "retired_at",
            postgresql_where=RETIRED_ROWS_ONLY,
            sqlite_where=RETIRED_ROWS_ONLY,
        ),
    )
    service: Service = Relationship(back_populates="schemas")
    tables: list["Table"] = Relationship(back_populates="database", cascade_delete=True)


class SchemaWrite(SchemaBase):
    """Define the model for writing schema data to the inventory.

    :param name: The name of the schema.
    :type name: NonEmptyStr
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


class SchemaCompactResponse(BaseSQLModel, RetiredAtBase, SchemaBase):
    """Define a compact schema response without nested tables.

    :param id: The primary key for the schema. Auto-incremented and not nullable.
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :param name: The name of the schema.
    :param service_id: The unique identifier of the service to which the schema belongs.
    :param retired_at: When the schema stopped being reported upstream, or None while
        it is active.
    """


class SchemaResponse(BaseSQLModel, RetiredAtBase, SchemaBase):
    """Define the schema API response.

    :param id: The primary key for the schema. Auto-incremented and not nullable.
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :param name: The name of the schema.
    :param service_id: The unique identifier of the service to which the schema belongs.
    :param retired_at: When the schema stopped being reported upstream, or None while
        it is active.
    :param tables: A list of tables within the schema.
    """

    tables: list["Table"]


class SchemaDetailResponse(SchemaResponse):
    """Define the schema retrieve API response.

    :param id: The primary key for the table. Auto-incremented and not nullable.
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :param name: The name of the schema.
    :param service_id: The unique identifier of the service to which the schema belongs.
    :param service: The schema's service.
    """

    service: Service


class TableBase(SQLModel):
    """Define the base structure for table-related operations.

    :param name: The name of the table.
    :param create: The SQL statement used to create the table.
    :param schema_id: The foreign key referencing the schema to which the table belongs.
    :param keys: A dictionary containing details about table keys (e.g., primary,
        unique).
    """

    name: NonEmptyStr
    create: NonEmptyStr = SQLField(sa_type=Text)
    schema_id: int = SQLField(foreign_key="schema.id", index=True, ondelete="CASCADE")
    keys: dict[str, Any] = SQLField(
        sa_column=Column(JSON, nullable=False),
        schema_extra={"json_schema_extra": {"additionalProperties": True}},
    )


class Table(RetirableSQLModel, TableBase, table=True):
    """Represent a table within a schema.

    :param id: The primary key for the table. Auto-incremented and not nullable.
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :param name: The name of the table. Must be unique for schema_id, as defined by
        composite index ix_table_name_schema_id.
    :param create: The SQL statement used to create the table.
    :param schema_id: The unique identifier of the schema to which the table belongs.
        Must be unique for name, as defined by composite index ix_table_name_schema_id.
    :param retired_at: When the table stopped being reported upstream, or None while
        it is active.
    :param retirement_key: The discriminator carried inside every unique index.
    :param database: The schema to which the table is associated.
    """

    __table_args__ = (
        Index(
            "ix_table_name_schema_id",
            "name",
            "schema_id",
            "retirement_key",
            unique=True,
        ),
        Index(
            "ix_table_retired_at_not_null",
            "retired_at",
            postgresql_where=RETIRED_ROWS_ONLY,
            sqlite_where=RETIRED_ROWS_ONLY,
        ),
    )
    database: Schema = Relationship(back_populates="tables")


class TableWrite(TableBase):
    """Define the model for writing table data to the inventory.

    :param name: The name of the table.
    :param create: The SQL statement used to create the table.
    :param schema_id: The foreign key referencing the schema to which the table belongs.
    """

    schema_id: int | None = SQLField(
        default=None,
        foreign_key="schema.id",
        index=True,
        ondelete="CASCADE",
    )


class TableResponse(BaseSQLModel, RetiredAtBase, TableBase):
    """Define the table API response.

    :param id: The primary key for the table. Auto-incremented and not nullable.
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :param name: The name of the table.
    :param create: The SQL statement used to create the table.
    :param schema_id: The foreign key referencing the schema to which the table belongs.
    :param retired_at: When the table stopped being reported upstream, or None while
        it is active.
    """


class TableDetailResponse(TableResponse):
    """Define the schema retrieve API response.

    :param id: The primary key for the table. Auto-incremented and not nullable.
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :param name: The name of the table.
    :param create: The SQL statement used to create the table.
    :param schema_id: The foreign key referencing the schema to which the table belongs.
    :param database: The table's schema.
    """

    database: Schema


class HostSystemObservationBase(SQLModel):
    """Define the base structure for host-level system observation data.

    :param node_id: The foreign key referencing the node this observation belongs to.
    :param os_version: The observed operating system version. Defaults to None.
    :param installed_packages: Snapshot of installed packages. Defaults to None.
    :param config: Snapshot of host configuration. Defaults to None.
    :param observed_at: When this observation was collected (domain provenance).
    """

    node_id: int = SQLField(
        foreign_key="node.id",
        unique=True,
        index=True,
        ondelete="CASCADE",
    )
    os_version: str | None = None
    installed_packages: list[ArbitraryMapping] | None = SQLField(
        default=None,
        sa_column=Column(JSON),
    )
    config: ArbitraryMapping | None = SQLField(
        default=None,
        sa_column=Column(JSON),
    )
    observed_at: UTCDatetime

    @model_validator(mode="after")
    def validate_at_least_one_observation_field(self) -> Self:
        """Ensure that at least one of os_version, installed_packages, or config is set.

        Validates that at least one of ``os_version``, ``installed_packages``, or
        ``config`` is provided.

        :return: The validated instance.
        :raises ValueError: If ``os_version``, ``installed_packages``, and ``config``
            are all unset.
        """
        if (
            self.os_version is None
            and self.installed_packages is None
            and self.config is None
        ):
            raise ValueError(
                "At least one of os_version, installed_packages, or config must be set",
            )
        return self


class HostSystemObservation(BaseSQLModel, HostSystemObservationBase, table=True):
    """Store host-level system facts for a node (one snapshot per node).

    :param id: The primary key for the table. Auto-incremented and not nullable.
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :param node_id: The unique identifier of the observed node. At most one observation
        row per node.
    :param os_version: The observed operating system version, if set.
    :param installed_packages: Snapshot of installed packages, if set.
    :param config: Snapshot of host configuration, if set.
    :param observed_at: When this observation was collected.
    """


class HostSystemObservationWrite(HostSystemObservationBase):
    """Define the model for writing host system observation data to the inventory.

    :param node_id: The foreign key referencing the node. Defaults to None.
    :type node_id: int | None
    :param os_version: The observed operating system version. Defaults to None.
    :type os_version: str | None
    :param installed_packages: Snapshot of installed packages. Defaults to None.
    :param config: Snapshot of host configuration. Defaults to None.
    :param observed_at: When this observation was collected.
    :type observed_at: UTCDatetime
    """

    node_id: int | None = SQLField(
        default=None,
        foreign_key="node.id",
        index=True,
        ondelete="CASCADE",
    )


class ServiceSystemObservationBase(SQLModel):
    """Define the base structure for service-level system observation data.

    :param service_id: The foreign key referencing the service this observation belongs
        to.
    :param db_engine_version: The observed database engine version.
    :param observed_at: When this observation was collected (domain provenance).
    """

    service_id: int = SQLField(
        foreign_key="service.id",
        unique=True,
        index=True,
        ondelete="CASCADE",
    )
    db_engine_version: NonEmptyStr
    observed_at: UTCDatetime


class ServiceSystemObservation(BaseSQLModel, ServiceSystemObservationBase, table=True):
    """Store service-level system facts (one snapshot per service).

    :param id: The primary key for the table. Auto-incremented and not nullable.
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :param service_id: The unique identifier of the observed service. At most one
        observation row per service.
    :param db_engine_version: The observed database engine version.
    :param observed_at: When this observation was collected.
    """


class ServiceSystemObservationWrite(ServiceSystemObservationBase):
    """Define the model for writing service system observation data to the inventory.

    :param service_id: The foreign key referencing the service. Defaults to None.
    :type service_id: int | None
    :param db_engine_version: The observed database engine version.
    :type db_engine_version: NonEmptyStr
    :param observed_at: When this observation was collected.
    :type observed_at: UTCDatetime
    """

    service_id: int | None = SQLField(
        default=None,
        foreign_key="service.id",
        index=True,
        ondelete="CASCADE",
    )


class HostSystemObservationResponse(BaseSQLModel, HostSystemObservationBase):
    """Define the response model for host system observation data.

    :param id: The primary key of the observation record.
    :type id: int | None
    :param created_at: When the record was created.
    :type created_at: UTCDatetime
    :param updated_at: When the record was last updated.
    :type updated_at: UTCDatetime | None
    :param node_id: The unique identifier of the observed node.
    :type node_id: int
    :param os_version: The observed operating system version.
    :type os_version: str | None
    :param installed_packages: Snapshot of installed packages.
    :param config: Snapshot of host configuration.
    :param observed_at: When this observation was collected.
    :type observed_at: UTCDatetime
    """


class ServiceSystemObservationResponse(BaseSQLModel, ServiceSystemObservationBase):
    """Define the response model for service system observation data.

    :param id: The primary key of the observation record.
    :type id: int | None
    :param created_at: When the record was created.
    :type created_at: UTCDatetime
    :param updated_at: When the record was last updated.
    :type updated_at: UTCDatetime | None
    :param service_id: The unique identifier of the observed service.
    :type service_id: int
    :param db_engine_version: The observed database engine version.
    :type db_engine_version: NonEmptyStr
    :param observed_at: When this observation was collected.
    :type observed_at: UTCDatetime
    """


class InventoryCollectWrite(BaseModel):
    """Ask the inventory service to collect the tombstones nothing resolves.

    Unknown fields are rejected with HTTP 422. This request deletes rows
    irreversibly, so a client typo must never be read as an omitted field: a
    misspelled ``keep`` would otherwise arrive as an empty retained set and a
    misspelled ``dry_run`` as a real delete.

    :param retired_before: The cutoff a tombstone must predate to be eligible.
        The caller pins one value for a whole run so successive batches cannot
        drift into collecting a tombstone that was too young a moment earlier.
    :param keep: The ids the caller knows are still referenced, per entity type.
        Ancestors of a kept entity are retained without being listed.
    :param limit: The most entities to collect per type in this call.
    :param dry_run: Whether to report the eligible ids without deleting them.
        Defaults to reporting: on an irreversible endpoint the mode a caller
        reaches by omission is the one that cannot destroy anything.
    """

    model_config = ConfigDict(extra="forbid")
    retired_before: UTCDatetime
    keep: dict[RetirableEntityName, list[int]] = {}
    limit: PositiveInt = 500
    dry_run: bool = True


class InventoryCollectResponse(BaseModel):
    """Report what a collection call deleted, or would have deleted.

    :param deleted: The collected ids per entity type, exhaustive for this
        call. On a dry run these are the ids the equivalent real call would
        delete. A type the walk stopped before reporting is empty rather than
        absent.
    :param remaining: Whether any entity type filled its ``limit``, meaning more
        tombstones are waiting for the next batch.
    """

    deleted: dict[RetirableEntityName, list[int]]
    remaining: bool
