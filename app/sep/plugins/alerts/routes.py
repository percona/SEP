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

"""Define routes for the alerts plugin."""

from typing import Annotated

from fastapi import APIRouter, Form, Request, status
from fastapi.exceptions import HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from app.sep.config import sep_settings
from app.sep.deps import DefaultContext, IsAuthenticated, IsCsrfValidated, SessionDep
from app.sep.plugins.alerts.crud import AlertBackupManager
from app.sep.plugins.alerts.deps import (
    AlertsIndexContext,
    PMMAPIDep,
    restore_from_backup,
)

router = APIRouter()
templates = sep_settings.TEMPLATES


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def alerts_index(
    request: Request,
    context: AlertsIndexContext,
) -> HTMLResponse:
    """Render the alert templates list page."""
    return templates.TemplateResponse(
        request=request,
        name="alerts/index.html.j2",
        context=context,
    )


@router.post("/restore", dependencies=[IsAuthenticated, IsCsrfValidated])
async def alerts_restore(
    pmm_api: PMMAPIDep,
    session: SessionDep,
    backup_id: Annotated[int, Form()],
) -> JSONResponse:
    """Restore alert configuration from a selected backup."""
    if pmm_api is None:
        return JSONResponse(
            {"error": "PMM is not configured"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    backup = await AlertBackupManager.get_or_404(session, id=backup_id)
    try:
        results = await restore_from_backup(pmm_api, backup)
    except (HTTPException, OSError) as exc:
        detail = getattr(exc, "detail", str(exc))
        return JSONResponse(
            {"status": "error", "message": detail},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return JSONResponse({"status": "success", "details": results})


@router.get("/backups", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def alerts_backup_list(
    request: Request,
    context: DefaultContext,
    session: SessionDep,
) -> HTMLResponse:
    """Render the full backup history page."""
    backups = await AlertBackupManager.list(session)
    context["backups"] = backups
    return templates.TemplateResponse(
        request=request,
        name="alerts/backup_history.html.j2",
        context=context,
    )
