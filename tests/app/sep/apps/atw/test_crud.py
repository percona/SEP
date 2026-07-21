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

"""Define tests for the ATW incident CRUD managers."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import HTTPNotFoundException
from app.core.pagination.models import Pagination
from app.core.utils.date_time import utc_now
from app.sep.apps.atw.crud import AtwIncidentExecutionManager, AtwIncidentManager
from app.sep.apps.atw.models import AtwIncident, AtwIncidentExecution

_EXPECTED_INCIDENT_COUNT = 2
_EXECUTION_TASK_IDS = (1, 2)


class TestAtwIncidentManager:
    """Check AtwIncidentManager CRUD round-trips."""

    @pytest.mark.asyncio
    async def test_save_and_get_or_404_round_trip(self, session: AsyncSession) -> None:
        """Ensure an incident can be saved and retrieved by id."""
        saved = await AtwIncidentManager.save(
            session, AtwIncident(created_by="alice", name="Case 42")
        )
        assert isinstance(saved.id, UUID)

        fetched = await AtwIncidentManager.get_or_404(session, id=saved.id)
        assert fetched.id == saved.id
        assert fetched.name == "Case 42"

    @pytest.mark.asyncio
    async def test_get_or_404_unknown_id_raises(self, session: AsyncSession) -> None:
        """Ensure a missing incident raises the project 404 exception."""
        with pytest.raises(HTTPNotFoundException):
            await AtwIncidentManager.get_or_404(session, id=uuid4())

    @pytest.mark.asyncio
    async def test_list_paginated_orders_newest_first(
        self, session: AsyncSession
    ) -> None:
        """Ensure list_paginated returns incidents newest-first with a total."""
        await AtwIncidentManager.save(
            session,
            AtwIncident(
                created_by="alice",
                name="older",
                created_at=utc_now() - timedelta(minutes=1),
            ),
        )
        await AtwIncidentManager.save(
            session, AtwIncident(created_by="alice", name="newer", created_at=utc_now())
        )

        page = await AtwIncidentManager.list_paginated(
            session, pagination=Pagination(offset=0, limit=50)
        )
        assert page.total == _EXPECTED_INCIDENT_COUNT
        assert [incident.name for incident in page.items] == ["newer", "older"]

    @pytest.mark.asyncio
    async def test_delete_cascades_executions(self, session: AsyncSession) -> None:
        """Ensure deleting an incident removes its execution rows via ORM cascade."""
        incident = await AtwIncidentManager.save(
            session, AtwIncident(created_by="alice")
        )
        for task_history_id in _EXECUTION_TASK_IDS:
            await AtwIncidentExecutionManager.save(
                session,
                AtwIncidentExecution(
                    incident_id=incident.id,
                    task_history_id=task_history_id,
                    snippet_filename="diag.sh",
                ),
            )
        assert await AtwIncidentExecutionManager.count(
            session, incident_id=incident.id
        ) == len(_EXECUTION_TASK_IDS)

        await AtwIncidentManager.delete(session, incident)

        assert (
            await AtwIncidentExecutionManager.count(session, incident_id=incident.id)
            == 0
        )


class TestAtwIncidentExecutionManager:
    """Check the parent-scoped AtwIncidentExecutionManager."""

    @pytest.mark.asyncio
    async def test_list_scoped_by_incident(self, session: AsyncSession) -> None:
        """Ensure executions are listed only for the requested incident."""
        incident_a = await AtwIncidentManager.save(
            session, AtwIncident(created_by="alice")
        )
        incident_b = await AtwIncidentManager.save(
            session, AtwIncident(created_by="bob")
        )
        await AtwIncidentExecutionManager.save(
            session,
            AtwIncidentExecution(
                incident_id=incident_a.id, task_history_id=1, snippet_filename="a.sh"
            ),
        )
        await AtwIncidentExecutionManager.save(
            session,
            AtwIncidentExecution(
                incident_id=incident_b.id, task_history_id=1, snippet_filename="b.sh"
            ),
        )

        rows = await AtwIncidentExecutionManager.list(
            session, incident_id=incident_a.id
        )
        assert len(rows) == 1
        assert rows[0].snippet_filename == "a.sh"
