"""Define models for the SEP app."""

from enum import auto
from enum import IntEnum
from enum import StrEnum
from typing import Any
from typing import Self

from pydantic import computed_field
from pydantic import field_validator
from pydantic import HttpUrl
from pydantic import model_validator
from pydantic import UUID4
from sqlalchemy import Column
from sqlalchemy import Enum as EnumField
from sqlalchemy import Index
from sqlmodel import Field as SQLField
from sqlmodel import Relationship
from sqlmodel import SQLModel

from app.core.config import BaseCaseInsensitiveModel
from app.core.db.models import BaseUUIDSQLModel
from app.core.fields import RequiredStr
from app.core.fields import StrImportableModule
from app.core.fields import URIPath
from app.core.utils import slugify


class Plugin(BaseCaseInsensitiveModel):
    """Represent a SEP plugin.

    This model defines the structure for a plugin, including its name, module,
    URI path, and CSS class. It includes custom validators to resolve the module
    path and set default values based on the plugin's name.

    :param name: The name of the plugin.
    :type name: str
    :param module_name: The name of the module associated with the plugin. This field is
        automatically prefixed with "app.sep.plugins." during validation.
    :type module_name: StrImportableModule
    :param uri_path: The URI path where the plugin is accessible. Defaults to an empty
        string, but is automatically set to a slugified version of the plugin name if
        not provided.
    :type uri_path: HttpUrl | URIPath
    :param css_class: The CSS class associated with the plugin. Defaults to an empty
        string, but is automatically set to a slugified version of the plugin name if
        not provided.
    :type css_class: str
    """

    name: str
    module_name: StrImportableModule
    uri_path: HttpUrl | URIPath = ""
    css_class: str = ""

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Plugin):
            return self.module_name == other.module_name
        raise NotImplementedError

    @field_validator("module_name", mode="before")
    @classmethod
    def resolve_module_path(cls, v: str) -> str:
        """Resolve the full module path for the plugin.

        This method takes the module name provided and prefixes it with
        "app.sep.plugins." to resolve the full import path.

        :param v: The module name to resolve.
        :type v: str
        :return: The full module path with the "app.sep.plugins." prefix.
        :rtype: str
        """
        return f"app.sep.plugins.{v}"

    @model_validator(mode="before")
    @classmethod
    def _set_default_from_name(cls, data: Any) -> Any:
        if isinstance(data, dict) and (name := data.get("name")):
            slug = slugify(name)
            data["uri_path"] = data.get("uri_path") or f"/{slug}"
            data["css_class"] = data.get("css_class") or slug
        return data

    @computed_field
    @property
    def router_path(self) -> str:
        """Return the plugin's router path.

        :return: The router path derived from the module name.
        :rtype: str
        """
        return f"{self.module_name}.router"


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
    :type created_at: datetime
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :type updated_at: datetime | None
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
    :param task_history_id: The identifier of the task history associated with this
        synchronization instance. Defaults to None.
    :type task_history_id: int | None
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
    task_history_id: int | None = None
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
    :type created_at: datetime
    :param updated_at: The timestamp when the record is last updated. Automatically
        updated on changes.
    :type updated_at: datetime | None
    :param entity_id: The identifier of the inventory item being synchronized.
    :type entity_id: int | None
    :param entity_type: The type of the inventory item being synchronized.
    :type entity_type: SyncInventoryEntityTypeEnum
    :param status: The current status of the synchronization process.
    :type status: SyncStatusEnum
    :param task_history_id: The identifier of the task history associated with this
        synchronization instance.
    :type task_history_id: int | None
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
    :param task_history_id: The identifier of the task history associated with this
        synchronization instance. Defaults to None.
    :type task_history_id: int | None
    :param sync_instance_id: The foreign key referencing the associated synchronization
        instance.
    :type sync_instance_id: UUID4
    """
