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

"""Define database operations for AlertBackup."""

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db.crud import BaseSQLModelManager
from app.sep.plugins.alerts.backup import AlertBackup


class AlertBackupManager(BaseSQLModelManager):
    """Manage AlertBackup CRUD operations.

    :cvar Model: The SQLModel class this manager is responsible for (``AlertBackup``).
    :vartype Model: type[AlertBackup]
    :cvar ordering: The default ordering for listing backups, by ``created_at``
        descending with ``id`` descending as tiebreaker.
    :vartype ordering: list[ColumnExpressionOrStrLabelArgument]
    """

    Model = AlertBackup
    ordering = [col(AlertBackup.created_at).desc(), col(AlertBackup.id).desc()]

    @classmethod
    async def list_recent(cls, session: AsyncSession, limit: int) -> list[AlertBackup]:
        """Return the most recent backups, limited to ``limit`` rows.

        :param session: The async database session.
        :type session: AsyncSession
        :param limit: Maximum number of backups to return.
        :type limit: int
        :return: A list of the most recent backups.
        :rtype: list[AlertBackup]
        """
        stmt = select(AlertBackup).order_by(*cls.ordering).limit(limit)
        result = await session.exec(stmt)
        return list(result.all())
