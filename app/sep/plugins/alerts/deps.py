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
from app.sep.deps import DefaultContext, SessionDep
from app.sep.plugins.alerts.backup import AlertBackup
from app.sep.plugins.alerts.crud import AlertBackupManager
from app.sep.plugins.alerts.loader import get_alert_templates
from app.sep.plugins.alerts.models import AlertTemplate, ServiceType

logger = logging.getLogger(__name__)

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


async def get_recent_backups(session: SessionDep) -> list[AlertBackup]:
    """Return the most recent alert backups for the sidebar widget.

    :param session: The async database session.
    :type session: SessionDep
    :return: A list of recent alert backups, ordered by creation date descending.
    :rtype: list[AlertBackup]
    """
    return await AlertBackupManager.list(session)


RecentBackupsDep = Annotated[list[AlertBackup], Depends(get_recent_backups)]


async def get_alerts_index_context(
    context: DefaultContext,
    alert_templates: AlertTemplatesDep,
    pmm_present_names: PMMPresentNamesDep,
    recent_backups: RecentBackupsDep,
) -> dict[str, Any]:
    """Assemble the template context for the alerts plugin index view.

    :param context: The default template context with user, plugins, etc.
    :type context: DefaultContext
    :param alert_templates: Alert templates grouped by service type.
    :type alert_templates: AlertTemplatesDep
    :param pmm_present_names: Set of template names present in PMM, or ``None``
        when PMM is unreachable.
    :type pmm_present_names: PMMPresentNamesDep
    :param recent_backups: The most recent alert backups for the sidebar widget.
    :type recent_backups: RecentBackupsDep
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
            "recent_backups": recent_backups,
        }
    )
    return context


AlertsIndexContext = Annotated[dict[str, Any], Depends(get_alerts_index_context)]
