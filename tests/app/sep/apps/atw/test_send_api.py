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

"""Define tests for the ATW diagnostics send-job endpoints."""

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from kombu.exceptions import OperationalError
from pytest_mock import MockerFixture
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils.date_time import utc_now
from app.sep.apps.atw.crud import (
    AtwIncidentExecutionManager,
    AtwIncidentManager,
    AtwSendLogManager,
)
from app.sep.apps.atw.models import (
    AtwIncident,
    AtwIncidentExecution,
    AtwSendLog,
    AtwSendStatusEnum,
)
from app.sep.bundle_upload.plan import DeliveryPlan
from app.sep.config import DeliveryPlanInputs, sep_settings

_BASE = "/api/apps/atw"
_EXPECTED_PAGE_TOTAL = 3
_EXPECTED_CONCURRENT_SENDS = 2


@pytest.fixture(name="configured")
def configured_fixture(mocker: MockerFixture, delivery_plan: DeliveryPlan) -> None:
    """Configure a diagnostics receiver so the send gate passes."""
    mocker.patch.object(sep_settings, "DIAGNOSTICS_DELIVERY", delivery_plan)


@pytest.fixture(name="unconfigured")
def unconfigured_fixture(mocker: MockerFixture) -> None:
    """Leave diagnostics delivery unconfigured so the send gate refuses."""
    mocker.patch.object(sep_settings, "DIAGNOSTICS_DELIVERY", None)


def _awaiting_secrets_plan() -> DeliveryPlan:
    """Build a baked receiver whose one declared secret carries no value.

    :return: The plan an image ships before an operator supplies credentials.
    """
    return DeliveryPlan(
        endpoint="https://intake.example.com/",
        secrets={"api_key": ""},
        upload={
            "path": "attachment/upload",
            "headers": {"x-api-key": {"source": "secret", "name": "api_key"}},
            "reference_pointer": "/result/sys_id",
        },
    )


@pytest.fixture(name="awaiting_secrets")
def awaiting_secrets_fixture(mocker: MockerFixture) -> None:
    """Bake a receiver whose declared secret an operator has not supplied yet."""
    mocker.patch.object(sep_settings, "DIAGNOSTICS_DELIVERY", _awaiting_secrets_plan())
    mocker.patch.object(sep_settings, "DIAGNOSTICS_DELIVERY_INPUTS", None)


@pytest.fixture(name="configured_by_inputs")
def configured_by_inputs_fixture(mocker: MockerFixture) -> None:
    """Supply the baked receiver's declared secret through the runtime inputs."""
    mocker.patch.object(sep_settings, "DIAGNOSTICS_DELIVERY", _awaiting_secrets_plan())
    mocker.patch.object(
        sep_settings,
        "DIAGNOSTICS_DELIVERY_INPUTS",
        DeliveryPlanInputs(secrets={"api_key": "supplied-key"}),
    )


@pytest.fixture(name="enqueue")
def enqueue_fixture(mocker: MockerFixture) -> Any:
    """Intercept the Celery enqueue so no broker is needed."""
    return mocker.patch("app.sep.apps.atw.api_routes.send_incident_diagnostics")


async def _seed_incident(
    session: AsyncSession, *, executions: int = 2
) -> tuple[AtwIncident, list[AtwIncidentExecution]]:
    """Persist an incident with ``executions`` recorded snippet executions.

    :param session: The database session.
    :param executions: How many execution rows to record.
    :return: The incident and its execution rows.
    """
    incident = await AtwIncidentManager.save(
        session, AtwIncident(created_by="alice", case_ref="CS0001")
    )
    rows = [
        await AtwIncidentExecutionManager.save(
            session,
            AtwIncidentExecution(
                incident_id=incident.id,
                task_history_id=index + 1,
                snippet_filename=f"diag-{index}.sh",
            ),
        )
        for index in range(executions)
    ]
    return incident, rows


@pytest.mark.asyncio
@pytest.mark.usefixtures("configured")
class TestStartSendJob:
    """Cover POST of a new diagnostics send job."""

    async def test_creates_a_pending_row_and_enqueues_it(
        self,
        async_api_client: AsyncClient,
        session: AsyncSession,
        enqueue: Any,
    ) -> None:
        """Accept the send, record it as pending, and hand its id to the worker."""
        incident, executions = await _seed_incident(session)

        response = await async_api_client.post(
            f"{_BASE}/incidents/{incident.id}/send-jobs/",
            json={
                "case_ref": "CS0042",
                "execution_ids": [str(execution.id) for execution in executions],
            },
        )

        assert response.status_code == status.HTTP_202_ACCEPTED
        body = response.json()
        assert body["status"] == AtwSendStatusEnum.PENDING.value
        assert body["case_ref"] == "CS0042"
        assert body["requested_by"]

        row = await AtwSendLogManager.get_or_404(session, id=UUID(body["id"]))
        assert [entry["task_history_id"] for entry in row.detail["executions"]] == [
            1,
            2,
        ]
        enqueue.delay.assert_called_once_with(str(row.id))

    async def test_rejects_an_execution_from_another_incident(
        self,
        async_api_client: AsyncClient,
        session: AsyncSession,
        enqueue: Any,
    ) -> None:
        """Refuse a send naming an execution the incident does not own."""
        incident, _executions = await _seed_incident(session)
        other, other_executions = await _seed_incident(session)

        response = await async_api_client.post(
            f"{_BASE}/incidents/{incident.id}/send-jobs/",
            json={
                "case_ref": "CS0042",
                "execution_ids": [str(other_executions[0].id)],
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert str(other_executions[0].id) in str(response.json()["detail"])
        assert await AtwSendLogManager.count(session, incident_id=incident.id) == 0
        assert await AtwSendLogManager.count(session, incident_id=other.id) == 0
        enqueue.delay.assert_not_called()

    async def test_rejects_an_empty_execution_selection(
        self, async_api_client: AsyncClient, session: AsyncSession
    ) -> None:
        """Refuse a send that selects nothing."""
        incident, _executions = await _seed_incident(session)

        response = await async_api_client.post(
            f"{_BASE}/incidents/{incident.id}/send-jobs/",
            json={"case_ref": "CS0042", "execution_ids": []},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_rejects_a_blank_case_ref(
        self, async_api_client: AsyncClient, session: AsyncSession
    ) -> None:
        """Refuse a send with no support-case reference to attach to."""
        incident, executions = await _seed_incident(session)

        response = await async_api_client.post(
            f"{_BASE}/incidents/{incident.id}/send-jobs/",
            json={"case_ref": "", "execution_ids": [str(executions[0].id)]},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_a_broker_failure_leaves_a_failed_row(
        self,
        async_api_client: AsyncClient,
        session: AsyncSession,
        enqueue: Any,
    ) -> None:
        """Record the attempt as failed when it could not even be queued."""
        enqueue.delay.side_effect = OperationalError("broker unreachable")
        incident, executions = await _seed_incident(session)

        response = await async_api_client.post(
            f"{_BASE}/incidents/{incident.id}/send-jobs/",
            json={"case_ref": "CS0042", "execution_ids": [str(executions[0].id)]},
        )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        rows = await AtwSendLogManager.list(session, incident_id=incident.id)
        assert [row.status for row in rows] == [AtwSendStatusEnum.FAILED]
        assert "broker unreachable" in rows[0].detail["error"]

    async def test_concurrent_sends_for_one_incident_are_allowed(
        self,
        async_api_client: AsyncClient,
        session: AsyncSession,
        enqueue: Any,
    ) -> None:
        """Let a second send start while the first is still in flight."""
        incident, executions = await _seed_incident(session)
        payload = {
            "case_ref": "CS0042",
            "execution_ids": [str(executions[0].id)],
        }

        first = await async_api_client.post(
            f"{_BASE}/incidents/{incident.id}/send-jobs/", json=payload
        )
        second = await async_api_client.post(
            f"{_BASE}/incidents/{incident.id}/send-jobs/", json=payload
        )

        assert first.status_code == status.HTTP_202_ACCEPTED
        assert second.status_code == status.HTTP_202_ACCEPTED
        assert (
            await AtwSendLogManager.count(session, incident_id=incident.id)
            == _EXPECTED_CONCURRENT_SENDS
        )


@pytest.mark.asyncio
@pytest.mark.usefixtures("unconfigured")
class TestStartSendJobUnconfigured:
    """Cover the gate that refuses a send with no configured receiver."""

    async def test_refuses_with_the_reason(
        self, async_api_client: AsyncClient, session: AsyncSession
    ) -> None:
        """Answer 503 naming why the send cannot run."""
        incident, executions = await _seed_incident(session)

        response = await async_api_client.post(
            f"{_BASE}/incidents/{incident.id}/send-jobs/",
            json={"case_ref": "CS0042", "execution_ids": [str(executions[0].id)]},
        )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "Diagnostics delivery is not configured" in response.json()["detail"]
        assert await AtwSendLogManager.count(session, incident_id=incident.id) == 0


@pytest.mark.asyncio
class TestReadSendJobs:
    """Cover the polling and history endpoints."""

    async def test_get_returns_the_full_send_log(
        self, async_api_client: AsyncClient, session: AsyncSession
    ) -> None:
        """Return every stored field so the dialog can render any state."""
        incident, _executions = await _seed_incident(session)
        row = await AtwSendLogManager.save(
            session,
            AtwSendLog(
                incident_id=incident.id,
                case_ref="CS0042",
                requested_by="alice",
                status=AtwSendStatusEnum.SUCCESS,
                finished_at=utc_now(),
                detail={"upload_reference": "att-9"},
            ),
        )

        response = await async_api_client.get(
            f"{_BASE}/incidents/{incident.id}/send-jobs/{row.id}"
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status"] == AtwSendStatusEnum.SUCCESS.value
        assert body["detail"]["upload_reference"] == "att-9"
        assert body["finished_at"] is not None

    async def test_get_scoped_to_the_owning_incident(
        self, async_api_client: AsyncClient, session: AsyncSession
    ) -> None:
        """Refuse to read another incident's send log through this incident."""
        incident, _executions = await _seed_incident(session)
        other, _other_executions = await _seed_incident(session)
        row = await AtwSendLogManager.save(
            session,
            AtwSendLog(
                incident_id=other.id, case_ref="CS0042", requested_by="alice", detail={}
            ),
        )

        response = await async_api_client.get(
            f"{_BASE}/incidents/{incident.id}/send-jobs/{row.id}"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_get_unknown_id_is_not_found(
        self, async_api_client: AsyncClient, session: AsyncSession
    ) -> None:
        """Answer 404 for a send job that never existed."""
        incident, _executions = await _seed_incident(session)

        response = await async_api_client.get(
            f"{_BASE}/incidents/{incident.id}/send-jobs/{uuid4()}"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_list_is_paginated_newest_first(
        self, async_api_client: AsyncClient, session: AsyncSession
    ) -> None:
        """Return a paginated page of attempts with the newest first."""
        incident, _executions = await _seed_incident(session)
        for index in range(_EXPECTED_PAGE_TOTAL):
            await AtwSendLogManager.save(
                session,
                AtwSendLog(
                    incident_id=incident.id,
                    case_ref=f"CS000{index}",
                    requested_by="alice",
                    created_at=utc_now() - timedelta(minutes=index),
                    detail={},
                ),
            )

        response = await async_api_client.get(
            f"{_BASE}/incidents/{incident.id}/send-jobs/"
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == _EXPECTED_PAGE_TOTAL
        assert [item["case_ref"] for item in body["items"]] == [
            "CS0000",
            "CS0001",
            "CS0002",
        ]

    async def test_list_excludes_other_incidents(
        self, async_api_client: AsyncClient, session: AsyncSession
    ) -> None:
        """Scope the history strip to the incident being viewed."""
        incident, _executions = await _seed_incident(session)
        other, _other_executions = await _seed_incident(session)
        await AtwSendLogManager.save(
            session,
            AtwSendLog(
                incident_id=other.id, case_ref="CS9999", requested_by="bob", detail={}
            ),
        )

        response = await async_api_client.get(
            f"{_BASE}/incidents/{incident.id}/send-jobs/"
        )

        assert response.json()["total"] == 0


@pytest.mark.asyncio
class TestAtwConfig:
    """Cover the config-status endpoint the Send button reads."""

    @pytest.mark.usefixtures("unconfigured")
    async def test_reports_the_reason_when_unconfigured(
        self, async_api_client: AsyncClient
    ) -> None:
        """Tell the UI why the Send button is disabled."""
        response = await async_api_client.get(f"{_BASE}/config/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["send_disabled_reasons"] == [
            "Diagnostics delivery is not configured"
        ]

    @pytest.mark.usefixtures("configured")
    async def test_reports_no_reasons_when_configured(
        self, async_api_client: AsyncClient
    ) -> None:
        """Offer the Send button once a receiver is configured."""
        response = await async_api_client.get(f"{_BASE}/config/")

        assert response.json()["send_disabled_reasons"] == []

    @pytest.mark.usefixtures("awaiting_secrets")
    async def test_reports_a_reason_while_a_declared_secret_is_empty(
        self, async_api_client: AsyncClient
    ) -> None:
        """Withhold the Send button until an operator supplies the credentials."""
        response = await async_api_client.get(f"{_BASE}/config/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["send_disabled_reasons"] == [
            "Diagnostics delivery is not configured"
        ]

    @pytest.mark.usefixtures("configured_by_inputs")
    async def test_reports_no_reasons_once_the_inputs_supply_the_secrets(
        self, async_api_client: AsyncClient
    ) -> None:
        """Offer the Send button once the runtime inputs complete the plan."""
        response = await async_api_client.get(f"{_BASE}/config/")

        assert response.json()["send_disabled_reasons"] == []


@pytest.mark.asyncio
class TestStartSendJobRuntimeInputs:
    """Cover the send gate when the receiver's credentials arrive as runtime inputs."""

    @pytest.mark.usefixtures("configured_by_inputs")
    async def test_accepts_the_send_once_the_inputs_complete_the_plan(
        self,
        async_api_client: AsyncClient,
        session: AsyncSession,
        enqueue: Any,
    ) -> None:
        """Let the send through on a plan completed by the runtime inputs."""
        incident, executions = await _seed_incident(session)

        response = await async_api_client.post(
            f"{_BASE}/incidents/{incident.id}/send-jobs/",
            json={
                "case_ref": "CS0042",
                "execution_ids": [str(execution.id) for execution in executions],
            },
        )

        assert response.status_code == status.HTTP_202_ACCEPTED
        row = await AtwSendLogManager.get_or_404(
            session, id=UUID(response.json()["id"])
        )
        enqueue.delay.assert_called_once_with(str(row.id))

    @pytest.mark.usefixtures("awaiting_secrets")
    async def test_refuses_the_send_while_a_declared_secret_is_empty(
        self,
        async_api_client: AsyncClient,
        session: AsyncSession,
    ) -> None:
        """Refuse before staging a bundle, where the plan previously failed mid-send."""
        incident, executions = await _seed_incident(session)

        response = await async_api_client.post(
            f"{_BASE}/incidents/{incident.id}/send-jobs/",
            json={
                "case_ref": "CS0042",
                "execution_ids": [str(execution.id) for execution in executions],
            },
        )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "Diagnostics delivery is not configured" in response.json()["detail"]
