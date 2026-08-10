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

"""Define FastAPI dependencies for the ATW plugin's incident routes."""

from typing import Annotated

from fastapi import Depends
from pydantic import UUID4

from app.core.exceptions import HTTPConflictException, HTTPServiceUnavailableException
from app.sep.apps.atw.crud import AtwIncidentManager
from app.sep.apps.atw.models import AtwIncident
from app.sep.bundle_upload.resolver import resolve_delivery_plan
from app.sep.deps import SessionDep


async def get_atw_incident(session: SessionDep, incident_id: UUID4) -> AtwIncident:
    """Resolve the ``incident_id`` path parameter to an incident or raise 404.

    :param session: The database session.
    :param incident_id: The incident's UUID.
    :return: The matching incident.
    :raises HTTPNotFoundException: If no incident has that id.
    """
    return await AtwIncidentManager.get_or_404(session, id=incident_id)


AtwIncidentDep = Annotated[AtwIncident, Depends(get_atw_incident)]


async def require_open_incident(incident: AtwIncidentDep) -> AtwIncident:
    """Return the incident or raise if it has been closed.

    :param incident: The incident resolved from the ``incident_id`` path parameter.
    :return: The matching open incident.
    :raises HTTPConflictException: If the incident is closed.
    """
    if incident.closed_at is not None:
        raise HTTPConflictException(detail="This incident is closed.")
    return incident


OpenAtwIncidentDep = Annotated[AtwIncident, Depends(require_open_incident)]


async def require_closed_incident(incident: AtwIncidentDep) -> AtwIncident:
    """Return the incident or raise if it is still open.

    :param incident: The incident resolved from the ``incident_id`` path parameter.
    :return: The matching closed incident.
    :raises HTTPConflictException: If the incident is already open.
    """
    if incident.closed_at is None:
        raise HTTPConflictException(detail="This incident is already open.")
    return incident


ClosedAtwIncidentDep = Annotated[AtwIncident, Depends(require_closed_incident)]


def diagnostics_send_disabled_reasons() -> list[str]:
    """Return why the incident send action is unavailable, empty when it is not.

    The plan is resolved from the baked skeleton and its runtime inputs on every
    call, so a partially-configured receiver — a declared secret left without a
    value — is reported here rather than failing mid-send. Delivery that was
    working until stored inputs stopped matching the plan is reported
    separately, because re-supplying the inputs and configuring delivery for the
    first time are opposite actions.

    ``resolve_delivery_plan`` logs which secret names are involved; the reason
    surfaced to the UI names none of them, because it reaches an operator who
    cannot act on the receiver's internal secret names.

    :return: The reasons to withhold the send action from the UI.
    """
    if (reason := resolve_delivery_plan().unavailable_reason) is not None:
        return [reason]
    return []


async def require_diagnostics_send_configured() -> None:
    """Raise if diagnostics delivery is not configured.

    :raises HTTPServiceUnavailableException: If no receiver is configured.
    """
    if reasons := diagnostics_send_disabled_reasons():
        raise HTTPServiceUnavailableException(detail="; ".join(reasons))


IsDiagnosticsSendConfigured = Depends(require_diagnostics_send_configured)
