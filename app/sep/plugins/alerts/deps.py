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

"""Define dependencies for the alerts plugin."""

import logging
from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import Depends
from fastapi.exceptions import HTTPException

from app.core.config import settings
from app.sep.clients.pmm import PMMRemoteAPI
from app.sep.config import sep_settings
from app.sep.deps import DefaultContext
from app.sep.plugins.alerts.loader import get_alert_templates
from app.sep.plugins.alerts.models import AlertTemplate, ServiceType

logger = logging.getLogger(__name__)

PAGERDUTY_CONTACT_POINT_NAME = "SEP PagerDuty"
PAGERDUTY_MIN_KEY_SUFFIX_LENGTH = 4

AlertTemplatesDep = Annotated[
    Mapping[ServiceType, tuple[AlertTemplate, ...]], Depends(get_alert_templates)
]


async def get_pmm_api() -> PMMRemoteAPI | None:
    """Return a `PMMRemoteAPI` client, or `None` when PMM is not configured.

    :return: The PMM API client, or `None` if endpoint or API key is missing.
    :rtype: PMMRemoteAPI | None
    """
    if not sep_settings.PMM.endpoint or not sep_settings.PMM.api_key:
        return None
    return await settings.get_remote_api(
        PMMRemoteAPI,
        endpoint=sep_settings.PMM.endpoint,
        api_key=sep_settings.PMM.api_key,
        verify_ssl=sep_settings.PMM.verify_ssl,
    )


PMMAPIDep = Annotated[PMMRemoteAPI | None, Depends(get_pmm_api)]


async def get_pmm_present_names(pmm_api: PMMAPIDep) -> set[str] | None:
    """Return names of alert templates present in PMM.

    Fetch all templates from the PMM API in a single batch call and extract
    their names into a set. Return `None` when the PMM client is unavailable
    or when the API call fails, enabling graceful degradation in the UI.

    :param pmm_api: The PMM API client dependency, or `None` if PMM is not
        configured.
    :type pmm_api: PMMRemoteAPI | None
    :return: A set of template names present in PMM, or `None` on failure.
    :rtype: set[str] | None
    """
    if pmm_api is None:
        return None
    try:
        templates = await pmm_api.list_templates()
        return {t.name for t in templates}
    except (HTTPException, OSError):
        logger.warning("Failed to fetch PMM alert templates", exc_info=True)
        return None


PMMPresentNamesDep = Annotated[set[str] | None, Depends(get_pmm_present_names)]


async def get_pagerduty_status(pmm_api: PMMAPIDep) -> dict[str, Any] | None:
    """Return PagerDuty contact point status for the sidebar widget.

    Fetch all contact points from PMM and find the PagerDuty one.
    Return ``None`` when PMM is unavailable or the API call fails.

    :param pmm_api: The PMM API client dependency, or ``None`` if PMM is not
        configured.
    :type pmm_api: PMMRemoteAPI | None
    :return: A dictionary with ``configured``, ``masked_key``, and ``uid`` keys
        when a PagerDuty contact point exists; ``{"configured": False}`` when
        none exists; or ``None`` when PMM is unreachable.
    :rtype: dict[str, Any] | None
    """
    if pmm_api is None:
        return None
    try:
        contact_points = await pmm_api.list_contact_points()
    except (HTTPException, OSError):
        logger.warning("Failed to fetch PagerDuty contact point status", exc_info=True)
        return None

    pd_cp = next((cp for cp in contact_points if cp.type == "pagerduty"), None)
    if pd_cp is None:
        return {"configured": False}
    key = pd_cp.settings.get("integrationKey", "")
    masked = (
        f"****{key[-PAGERDUTY_MIN_KEY_SUFFIX_LENGTH:]}"
        if len(key) >= PAGERDUTY_MIN_KEY_SUFFIX_LENGTH
        else "****"
    )
    return {"configured": True, "masked_key": masked, "uid": pd_cp.uid}


PagerDutyStatusDep = Annotated[dict[str, Any] | None, Depends(get_pagerduty_status)]


async def ensure_pagerduty_notification_route(
    pmm_api: PMMRemoteAPI, contact_point_name: str
) -> None:
    """Append a notification policy route for PagerDuty if not already present.

    Fetch the current notification policy tree from PMM, check if a route
    targeting ``contact_point_name`` already exists, and append one if it does
    not.

    :param pmm_api: The PMM API client.
    :type pmm_api: PMMRemoteAPI
    :param contact_point_name: The receiver name to match on.
    :type contact_point_name: str
    """
    policy = await pmm_api.get_notification_policy()
    if any(r.get("receiver") == contact_point_name for r in policy.routes):
        return
    policy.routes.append(
        {
            "receiver": contact_point_name,
            "matchers": [{"name": "service", "value": "sep", "type": "="}],
        }
    )
    await pmm_api.update_notification_policy(policy)


async def get_alerts_index_context(
    context: DefaultContext,
    alert_templates: AlertTemplatesDep,
    pmm_present_names: PMMPresentNamesDep,
    pagerduty_status: PagerDutyStatusDep,
) -> dict[str, Any]:
    """Assemble the template context for the alerts plugin index view.

    :param context: The default template context with user, plugins, etc.
    :type context: DefaultContext
    :param alert_templates: Alert templates grouped by service type.
    :type alert_templates: AlertTemplatesDep
    :param pmm_present_names: Set of template names present in PMM, or ``None``
        when PMM is unreachable.
    :type pmm_present_names: PMMPresentNamesDep
    :param pagerduty_status: PagerDuty contact point status for the sidebar
        widget, or ``None`` when PMM is unreachable.
    :type pagerduty_status: PagerDutyStatusDep
    :return: The updated context dictionary with alerts data.
    :rtype: dict[str, Any]
    """
    all_templates = [t for templates in alert_templates.values() for t in templates]
    context.update(
        {
            "alert_templates": alert_templates,
            "all_templates": all_templates,
            "service_types": list(ServiceType),
            "pmm_present_names": pmm_present_names,
            "pagerduty_status": pagerduty_status,
        }
    )
    return context


AlertsIndexContext = Annotated[dict[str, Any], Depends(get_alerts_index_context)]
