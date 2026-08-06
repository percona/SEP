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

from sqlalchemy import or_
from sqlalchemy.sql import ColumnExpressionArgument
from sqlmodel import and_, col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db.crud import BaseSQLModelManager
from app.core.db.utils import NullsLastOrdering
from app.core.pagination import PaginatedResponse, Pagination
from app.sep.apps.mysql_backups.models import MysqlBackupRun


class MysqlBackupRunManager(BaseSQLModelManager):
    """Manage :class:`MysqlBackupRun` CRUD operations.

    :cvar Model: The SQLModel class this manager is responsible for
        (``MysqlBackupRun``).
    """

    Model = MysqlBackupRun

    @classmethod
    def _service_key(
        cls, service_name: str, service_id: int | None
    ) -> ColumnExpressionArgument[bool]:
        """Return the predicate selecting one service's rows.

        Prefers the inventory id, which survives a rename where the name does not.
        The name is matched only for rows carrying *no* id — guarding that fallback
        on ``IS NULL`` is what keeps two same-named services apart, since
        ``Service.name`` carries no uniqueness constraint and an unguarded name
        match would hand each service the other's runs.

        :param service_name: The inventory service name to match rows by.
        :param service_id: The inventory service id, or ``None`` when the caller
            resolved no inventory service.
        :return: The SQL predicate selecting this service's rows.
        """
        by_name = col(MysqlBackupRun.service_name) == service_name
        if service_id is None:
            return by_name
        return or_(
            col(MysqlBackupRun.service_id) == service_id,
            and_(col(MysqlBackupRun.service_id).is_(None), by_name),
        )

    @classmethod
    async def list_for_service(
        cls,
        session: AsyncSession,
        service_name: str,
        *,
        service_id: int | None = None,
        pagination: Pagination,
    ) -> PaginatedResponse[MysqlBackupRun]:
        """Return a page of a service's recorded backup runs, newest run first.

        Keyed by :meth:`_service_key`. The reported total counts exactly the rows
        this query can return, so a caller paging to a fixed cap is never cut short
        by a total drawn from a wider key.

        Ordered by run completion (``finished_at`` desc), not insertion time, so
        a run that was catalogued late cannot jump ahead of a more recently
        finished one. NULLs-last is explicit via
        :class:`~app.core.db.utils.NullsLastOrdering`, so a row whose
        ``finished_at`` was never reported sorts to the tail on every supported
        backend, including MySQL, which has no native ``NULLS LAST`` syntax.
        ``created_at`` then ``id`` (both desc) break ties and order the
        null-``finished_at`` rows among themselves by insertion order.

        :param session: The database session to query on.
        :param service_name: The inventory service name to filter records by.
        :param service_id: The inventory service id to prefer as the key, or
            ``None`` (default) to key on the name alone.
        :param pagination: Validated offset/limit window for this page.
        :return: The requested page of the service's backup-run records, newest
            run first.
        """
        return await cls.list_paginated(
            session,
            cls._service_key(service_name, service_id),
            order_by=[
                NullsLastOrdering(MysqlBackupRun.finished_at, descending=True),
                MysqlBackupRun.created_at.desc(),
                MysqlBackupRun.id.desc(),
            ],
            pagination=pagination,
        )
