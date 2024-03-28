"""
Inventory API data models
"""

import json
from datetime import (
    datetime,
    timezone,
)
from enum import IntEnum

from pydantic import BaseModel
from sqlalchemy import (
    BigInteger,
    Column,
    Enum,
    Integer,
    JSON,
    LargeBinary,
    null,
    String,
    Table,
    Text,
    TypeDecorator,
    UniqueConstraint,
)

from sep.core.db import (
    DATABASE_EXTRA_COLUMNS,
    get_metadata,
)

INVENTORY_ALIAS_LENGTH = 100
INVENTORY_BACKEND_MAP = {  # CAUTION: changing existing values should be done with the utmost care
    "pmm": 1,
}
INVENTORY_BACKEND_LOOKUP = {v: k for k, v in INVENTORY_BACKEND_MAP.items()}
INVENTORY_CREDENTIAL_SOURCE_MAP = {
    "default": 1,
}
INVENTORY_CREDENTIAL_SOURCE_LOOKUP = {v: k for k, v in INVENTORY_CREDENTIAL_SOURCE_MAP.items()}


class InventoryBackendEnum(IntEnum):
    """Control the choice of backends"""

    pmm = INVENTORY_BACKEND_MAP["pmm"]


class InventoryCredentialSourceEnum(IntEnum):
    """Options for credential sources"""

    default = INVENTORY_CREDENTIAL_SOURCE_MAP["default"]  # The connector is left to its default behaviour


class InventoryItemService(BaseModel):
    """Service model"""

    service_id: str | None = None
    service_name: str | None = None
    database_name: str | None = None
    node_id: str | None = None
    address: str | None = None
    port: int | None = None
    type: str | None = None


class InventoryItemServiceType(TypeDecorator):
    """Data type to use for InventoryItemService"""

    impl = JSON

    def process_bind_param(self, value, dialect):
        if value is not None:
            value = json.dumps(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            value = json.loads(value)
        return value


class InventoryItemData(BaseModel):
    """Data model for inventory items"""

    name: str
    services: list[InventoryItemService]


class InventoryItemBaseModel(BaseModel):
    """Model for tasks"""

    name: str
    node_id: str
    data: InventoryItemData

    backend: InventoryBackendEnum = InventoryBackendEnum.pmm
    credential_source: InventoryCredentialSourceEnum = InventoryCredentialSourceEnum.default

    created_at: datetime = datetime.now(tz=timezone.utc)
    deleted_at: datetime | None = None
    updated_at: datetime | None = None


class InventoryItem(InventoryItemBaseModel):
    """Model for existing tasks"""

    id: int


inventory = Table(
    "inventory",
    get_metadata(),
    Column(
        "id",
        BigInteger().with_variant(Integer, dialect_name="sqlite"),
        autoincrement=True,
        nullable=False,
        primary_key=True,
    ),
    Column("name", String(INVENTORY_ALIAS_LENGTH), nullable=False),
    Column("node_id", String(INVENTORY_ALIAS_LENGTH), nullable=False),
    Column("data", InventoryItemServiceType, nullable=False),
    Column(
        "backend",
        Enum(InventoryBackendEnum).with_variant(Integer, dialect_name="sqlite"),
        default=null(),
        nullable=True,
    ),
    Column(
        "credential_source",
        Enum(InventoryCredentialSourceEnum).with_variant(Integer, dialect_name="sqlite"),
        default=null(),
        nullable=True,
    ),
    UniqueConstraint("name"),
)

# history = Table(
#    "inventory_history",
#    get_metadata(),
#    Column(
#        "id",
#        BigInteger().with_variant(Integer, dialect_name="sqlite"),
#        autoincrement=True,
#        nullable=False,
#        primary_key=True,
#    ),
#    Column("data", LargeBinary, nullable=False),
# )

for col in DATABASE_EXTRA_COLUMNS:
    inventory.append_column(col.copy())
