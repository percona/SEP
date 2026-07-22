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

from app.sep.apps.atw.crud import AtwIncidentManager
from app.sep.apps.atw.models import AtwIncident
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
