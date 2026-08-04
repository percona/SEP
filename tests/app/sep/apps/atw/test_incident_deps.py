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

"""Define tests for the ATW open- and closed-incident dependency guards."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import HTTPConflictException
from app.core.utils.date_time import utc_now
from app.sep.apps.atw.crud import AtwIncidentManager
from app.sep.apps.atw.deps import require_closed_incident, require_open_incident
from app.sep.apps.atw.models import AtwIncident


@pytest_asyncio.fixture
async def open_incident(session: AsyncSession) -> AtwIncident:
    """Seed one open incident."""
    return await AtwIncidentManager.save(
        session, AtwIncident(created_by="alice", name="Open incident")
    )


@pytest_asyncio.fixture
async def closed_incident(session: AsyncSession) -> AtwIncident:
    """Seed one closed incident."""
    return await AtwIncidentManager.save(
        session,
        AtwIncident(created_by="alice", name="Closed incident", closed_at=utc_now()),
    )


class TestRequireOpenIncident:
    """Cover the open-incident guard dependency."""

    @pytest.mark.asyncio
    async def test_open_incident_passes_through(
        self, open_incident: AtwIncident
    ) -> None:
        """Return the incident unchanged when it is open."""
        result = await require_open_incident(open_incident)

        assert result is open_incident

    @pytest.mark.asyncio
    async def test_closed_incident_raises_conflict(
        self, closed_incident: AtwIncident
    ) -> None:
        """Reject a closed incident before batch execution or close can proceed."""
        with pytest.raises(HTTPConflictException) as exc_info:
            await require_open_incident(closed_incident)

        assert "closed" in exc_info.value.detail.lower()


class TestRequireClosedIncident:
    """Cover the closed-incident guard dependency."""

    @pytest.mark.asyncio
    async def test_closed_incident_passes_through(
        self, closed_incident: AtwIncident
    ) -> None:
        """Return the incident unchanged when it is closed."""
        result = await require_closed_incident(closed_incident)

        assert result is closed_incident

    @pytest.mark.asyncio
    async def test_open_incident_raises_conflict(
        self, open_incident: AtwIncident
    ) -> None:
        """Reject an open incident before reopen can proceed."""
        with pytest.raises(HTTPConflictException) as exc_info:
            await require_closed_incident(open_incident)

        assert "open" in exc_info.value.detail.lower()
