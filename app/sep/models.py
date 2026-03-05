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

"""Define models for the SEP app."""

from enum import auto, IntEnum, StrEnum
from typing import Self

from pydantic import (
    model_validator,
    UUID4,
)
from sqlalchemy import Column, Index
from sqlalchemy import Enum as EnumField
from sqlmodel import Field as SQLField
from sqlmodel import Relationship, SQLModel

from app.core.db.models import BaseUUIDSQLModel
from app.core.utils.fields import NonEmptyStr


class SyncInventoryEntityTypeEnum(IntEnum):
    """Enumerate the types of inventory entities that can be synchronized.

    :cvar INVENTORY: Represents the entire inventory.
    :vartype INVENTORY: int
    :cvar NODE: Represents a node within the inventory.
    :vartype NODE: int
    :cvar SERVICE: Represents a service within a node.
    :vartype SERVICE: int
    :cvar SCHEMA: Represents a schema within a service.
    :vartype SCHEMA: int
    :cvar TABLE: Represents a table within a schema.
    :vartype TABLE: int
    """

    INVENTORY = auto()
    NODE = auto()
    SERVICE = auto()
    SCHEMA = auto()
    TABLE = auto()


class SyncStatusEnum(StrEnum):
    """Enumerate the possible statuses of a synchronization process.

    :cvar PENDING: The synchronization is pending.
    :vartype PENDING: str
    :cvar RUNNING: The synchronization is currently running.
    :vartype RUNNING: str
    :cvar SUCCESS: The synchronization completed successfully.
    :vartype SUCCESS: str
    :cvar FAILED: The synchronization failed.
    :vartype FAILED: str
    """

    PENDING = auto()
    RUNNING = auto()
    SUCCESS = auto()
    FAILED = auto()


class SyncInstanceBase(SQLModel):
    """Define the base structure for a synchronization instance.

    This model provides the foundational fields required for tracking a synchronization
    instance, including the synchronizer responsible for the synchronization.

    :param syncer: The name of the synchronizer responsible for this synchronization.
        Indexed for quick lookup.
    :type syncer: NonEmptyStr
    """

    syncer: NonEmptyStr = SQLField(index=True)


class SyncInstance(BaseUUIDSQLModel, SyncInstanceBase, table=True):
    """Represent a synchronization instance in the SEP app.

    This model represents an instance of a synchronization process, tracking its
    inventory item, type, associated task history, synchronizer, and current status.

    :param id: The primary key for the table. Automatically generated using UUID4.
    :type id: UUID4
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :type created_at: UTCDatetime
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :type updated_at: UTCDatetime | None
    :param syncer: The name of the synchronizer responsible for this synchronization.
        Indexed for quick lookup.
    :type syncer: NonEmptyStr
    :param items: A list of synchronization items associated with this synchronization
        instance.
    :type items: list[SyncItem]
    """

    items: list["SyncItem"] = Relationship(
        back_populates="sync_instance",
        cascade_delete=True,
    )


class SyncInstanceWrite(SyncInstanceBase):
    """Define the write model for creating a synchronization instance.

    This model extends `SyncInstanceBase` and is used specifically for creating
    new synchronization instances.

    :param syncer: The name of the synchronizer responsible for this synchronization.
        Indexed for quick lookup.
    :type syncer: NonEmptyStr
    """


class SyncItemBase(SQLModel):
    """Define the base structure for a synchronization item.

    This model provides the foundational fields required for tracking individual
    synchronization items, including the associated inventory item and synchronization
    status.

    :param entity_id: The identifier of the inventory item being synchronized.
    :type entity_id: int | None
    :param entity_type: The type of the inventory item being synchronized.
    :type entity_type: SyncInventoryEntityTypeEnum
    :param status: The current status of the synchronization process. Defaults to
        PENDING.
    :type status: SyncStatusEnum
    :param sync_instance_id: The foreign key referencing the associated synchronization
        instance.
    :type sync_instance_id: UUID4
    """

    entity_id: int | None = SQLField(index=True)
    entity_type: SyncInventoryEntityTypeEnum = SQLField(
        sa_column=Column(
            EnumField(SyncInventoryEntityTypeEnum),
            nullable=False,
            index=True,
        ),
    )
    status: SyncStatusEnum = SQLField(
        default=SyncStatusEnum.PENDING,
        sa_column=Column(EnumField(SyncStatusEnum), nullable=False, index=True),
    )
    sync_instance_id: UUID4 = SQLField(
        foreign_key="syncinstance.id",
        index=True,
        ondelete="CASCADE",
    )


class SyncItem(BaseUUIDSQLModel, SyncItemBase, table=True):
    """Represent a synchronization item.

    This model represents an individual synchronization task within a synchronization
    instance, tracking its inventory item, type, status, and associated task history.

    :param id: The primary key for the table. Automatically generated using UUID4.
    :type id: UUID4
    :param created_at: The timestamp when the record is created. Defaults to the current
        time in UTC.
    :type created_at: UTCDatetime
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :type updated_at: UTCDatetime | None
    :param entity_id: The identifier of the inventory item being synchronized.
    :type entity_id: int | None
    :param entity_type: The type of the inventory item being synchronized.
    :type entity_type: SyncInventoryEntityTypeEnum
    :param status: The current status of the synchronization process.
    :type status: SyncStatusEnum
    :param sync_instance_id: The foreign key referencing the associated synchronization
        instance.
    :type sync_instance_id: UUID4
    :param sync_instance: The synchronization instance to which this item belongs.
    :type sync_instance: SyncInstance
    """

    __table_args__ = (
        Index(
            "ix_syncitem_entity_id_entity_type_status",
            "entity_id",
            "entity_type",
            "status",
        ),
        Index("ix_syncitem_entity_type_status", "entity_type", "status"),
    )
    sync_instance: SyncInstance = Relationship(back_populates="items")

    @model_validator(mode="after")
    def _validate_entity_id_not_null(self) -> Self:
        if (
            self.entity_id is None
            and self.entity_type != SyncInventoryEntityTypeEnum.INVENTORY
        ):
            raise ValueError(
                f"entity_id cannot be None for type {self.entity_type}",
            )
        return self


class SyncItemWrite(SyncItemBase):
    """Define the write model for creating a synchronization item.

    This model extends `SyncItemBase` and is used specifically for creating
    new synchronization items.

    :param entity_id: The identifier of the inventory item being synchronized.
    :type entity_id: int | None
    :param entity_type: The type of the inventory item being synchronized.
    :type entity_type: SyncInventoryEntityTypeEnum
    :param status: The current status of the synchronization process. Defaults to
        PENDING.
    :type status: SyncStatusEnum
    :param sync_instance_id: The foreign key referencing the associated synchronization
        instance.
    :type sync_instance_id: UUID4
    """
