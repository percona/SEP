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

"""Define database operations for the MySQL backup catalog."""

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db.crud import BaseSQLModelManager
from app.sep.apps.mysql_backups.catalog_models import MysqlBackupRun


class MysqlBackupRunManager(BaseSQLModelManager):
    """Manage :class:`MysqlBackupRun` CRUD operations.

    :cvar Model: The SQLModel class this manager is responsible for
        (``MysqlBackupRun``).
    """

    Model = MysqlBackupRun

    @classmethod
    async def list_for_service(
        cls, session: AsyncSession, service_name: str
    ) -> list[MysqlBackupRun]:
        """Return a service's recorded backup runs, newest run first.

        Ordered by run completion (``finished_at`` desc), not insertion time, so
        a run that was catalogued late cannot jump ahead of a more recently
        finished one. ``NULLS LAST`` is explicit: a row whose ``finished_at`` was
        never reported sorts to the tail on both backends (Postgres orders NULLs
        first under ``desc`` by default, SQLite last — this pins the intended
        order). ``created_at`` then ``id`` (both desc) break ties and order the
        null-``finished_at`` rows among themselves by insertion order.

        :param session: The database session to query on.
        :param service_name: The inventory service name to filter records by.
        :return: The service's backup-run records, newest run first.
        """
        return await cls.list(
            session,
            order_by=[
                MysqlBackupRun.finished_at.desc().nulls_last(),
                MysqlBackupRun.created_at.desc(),
                MysqlBackupRun.id.desc(),
            ],
            service_name=service_name,
        )
