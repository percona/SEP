"""Define models for the SEP app."""

from enum import auto
from enum import StrEnum
from typing import Any
from typing import Self

from pydantic import ConfigDict
from pydantic import field_validator
from pydantic import HttpUrl
from pydantic import model_validator
from sqlalchemy import Column
from sqlalchemy import Enum as EnumField
from sqlalchemy import Index
from sqlmodel import Field as SQLField

from app.core.config import BaseCaseInsensitiveModel
from app.core.db import BaseSQLModel
from app.core.fields import RequiredStr
from app.core.fields import StrImportableAttribute
from app.core.fields import StrImportableModule
from app.core.fields import URIPath
from app.core.utils import slugify


class Plugin(BaseCaseInsensitiveModel):
    """Represent a SEP plugin.

    This model defines the structure for a plugin, including its name, module,
    URI path, and CSS class. It includes custom validators to resolve the module
    path and set default values based on the plugin's name.

    Attributes
    ----------
    name : str
        The name of the plugin.
    module_name : StrImportableModule
        The name of the module associated with the plugin. This field is automatically
        prefixed with "app.sep.plugins." during validation.
    uri_path : HttpUrl or URIPath, optional
        The URI path where the plugin is accessible. Defaults to an empty string,
        but is automatically set to a slugified version of the plugin name if
        not provided.
    css_class : str, optional
        The CSS class associated with the plugin. Defaults to an empty string,
        but is automatically set to a slugified version of the plugin name if
        not provided.

    """

    model_config = ConfigDict(frozen=True)
    name: str
    module_name: StrImportableModule
    uri_path: HttpUrl | URIPath = ""
    css_class: str = ""

    def __hash__(self) -> int:
        return hash(self.module_name)

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

        Parameters
        ----------
        v : str
            The module name to resolve.

        Returns
        -------
        str
            The full module path with the "app.sep.plugins." prefix.

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


class Synchronizer(BaseCaseInsensitiveModel):
    """Represent a synchronizer for the SEP app.

    This model represents a synchronizer component within the SEP application,
    including its importable attribute and any additional keyword arguments required for
    its operation.

    Attributes
    ----------
    syncer : StrImportableAttribute
        The importable attribute name for the synchronizer. This field is automatically
        prefixed with "app.sep.sync.syncers." during validation.
    extra_kwargs : dict[str, Any]
        Additional keyword arguments to be passed in the syncer instantiation.

    """

    model_config = ConfigDict(frozen=True)
    syncer: StrImportableAttribute
    extra_kwargs: dict[str, Any]

    def __hash__(self) -> int:
        return hash(self.syncer)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Synchronizer):
            return self.syncer == other.syncer
        raise NotImplementedError

    @field_validator("syncer", mode="before")
    @classmethod
    def resolve_syncer_path(cls, v: str) -> str:
        """Resolve the full path for the syncer.

        Prefix the provided synchronizer name with "app.sep.sync.syncers." to form the
        complete import path.

        Parameters
        ----------
        v : str
            The base syncer name provided.

        Returns
        -------
        str
            The fully qualified path for the synchronizer.

        """
        return f"app.sep.sync.syncers.{v}"


class SyncInventoryTypeEnum(StrEnum):
    """Enumerate the types of inventory items that can be synchronized."""

    INVENTORY = auto()
    NODE = auto()
    SERVICE = auto()
    SCHEMA = auto()
    TABLE = auto()


class SyncStatusEnum(StrEnum):
    """Enumerate the possible statuses of a synchronization process."""

    PENDING = auto()
    RUNNING = auto()
    SUCCESS = auto()
    FAILED = auto()


class SyncInstance(BaseSQLModel, table=True):
    """Represent a synchronization instance in the SEP app.

    This model represents an instance of a synchronization process, tracking its
    inventory item, type, associated task history, synchronizer, and current status.

    Attributes
    ----------
    inventory_id : int or None
        The identifier of the inventory item being synchronized.
    inventory_type : SyncInventoryTypeEnum
        The type of the inventory item being synchronized.
    task_history_id : int or None, optional
        The identifier of the task history associated with this synchronization
        instance. Defaults to None
    syncer : RequiredStr
        The name of the synchronizer responsible for this synchronization.
    status : SyncStatusEnum, optional
        The current status of the synchronization process. Defaults to PENDING.

    """

    __table_args__ = (
        Index(
            "ix_syncinstance_inventory_id_inventory_type_status",
            "inventory_id",
            "inventory_type",
            "status",
        ),
        Index("ix_syncinstance_inventory_type_status", "inventory_type", "status"),
    )
    inventory_id: int | None = SQLField(index=True)
    inventory_type: SyncInventoryTypeEnum = SQLField(
        sa_column=Column(EnumField(SyncInventoryTypeEnum), nullable=False, index=True),
    )
    task_history_id: int | None = None
    syncer: RequiredStr = SQLField(index=True)
    status: SyncStatusEnum = SQLField(
        default=SyncStatusEnum.PENDING,
        sa_column=Column(EnumField(SyncInventoryTypeEnum), nullable=False, index=True),
    )

    @model_validator(mode="after")
    def _validate_inventory_id_not_null(self) -> Self:
        if (
            self.inventory_id is None
            and self.inventory_type != SyncInventoryTypeEnum.INVENTORY
        ):
            raise ValueError(
                f"inventory_id cannot be None for type {self.inventory_type}",
            )
        return self
