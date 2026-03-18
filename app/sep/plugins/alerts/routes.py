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
from app.sep.clients.pmm import PMMRemoteAPI
from app.sep.config import sep_settings
from app.sep.deps import DefaultContext, IsAuthenticated, IsCsrfValidated, SessionDep
from app.sep.plugins.alerts.crud import AlertBackupManager
from app.sep.plugins.alerts.deps import (
    AlertsIndexContext,
    AlertTemplatesDep,
    ensure_pagerduty_notification_route,
    PAGERDUTY_CONTACT_POINT_NAME,
    PMMAPIDep,
    PMMPresentNamesDep,
    RequiredAlertFolderDep,
    RequiredPMMAPIDep,
)
from app.sep.plugins.alerts.models import DEFAULT_FOR_DURATION, to_pmm_template_yaml
from app.sep.plugins.alerts.restore import restore_from_backup

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES


async def _delete_conflicting_rules(
    pmm_api: PMMRemoteAPI, rule_name: str, folder_uid: str
) -> None:
    """Delete rules that conflict with the given name in the folder.

    Remove any existing rule whose title matches ``rule_name`` as well as
    ghost rules (empty title) within the same folder so that a subsequent
    ``create_rule`` call can succeed.

    :param pmm_api: The PMM API client.
    :type pmm_api: PMMRemoteAPI
    :param rule_name: The rule title that triggered the conflict.
    :type rule_name: str
    :param folder_uid: The folder UID where the conflict occurred.
    :type folder_uid: str
    """
    rules = await pmm_api.list_rules()
    for rule in rules:
        namespace = getattr(rule, "namespace_uid", "")
        if namespace != folder_uid:
            continue
        if rule.title in (rule_name, ""):
            logger.info("Deleting conflicting rule %s (title=%r)", rule.uid, rule.title)
            await pmm_api.delete_rule(rule.uid)


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
            {"status": "error", "message": "PMM is not configured"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    try:
        backup = await AlertBackupManager.get_or_404(session, id=backup_id)
        results = await restore_from_backup(pmm_api, backup)
    except (HTTPException, OSError) as exc:
        logger.exception("Failed to restore alert configuration from backup")
        detail = getattr(exc, "detail", str(exc))
        return JSONResponse(
            {"status": "error", "message": detail},
            status_code=status.HTTP_502_BAD_GATEWAY,
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
    :return: JSON with ``status``.
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

        return JSONResponse({"status": result_status})
    except (HTTPException, OSError):
        logger.exception("Failed to save PagerDuty contact point")
        return JSONResponse(
            {"error": "Failed to save PagerDuty configuration"},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )


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

        policy = await pmm_api.get_notification_policy()
        policy.routes = [
            r
            for r in policy.routes
            if r.get("receiver") != PAGERDUTY_CONTACT_POINT_NAME
        ]
        await pmm_api.update_notification_policy(policy)

        await pmm_api.delete_contact_point(pd_cp.uid)

        return JSONResponse({"status": "deleted"})
    except (HTTPException, OSError):
        logger.exception("Failed to delete PagerDuty contact point")
        return JSONResponse(
            {"error": "Failed to delete PagerDuty configuration"},
            status_code=status.HTTP_502_BAD_GATEWAY,
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
            if "conflicts with existing" not in detail:
                results.append(
                    {
                        "name": name,
                        "status": "error",
                        "message": f"Template created but rule failed: {detail}",
                    }
                )
                continue
            try:
                await _delete_conflicting_rules(pmm_api, template.name, folder.uid)
                await pmm_api.create_rule(
                    name=template.name,
                    template_name=template.name,
                    folder_uid=folder.uid,
                    for_duration=DEFAULT_FOR_DURATION,
                    group=sep_settings.PMM.alert_folder_name,
                )
                results.append(
                    {
                        "name": name,
                        "status": "success",
                        "message": "Pushed successfully (replaced conflicting rule)",
                    }
                )
            except (HTTPException, OSError) as retry_exc:
                retry_detail = getattr(retry_exc, "detail", str(retry_exc))
                results.append(
                    {
                        "name": name,
                        "status": "error",
                        "message": f"Template created but rule failed: {retry_detail}",
                    }
                )

    return JSONResponse({"results": results})
