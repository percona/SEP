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

"""Define models for database connectivity checks."""

from enum import auto, StrEnum

from pydantic import BaseModel, Field


class ConnectivityServiceType(StrEnum):
    """Define supported database service types for connectivity checks.

    :cvar MYSQL: MySQL database service.
    :vartype MYSQL: str
    :cvar POSTGRESQL: PostgreSQL database service.
    :vartype POSTGRESQL: str
    :cvar MONGODB: MongoDB database service.
    :vartype MONGODB: str
    """

    MYSQL = auto()
    POSTGRESQL = auto()
    MONGODB = auto()


REQUIREMENTS_BY_SERVICE_TYPE = {
    ConnectivityServiceType.MYSQL: "PyMySQL[rsa,ed25519]\nmyloginpath",
    ConnectivityServiceType.POSTGRESQL: "psycopg2-binary",
    ConnectivityServiceType.MONGODB: "pymongo",
}


class ConnectivityCheckWrite(BaseModel):
    """Represent a connectivity check request payload.

    :param target: The Nomad node name to run the check on.
    :param host: The database host address.
    :param port: The database port number.
    :param service_type: The type of database service to check.
    :param timeout: Connect-phase budget in seconds, counted only once the
        ``run-script`` task starts. Total server wait is ``PROVISIONING_TIMEOUT``
        (provisioning phase) plus this value. Defaults to 30.
    """

    target: str
    host: str
    port: int
    service_type: ConnectivityServiceType
    timeout: int = Field(default=30, gt=0, le=60)


class ConnectivityCheckResponse(BaseModel):
    """Represent a connectivity check result.

    :param success: Whether the connectivity check succeeded.
    :param error: Error message if the check failed. Defaults to ``None``.
    :param task_history_id: The ID of the task history record for this check.
    """

    success: bool
    error: str | None = None
    task_history_id: int
