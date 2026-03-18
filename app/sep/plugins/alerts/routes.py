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

import logging
from typing import Annotated

from fastapi import APIRouter, Form, Request, status
from fastapi.exceptions import HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from app.core.utils.fields import NonEmptyStr
from app.sep.config import sep_settings
from app.sep.deps import IsAuthenticated, IsCsrfValidated
from app.sep.plugins.alerts.deps import (
    AlertsIndexContext,
    ensure_pagerduty_notification_route,
    mask_pagerduty_key,
    PAGERDUTY_CONTACT_POINT_NAME,
    RequiredPMMAPIDep,
)

logger = logging.getLogger(__name__)
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


@router.post("/pagerduty", dependencies=[IsAuthenticated, IsCsrfValidated])
async def pagerduty_save(
    pmm_api: RequiredPMMAPIDep,
    integration_key: Annotated[NonEmptyStr, Form()],
) -> JSONResponse:
    """Create or update the PagerDuty contact point and notification policy.

    :param pmm_api: The PMM API client dependency.
    :type pmm_api: PMMRemoteAPI
    :param integration_key: The PagerDuty integration key from the form.
    :type integration_key: NonEmptyStr
    :return: JSON with ``status`` and ``masked_key``.
    :rtype: JSONResponse
    """
    try:
        contact_points = await pmm_api.list_contact_points()
        pd_cp = next(
            (
                cp
                for cp in contact_points
                if cp.type == "pagerduty" and cp.name == PAGERDUTY_CONTACT_POINT_NAME
            ),
            None,
        )
        pd_settings = {"integrationKey": integration_key}

        if pd_cp is not None:
            await pmm_api.update_contact_point(
                pd_cp.uid,
                PAGERDUTY_CONTACT_POINT_NAME,
                "pagerduty",
                pd_settings,
            )
            result_status = "updated"
        else:
            await pmm_api.create_contact_point(
                PAGERDUTY_CONTACT_POINT_NAME,
                "pagerduty",
                pd_settings,
            )
            result_status = "created"

        await ensure_pagerduty_notification_route(pmm_api, PAGERDUTY_CONTACT_POINT_NAME)

        return JSONResponse(
            {"status": result_status, "masked_key": mask_pagerduty_key(integration_key)}
        )
    except (HTTPException, OSError):
        logger.exception("Failed to save PagerDuty contact point")
        return JSONResponse(
            {"error": "Failed to save PagerDuty configuration"},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )


@router.post("/pagerduty/token", dependencies=[IsAuthenticated, IsCsrfValidated])
async def pagerduty_token(pmm_api: RequiredPMMAPIDep) -> JSONResponse:
    """Return the full PagerDuty integration key for the reveal toggle.

    :param pmm_api: The PMM API client dependency.
    :type pmm_api: PMMRemoteAPI
    :return: JSON with ``token`` containing the full integration key.
    :rtype: JSONResponse
    """
    try:
        contact_points = await pmm_api.list_contact_points()
    except (HTTPException, OSError):
        logger.exception("Failed to fetch PagerDuty token")
        return JSONResponse(
            {"error": "Failed to fetch PagerDuty token"},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )

    pd_cp = next(
        (
            cp
            for cp in contact_points
            if cp.type == "pagerduty" and cp.name == PAGERDUTY_CONTACT_POINT_NAME
        ),
        None,
    )
    if pd_cp is None:
        return JSONResponse(
            {"error": "PagerDuty contact point not found"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return JSONResponse({"token": pd_cp.settings.get("integrationKey", "")})


@router.post("/pagerduty/delete", dependencies=[IsAuthenticated, IsCsrfValidated])
async def pagerduty_delete(pmm_api: RequiredPMMAPIDep) -> JSONResponse:
    """Delete the PagerDuty contact point and remove its notification route.

    :param pmm_api: The PMM API client dependency.
    :type pmm_api: PMMRemoteAPI
    :return: JSON with ``status`` set to ``"deleted"``.
    :rtype: JSONResponse
    """
    try:
        contact_points = await pmm_api.list_contact_points()
        pd_cp = next(
            (
                cp
                for cp in contact_points
                if cp.type == "pagerduty" and cp.name == PAGERDUTY_CONTACT_POINT_NAME
            ),
            None,
        )
        if pd_cp is None:
            return JSONResponse(
                {"error": "PagerDuty contact point not found"},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        await pmm_api.delete_contact_point(pd_cp.uid)

        policy = await pmm_api.get_notification_policy()
        policy.routes = [
            r
            for r in policy.routes
            if r.get("receiver") != PAGERDUTY_CONTACT_POINT_NAME
        ]
        await pmm_api.update_notification_policy(policy)

        return JSONResponse({"status": "deleted"})
    except (HTTPException, OSError):
        logger.exception("Failed to delete PagerDuty contact point")
        return JSONResponse(
            {"error": "Failed to delete PagerDuty configuration"},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
