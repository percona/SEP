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

"""Define tests for the ATW send-log model, enum, and manager."""

from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.sep.apps.atw.crud import AtwIncidentManager, AtwSendLogManager
from app.sep.apps.atw.models import (
    AtwIncident,
    AtwSendJobWrite,
    AtwSendLog,
    AtwSendLogResponse,
    AtwSendStatusEnum,
)
from tests.app.factories import AtwSendLogFactory

_EXPECTED_SEND_LOG_COUNT = 2


class TestAtwSendStatusEnum:
    """Check the send-status enum's classification members."""

    def test_active_statuses_are_the_non_terminal_ones(self) -> None:
        """Ensure only pending and running count as active."""
        assert AtwSendStatusEnum.active_statuses() == frozenset(
            {AtwSendStatusEnum.PENDING, AtwSendStatusEnum.RUNNING}
        )

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (AtwSendStatusEnum.PENDING, False),
            (AtwSendStatusEnum.RUNNING, False),
            (AtwSendStatusEnum.SUCCESS, True),
            (AtwSendStatusEnum.FAILED, True),
        ],
    )
    def test_is_terminal_marks_finished_statuses(
        self, status: AtwSendStatusEnum, *, expected: bool
    ) -> None:
        """Ensure ``is_terminal`` splits finished statuses from in-flight ones."""
        assert status.is_terminal() is expected

    def test_json_value_is_the_lowercase_member_name(self) -> None:
        """Ensure the API-facing value is lowercase while the name stays upper."""
        assert AtwSendStatusEnum.SUCCESS.value == "success"
        assert AtwSendStatusEnum.SUCCESS.name == "SUCCESS"


class TestAtwSendLogModel:
    """Check the AtwSendLog table model."""

    @pytest.mark.asyncio
    async def test_persists_with_pending_default_and_empty_detail(
        self, session: AsyncSession
    ) -> None:
        """Ensure a new send log defaults to pending with no timestamps yet."""
        incident = await AtwIncidentManager.save(
            session, AtwIncident(created_by="alice")
        )
        row = await AtwSendLogManager.save(
            session,
            AtwSendLog(
                incident_id=incident.id, case_ref="CS0001", requested_by="alice"
            ),
        )

        assert isinstance(row.id, UUID)
        assert row.status is AtwSendStatusEnum.PENDING
        assert row.started_at is None
        assert row.finished_at is None
        assert row.detail == {}

    @pytest.mark.asyncio
    async def test_deleting_the_incident_cascades_send_logs(
        self, session: AsyncSession
    ) -> None:
        """Ensure send logs are removed with their incident via the ORM cascade."""
        incident = await AtwIncidentManager.save(
            session, AtwIncident(created_by="alice")
        )
        await AtwSendLogManager.save(
            session,
            AtwSendLog(
                incident_id=incident.id, case_ref="CS0001", requested_by="alice"
            ),
        )

        await AtwIncidentManager.delete(session, incident)

        assert await AtwSendLogManager.count(session, incident_id=incident.id) == 0

    @pytest.mark.asyncio
    async def test_detail_survives_a_fresh_session_read(
        self, session: AsyncSession
    ) -> None:
        """Ensure a re-assigned ``detail`` dict is persisted, not silently dropped."""
        incident = await AtwIncidentManager.save(
            session, AtwIncident(created_by="alice")
        )
        row = await AtwSendLogManager.save(
            session,
            AtwSendLog(
                incident_id=incident.id, case_ref="CS0001", requested_by="alice"
            ),
        )

        row.detail = {"upload_response": {"result": {"sys_id": "abc"}}}
        await AtwSendLogManager.save(session, row, flag_modified_fields=["detail"])
        session.expunge_all()

        reloaded = await AtwSendLogManager.get_or_404(session, id=row.id)
        assert reloaded.detail == {"upload_response": {"result": {"sys_id": "abc"}}}


class TestAtwSendJobWrite:
    """Check the send-job create payload's declarative validation."""

    def test_rejects_an_empty_execution_id_list(self) -> None:
        """Ensure a send with no selected executions is refused at the schema."""
        with pytest.raises(ValidationError):
            AtwSendJobWrite(case_ref="CS0001", execution_ids=[])

    def test_rejects_a_blank_case_ref(self) -> None:
        """Ensure a blank support-case reference is refused at the schema."""
        with pytest.raises(ValidationError):
            AtwSendJobWrite(case_ref="", execution_ids=[UUID(int=1)])


class TestAtwSendLogResponse:
    """Check the AtwSendLogResponse API response model."""

    def test_all_persisted_fields_are_required(self) -> None:
        """Ensure the response advertises every stored field as required."""
        required = set(AtwSendLogResponse.model_json_schema()["required"])
        assert required == {
            "id",
            "incident_id",
            "case_ref",
            "requested_by",
            "status",
            "started_at",
            "finished_at",
            "created_at",
            "detail",
        }


class TestAtwSendLogManager:
    """Check the parent-scoped AtwSendLogManager."""

    @pytest.mark.asyncio
    async def test_list_scoped_by_incident(self, session: AsyncSession) -> None:
        """Ensure send logs are listed only for the requested incident."""
        incident_a = await AtwIncidentManager.save(
            session, AtwIncident(created_by="alice")
        )
        incident_b = await AtwIncidentManager.save(
            session, AtwIncident(created_by="bob")
        )
        for incident, case_ref in ((incident_a, "A"), (incident_b, "B")):
            await AtwSendLogManager.save(
                session,
                AtwSendLogFactory.build(
                    incident_id=incident.id, case_ref=case_ref, detail={}
                ),
            )

        rows = await AtwSendLogManager.list(session, incident_id=incident_a.id)
        assert [row.case_ref for row in rows] == ["A"]

    @pytest.mark.asyncio
    async def test_counts_every_row_under_one_incident(
        self, session: AsyncSession
    ) -> None:
        """Ensure repeated sends for one incident each get their own row."""
        incident = await AtwIncidentManager.save(
            session, AtwIncident(created_by="alice")
        )
        for _ in range(_EXPECTED_SEND_LOG_COUNT):
            await AtwSendLogManager.save(
                session,
                AtwSendLogFactory.build(incident_id=incident.id, detail={}),
            )

        assert (
            await AtwSendLogManager.count(session, incident_id=incident.id)
            == _EXPECTED_SEND_LOG_COUNT
        )
