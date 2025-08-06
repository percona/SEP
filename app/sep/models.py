# Copyright (C) 2025 Percona LLC
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

import hashlib
from enum import auto, IntEnum, StrEnum
from os import PathLike
from pathlib import Path
from typing import Any, Self

import aiofiles
import yaml
from aiofiles.ospath import getsize
from pydantic import (
    computed_field,
    model_validator,
    PositiveInt,
    UUID4,
)
from sqlalchemy import Column, Index, JSON
from sqlalchemy import Enum as EnumField
from sqlmodel import Field as SQLField
from sqlmodel import Relationship, SQLModel

from app.core.db import BaseSQLModel
from app.core.db.models import BaseUUIDSQLModel, DateTimeWithTimezone
from app.core.utils import utc_now
from app.core.utils.fields import RequiredStr, UTCDatetime
from app.sep.config import sep_settings


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
    :type syncer: RequiredStr
    """

    syncer: RequiredStr = SQLField(index=True)


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
    :type syncer: RequiredStr
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
    :type syncer: RequiredStr
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


class Snippet(BaseSQLModel, table=True):
    """Represent a support snippet stored in the database.

    :param filename: The snippet filename. Must be unique.
    :type filename: str
    :param md5_digest: The MD5 hash digest of the snippet file.
    :type md5_digest: str
    :param approved_at: The approval time for the snippet, or None if the snippet is not
        approved.
    :type approved_at: UTCDatetime | None
    :param reason: The reason for the approval or disapproval of the snippet, if any.
        Defaults to "New snippet".
    :type reason: str
    :param meta: Additional metadata about the snippet, such as title, description,
        parameters, etc.
    :type meta: dict[str, Any]
    """

    filename: str = SQLField(min_length=1, max_length=255, unique=True, index=True)
    size: PositiveInt
    md5_digest: str = SQLField(min_length=32, max_length=32)
    approved_at: UTCDatetime | None = SQLField(
        sa_type=DateTimeWithTimezone,
        default=None,
        index=True,
    )
    reason: str = "New snippet"
    meta: dict[str, Any] = SQLField(
        sa_column=Column(JSON, nullable=False),
        default_factory=dict,
    )

    def __repr__(self) -> str:
        return f"'{self.filename}' ({self.md5_digest})"

    def __str__(self) -> str:
        return self.filename

    def __hash__(self) -> int:
        return hash((self.filename, self.md5_digest))

    def __fspath__(self) -> str:
        return str(sep_settings.SNIPPETS.SNIPPETS_DIR / self.filename)

    @computed_field
    @property
    def is_approved(self) -> bool:
        """Determine whether the snippet has been approved.

        :return: True if the snippet is approved (i.e. approved_at is not None), else
            False.
        :rtype: bool
        """
        return self.approved_at is not None

    @staticmethod
    async def get_meta_by_path(path: PathLike) -> dict[str, Any]:
        """Extract metadata from a snippet file.

        This method reads the first few lines of the file and extracts metadata
        according to the specified patterns. It returns a dictionary with the
        extracted metadata.

        :param path: The path to the snippet file.
        :type path: PathLike
        :return: A dictionary containing the extracted metadata.
        :rtype: dict[str, Any]
        """
        try:
            async with aiofiles.open(path) as f:
                line = await f.readline()
                front_matter_lines = None
                while not sep_settings.SNIPPETS.META.STOP_SEARCH_PATTERN.match(line):
                    match = sep_settings.SNIPPETS.META.LINE_PATTERN.match(line)
                    if match:
                        content = match.groupdict().get("line", match.group(0))
                        if content == sep_settings.SNIPPETS.META.DELIMITER:
                            if front_matter_lines is not None:
                                break
                            front_matter_lines = []
                        elif front_matter_lines is not None:
                            front_matter_lines.append(content)
                    line = await f.readline()
            return (
                yaml.safe_load("\n".join(front_matter_lines))
                if front_matter_lines
                else {}
            )
        except UnicodeDecodeError:
            return {}

    @classmethod
    async def from_path(cls, path: PathLike) -> Self:
        """Create a new Snippet instance from a file path.

        This method computes the MD5 hash digest of the file at the specified path and
        instantiates a new Snippet with the filename and computed MD5 hash.

        :param path: A path-like object pointing to the snippet file.
        :type path: PathLike
        :return: A new instance of Snippet with the corresponding filename and
            md5_digest.
        :rtype: Snippet
        """
        path = sep_settings.SNIPPETS.SNIPPETS_DIR / Path(path)
        file_hash = hashlib.md5(usedforsecurity=False)
        chunk_size = 8192
        async with aiofiles.open(path, "rb") as f:
            while chunk := await f.read(chunk_size):
                file_hash.update(chunk)
        return cls(
            filename=path.name,
            md5_digest=file_hash.hexdigest(),
            size=await getsize(path),
        )

    def approve(self, reason: str) -> None:
        """Mark the snippet as approved.

        Set the snippet's approved_at to the current time and change the reason.

        :param reason: The reason for the approval of the snippet.
        :type reason: str
        """
        self.approved_at = utc_now()
        self.reason = reason

    def remove_approval(self, reason: str) -> None:
        """Mark the snippet as unapproved.

        Set the snippet's approved_at to None and change the reason.

        :param reason: The reason for the approval removal of the snippet.
        :type reason: str
        """
        self.approved_at = None
        self.reason = reason
