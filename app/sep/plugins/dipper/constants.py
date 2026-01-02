"""Constants for the Dipper plugin."""

from pathlib import Path

from app.inventory.models import ServiceTypeEnum

DIPPER_PAYLOADS_DIR = Path(__file__).resolve().parent / "payloads"

DIPPER_SUPPORTED_SERVICE_TYPES = (
    ServiceTypeEnum.MONGODB,
    ServiceTypeEnum.MYSQL,
    ServiceTypeEnum.POSTGRESQL,
)

DIPPER_SCRIPT_BY_SERVICE_TYPE = {
    ServiceTypeEnum.MYSQL: "pcs-collect-environment-mysql.sh",
    ServiceTypeEnum.MONGODB: "pcs-collect-environment-mongo.sh",
    ServiceTypeEnum.POSTGRESQL: "pcs-collect-environment-pgsql.sh",
}
