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
