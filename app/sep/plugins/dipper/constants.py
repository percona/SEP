"""Constants for the Dipper plugin."""

from enum import auto, StrEnum
from pathlib import Path

from app.core.utils.fields import EnumFieldMixin
from app.inventory.models import ServiceTypeEnum

DIPPER_PAYLOADS_DIR = Path(__file__).resolve().parent / "payloads"


class CollectorTypeEnum(EnumFieldMixin, StrEnum):
    """Define enum for Dipper collector types."""

    ENVIRONMENT = auto()
    PMM = auto()


DIPPER_SCRIPT_BY_SERVICE_TYPE = {
    ServiceTypeEnum.MYSQL: "pcs-collect-environment-mysql.sh",
    ServiceTypeEnum.MONGODB: "pcs-collect-environment-mongo.sh",
    ServiceTypeEnum.POSTGRESQL: "pcs-collect-environment-pgsql.sh",
}

DIPPER_PMM_SCRIPT_BY_SERVICE_TYPE = {
    ServiceTypeEnum.MYSQL: "pcs-collect-pmm-mysql.py",
}
