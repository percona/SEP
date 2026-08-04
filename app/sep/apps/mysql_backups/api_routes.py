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

"""Define the custom JSON API routes for the MySQL Backups catalog.

The declarative :class:`~app.sep.apps.framework.apps.TaskExecutionApp` in
``app.py`` derives the task CRUD surface; this router carries the per-service
completed-backup catalog query, mounted as the app's ``extra_routes``. The
route is read-only and inherits the app's standard authenticated-user gate from
the ``/api/apps/*`` mount, so it introduces no mutating or unauthenticated
surface.
"""

from fastapi import APIRouter

from app.core.pagination import PaginatedResponse
from app.core.pagination.deps import PaginationDep
from app.sep.apps.mysql_backups.crud import MysqlBackupRunManager
from app.sep.apps.mysql_backups.deps import ResolvedMysqlService
from app.sep.apps.mysql_backups.models import BackupRunResponse
from app.sep.deps import SessionDep

router = APIRouter()


@router.get("/services/{service_id}/backups")
async def list_service_backups(
    service: ResolvedMysqlService,
    session: SessionDep,
    pagination: PaginationDep,
) -> PaginatedResponse[BackupRunResponse]:
    """Return a page of a MySQL service's completed backup runs, newest run first.

    The ``service_id`` path parameter is resolved by
    :data:`~app.sep.apps.mysql_backups.deps.ResolvedMysqlService`, which lets an
    unknown service surface as a ``404``. A resolvable service with no recorded
    runs yields an empty page, so a caller building a restore selector is never
    blocked by an empty catalog but is still told when the service itself is
    unknown.

    :param service: The inventory service resolved from the ``service_id`` path
        parameter.
    :param session: The database session the catalog is queried on.
    :param pagination: The requested offset/limit window.
    :return: The requested page of the service's recorded backup runs, newest
        run first.
    """
    return await MysqlBackupRunManager.list_for_service(
        session, service.name, pagination=pagination
    )
