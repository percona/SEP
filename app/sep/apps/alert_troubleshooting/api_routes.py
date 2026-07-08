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

"""Define the JSON API router for the Alert Troubleshooting plugin.

Mounted at ``/api/apps/alert_troubleshooting/`` via ``apps_router`` in
``app/sep/api/router.py``. Authentication is enforced at the ``api_router``
mount level (``IsApiAuthenticated``). Route layout:

* ``GET /schema``                          — static plugin schema
* ``GET /``                                — list alerts grouped by service type
* ``GET /{service_type}/{alert_name}``     — snippets for a specific alert
"""

from typing import Annotated

from fastapi import APIRouter, Path

from app.sep.apps.alert_troubleshooting.deps import (
    get_grouped_alerts,
    get_snippets_for_alert,
)
from app.sep.apps.alert_troubleshooting.models import (
    AlertDetailResponse,
    AlertGroup,
    AlertSummary,
)
from app.sep.apps.alert_troubleshooting.schema import (
    ALERT_TROUBLESHOOTING_PLUGIN_SCHEMA,
)
from app.sep.apps.framework.api import schema_endpoint
from app.sep.apps.snippets.models import build_snippet_response
from app.sep.deps import SessionDep
from app.sep.models import AlertServiceType

router = APIRouter()
schema_endpoint(router=router, plugin_schema=ALERT_TROUBLESHOOTING_PLUGIN_SCHEMA)


@router.get("/")
async def alert_troubleshooting_api_list(
    session: SessionDep,
) -> list[AlertGroup]:
    """Return alerts grouped by service type.

    :param session: The database session.
    :type session: SessionDep
    :return: A list of alert groups, each containing alerts for a service type.
    :rtype: list[AlertGroup]
    """
    grouped = await get_grouped_alerts(session)
    result = []
    for service_type, alerts in grouped.items():
        alert_summaries = [
            AlertSummary(
                name=info.name,
                label=info.label,
            )
            for info in alerts
        ]
        result.append(
            AlertGroup(
                service_type=service_type,
                label=service_type.label,
                alerts=alert_summaries,
            )
        )
    return result


@router.get("/{service_type}/{alert_name}")
async def alert_troubleshooting_api_detail(
    service_type: AlertServiceType,
    alert_name: Annotated[str, Path(min_length=1, max_length=200)],
    session: SessionDep,
) -> AlertDetailResponse:
    """Return alert info and associated snippets for a specific alert.

    :param service_type: The service type of the alert.
    :type service_type: AlertServiceType
    :param alert_name: The alert name identifier.
    :type alert_name: str
    :param session: The database session.
    :type session: SessionDep
    :return: Alert info and associated snippets.
    :rtype: AlertDetailResponse
    :raises HTTPNotFoundException: If no snippets match the alert.
    """
    snippets, alert_info = await get_snippets_for_alert(
        session=session,
        alert_name=alert_name,
        service_type=service_type,
    )
    return AlertDetailResponse(
        alert=alert_info,
        snippets=[build_snippet_response(snippet) for snippet in snippets],
    )
