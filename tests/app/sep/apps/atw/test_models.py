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

"""Define tests for the ATW incident DB models."""

import re
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.sep.apps.atw.models import (
    AtwIncident,
    AtwIncidentResponse,
    AtwIncidentWrite,
)
from tests.app.factories import AtwIncidentExecutionFactory, AtwIncidentFactory

_INCIDENT_NAME_PATTERN = r"Incident \d{4}-\d\d-\d\d \d\d:\d\d"


class TestDefaultIncidentName:
    """Check the server-generated default incident name."""

    def test_write_default_name_matches_timestamped_shape(self) -> None:
        """Ensure a create payload without a name gets the timestamped default."""
        assert re.fullmatch(_INCIDENT_NAME_PATTERN, AtwIncidentWrite().name)


class TestAtwIncidentModel:
    """Check the AtwIncident table model."""

    @pytest.mark.asyncio
    async def test_persists_with_generated_defaults(
        self, session: AsyncSession
    ) -> None:
        """Ensure an incident persists with a UUID id, default name, and null case."""
        incident = AtwIncident(created_by="alice", case_ref=None)
        session.add(incident)
        await session.commit()
        await session.refresh(incident)

        assert isinstance(incident.id, UUID)
        assert incident.case_ref is None
        assert re.fullmatch(_INCIDENT_NAME_PATTERN, incident.name)

    @pytest.mark.asyncio
    async def test_created_by_is_not_nullable(self, session: AsyncSession) -> None:
        """Ensure a null ``created_by`` is rejected by the NOT NULL column."""
        incident = AtwIncidentFactory.build(created_by=None)
        session.add(incident)
        with pytest.raises(IntegrityError):
            await session.commit()


class TestAtwIncidentResponse:
    """Check the AtwIncidentResponse API response model."""

    def test_all_persisted_fields_are_required(self) -> None:
        """Ensure the response advertises every stored field as required, not optional."""
        required = set(AtwIncidentResponse.model_json_schema()["required"])
        assert required == {
            "id",
            "name",
            "case_ref",
            "created_by",
            "created_at",
            "updated_at",
            "closed_at",
        }


class TestAtwIncidentExecutionModel:
    """Check the AtwIncidentExecution table model."""

    @pytest.mark.asyncio
    async def test_duplicate_incident_task_pair_is_rejected(
        self, session: AsyncSession
    ) -> None:
        """Ensure the composite unique constraint blocks a duplicate execution row."""
        incident = AtwIncidentFactory.build()
        session.add(incident)
        await session.commit()

        first = AtwIncidentExecutionFactory.build(
            incident_id=incident.id, task_history_id=1
        )
        session.add(first)
        await session.commit()

        duplicate = AtwIncidentExecutionFactory.build(
            incident_id=incident.id, task_history_id=1
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            await session.commit()
