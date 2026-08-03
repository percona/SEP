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

from fastapi import APIRouter, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import HTTPNotFoundException
from app.core.pagination import DEFAULT_PAGINATION_LIMIT, PaginatedResponse, Pagination
from app.core.pagination.deps import PaginationDep
from app.sep.apps.framework.schema import Choice
from app.sep.apps.mysql_backups.backup_source_choices import backup_run_to_choice
from app.sep.apps.mysql_backups.crud import MysqlBackupRunManager
from app.sep.apps.mysql_backups.deps import resolve_mysql_service, ResolvedMysqlService
from app.sep.apps.mysql_backups.models import BackupRunResponse
from app.sep.apps.mysql_backups.restore.deps import UNKNOWN_SERVICE_SENTINEL
from app.sep.deps import InventoryAPI, SessionDep

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


async def _choices_for_service_name(
    session: AsyncSession, service_name: str
) -> list[Choice]:
    """Return Choice options for ``service_name``, newest first, capped at one page.

    :param session: The database session the catalog is queried on.
    :param service_name: The inventory service name to filter catalog rows by.
    :return: Choice-compatible options; at most ``DEFAULT_PAGINATION_LIMIT`` items.
    """
    page = await MysqlBackupRunManager.list_for_service(
        session,
        service_name,
        pagination=Pagination(offset=0, limit=DEFAULT_PAGINATION_LIMIT),
    )
    return [
        choice
        for run in page.items
        if (choice := backup_run_to_choice(run)) is not None
    ]


@router.get("/backup-sources/choices")
async def list_backup_source_choices(
    session: SessionDep,
    inventory_api: InventoryAPI,
    service_id: str = Query(
        ...,
        description=(
            "Cascade parent from the restore form. Inventory numeric ids are "
            "resolved to a MySQL service name; custom names query the catalog "
            "directly. Sentinel/blank/unknown values yield an empty list so "
            "free-text entry is never blocked by a failed options fetch."
        ),
    ),
) -> list[Choice]:
    """Return ``Choice`` options for a MySQL service's restore ``backup_source``.

    The ``service_id`` query parameter (cascade parent name on the restore form)
    selects which catalog rows to map. Options are newest-first and capped at
    :data:`~app.core.pagination.DEFAULT_PAGINATION_LIMIT` (older runs remain
    reachable via free-text). An empty or unresolvable parent yields ``[]`` —
    never a ``4xx`` — so the RemoteChoices free-text escape hatch stays usable.

    :param session: The database session the catalog is queried on.
    :param inventory_api: The Inventory API client used to resolve numeric ids.
    :param service_id: The cascade parent's submitted value.
    :return: Choice-compatible options for the restore backup-source selector.
    """
    trimmed = service_id.strip()
    if not trimmed or trimmed == UNKNOWN_SERVICE_SENTINEL:
        return []
    try:
        numeric_id = int(trimmed)
    except ValueError:
        return await _choices_for_service_name(session, trimmed)
    try:
        service = await resolve_mysql_service(numeric_id, inventory_api)
    except HTTPNotFoundException:
        return []
    return await _choices_for_service_name(session, service.name)
