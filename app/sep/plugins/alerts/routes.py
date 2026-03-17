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

from fastapi import APIRouter, Form, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from app.sep.config import sep_settings
from app.sep.deps import IsAuthenticated, IsCsrfValidated
from app.sep.plugins.alerts.deps import (
    AlertsIndexContext,
    AlertTemplatesDep,
    PMMPresentNamesDep,
    RequiredAlertFolderDep,
    RequiredPMMAPIDep,
)
from app.sep.plugins.alerts.models import DEFAULT_FOR_DURATION, to_pmm_template_yaml

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


@router.post("/push", dependencies=[IsAuthenticated, IsCsrfValidated])
async def alerts_push(
    pmm_api: RequiredPMMAPIDep,
    alert_templates: AlertTemplatesDep,
    folder: RequiredAlertFolderDep,
    present_names: PMMPresentNamesDep,
    selected: Annotated[list[str], Form(alias="selected_templates")],
) -> JSONResponse:
    """Push selected alert templates to PMM as rules.

    :param pmm_api: The PMM API client.
    :type pmm_api: PMMRemoteAPI
    :param alert_templates: Alert templates grouped by service type.
    :type alert_templates: AlertTemplatesDep
    :param folder: The PMM alert folder.
    :type folder: Folder
    :param present_names: Set of template names present in PMM, or ``None``
        when PMM is unreachable.
    :type present_names: set[str] | None
    :param selected: List of template names selected by the user.
    :type selected: list[str]
    :return: JSON response with per-template push results.
    :rtype: JSONResponse
    """
    all_templates = {t.name: t for ts in alert_templates.values() for t in ts}

    results = []
    for name in selected:
        template = all_templates.get(name)
        if template is None:
            results.append(
                {"name": name, "status": "error", "message": "Template not found"}
            )
            continue

        template_exists = present_names is not None and name in present_names

        if template_exists:
            try:
                await pmm_api.create_rule(
                    name=template.name,
                    template_name=template.name,
                    folder_uid=folder.uid,
                    for_duration=DEFAULT_FOR_DURATION,
                    group=sep_settings.PMM.alert_folder_name,
                )
            except (HTTPException, OSError):
                logger.debug("Rule already exists for %s", name, exc_info=True)
            results.append(
                {
                    "name": name,
                    "status": "skipped",
                    "message": "Already present in PMM",
                }
            )
            continue

        try:
            pmm_yaml = to_pmm_template_yaml(template)
            await pmm_api.create_template(pmm_yaml)
        except (HTTPException, OSError) as exc:
            detail = getattr(exc, "detail", str(exc))
            results.append({"name": name, "status": "error", "message": detail})
            continue

        try:
            await pmm_api.create_rule(
                name=template.name,
                template_name=template.name,
                folder_uid=folder.uid,
                for_duration=DEFAULT_FOR_DURATION,
                group=sep_settings.PMM.alert_folder_name,
            )
            results.append(
                {"name": name, "status": "success", "message": "Pushed successfully"}
            )
        except (HTTPException, OSError) as exc:
            detail = getattr(exc, "detail", str(exc))
            results.append(
                {
                    "name": name,
                    "status": "error",
                    "message": f"Template created but rule failed: {detail}",
                }
            )

    return JSONResponse({"results": results})
