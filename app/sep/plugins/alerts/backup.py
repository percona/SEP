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

"""Define the AlertBackup database model."""

from typing import Any

from sqlalchemy import Column, JSON
from sqlmodel import Field as SQLField

from app.core.db.models import BaseSQLModel


class AlertBackup(BaseSQLModel, table=True):
    """Store a point-in-time snapshot of PMM alert configuration.

    :param data: The full alert configuration data including templates,
        rules, contact points, notification policies, and folders.
    :type data: dict[str, Any]
    :param metadata_: Summary counts for the backed-up configuration,
        stored as the ``metadata`` column in the database.
    :type metadata_: dict[str, Any]
    """

    __tablename__ = "alert_backup"

    data: dict[str, Any] = SQLField(sa_column=Column(JSON, nullable=False))
    metadata_: dict[str, Any] = SQLField(
        sa_column=Column("metadata", JSON, nullable=False)
    )
