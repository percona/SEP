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
completed-backup catalog query and the restore ``backup_source`` Choice options
endpoint, mounted as the app's ``extra_routes``. Both routes are read-only and
inherit the app's standard authenticated-user gate from the ``/api/apps/*``
mount, so they introduce no mutating or unauthenticated surface.
"""

from fastapi import APIRouter

from app.core.pagination import PaginatedResponse
from app.core.pagination.deps import PaginationDep
from app.sep.apps.framework.schema import Choice
from app.sep.apps.mysql_backups.backup_source_choices import choices_for_service_name
from app.sep.apps.mysql_backups.crud import MysqlBackupRunManager
from app.sep.apps.mysql_backups.deps import (
    OptionalMysqlServiceName,
    ResolvedMysqlService,
)
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


@router.get("/backup-sources/choices")
async def list_backup_source_choices(
    session: SessionDep,
    service_name: OptionalMysqlServiceName,
) -> list[Choice]:  # pagination-ok: bounded by DEFAULT_PAGINATION_LIMIT
    """Return ``Choice`` options for a MySQL service's restore ``backup_source``.

    The ``service_id`` query parameter (cascade parent name on the restore form)
    selects which catalog rows to map. Options are newest-first and capped at
    :data:`~app.core.pagination.DEFAULT_PAGINATION_LIMIT` (older runs remain
    reachable via free-text). An omitted, empty, sentinel, or unknown parent
    yields ``[]`` rather than a ``404``, so the RemoteChoices free-text escape
    hatch stays usable. Other Inventory API failures still propagate.

    Free-typed (non-numeric) parents query the catalog by that name without an
    Inventory type check — matching ``ServiceRef(allow_custom=True)`` on the
    restore form, where the destination may be a name that has no MySQL
    inventory row. Numeric parents still require a resolvable MySQL service.

    :param session: The database session the catalog is queried on.
    :param service_name: The cascade parent resolved to a catalog service name,
        or ``None`` when the parent is unusable.
    :return: Choice-compatible options for the restore backup-source selector.
    """
    if service_name is None:
        return []
    return await choices_for_service_name(session, service_name)
