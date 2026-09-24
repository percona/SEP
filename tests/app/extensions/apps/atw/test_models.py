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
from sqlmodel.ext.asyncio.session import AsyncSession

from app.extensions.apps.atw.models import (
    AtwIncident,
    AtwIncidentResponse,
    AtwIncidentWrite,
)
from app.tasks.task_status import TaskHistoryStatusEnum
from tests.app.extensions.apps.atw.factories import (
    AtwIncidentExecutionFactory,
    AtwIncidentFactory,
)

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

    def test_run_aggregates_are_published_but_not_required(self) -> None:
        """Ensure the run-aggregate fields are additive to the shipped contract.

        Defaulted fields appear in ``properties`` but not in ``required``, so a client
        generated against the payload before these fields existed still validates a
        response that carries them.
        """
        schema = AtwIncidentResponse.model_json_schema()
        aggregate_fields = {"run_count", "failed_run_count", "last_activity_at"}

        assert aggregate_fields <= set(schema["properties"])
        assert aggregate_fields.isdisjoint(schema["required"])


class TestAtwIncidentExecutionModel:
    """Check the AtwIncidentExecution table model."""

    @pytest.mark.asyncio
    async def test_terminal_status_rejects_a_value_outside_the_enum(
        self, session: AsyncSession
    ) -> None:
        """Ensure the status column cannot hold a value the aggregate would skip.

        A bare ``str`` column would accept a misspelling and then omit it from the
        failed count silently, since the aggregate matches only known members. The
        rejection comes from the column's CHECK constraint, not from Python: SQLAlchemy
        passes an unrecognized string straight through to the database.
        """
        incident = AtwIncidentFactory.build()
        session.add(incident)
        await session.commit()
        execution = AtwIncidentExecutionFactory.build(
            incident_id=incident.id, task_history_id=1
        )
        execution.terminal_status = "teleported"
        session.add(execution)

        with pytest.raises(IntegrityError):
            await session.commit()

    @pytest.mark.asyncio
    async def test_terminal_status_round_trips_as_an_enum_member(
        self, session: AsyncSession
    ) -> None:
        """Ensure a written status comes back as the enum, not a bare string."""
        incident = AtwIncidentFactory.build()
        session.add(incident)
        await session.commit()
        execution = AtwIncidentExecutionFactory.build(
            incident_id=incident.id,
            task_history_id=2,
            terminal_status=TaskHistoryStatusEnum.UNLAUNCHABLE,
        )
        session.add(execution)
        await session.commit()
        await session.refresh(execution)

        assert execution.terminal_status is TaskHistoryStatusEnum.UNLAUNCHABLE

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
