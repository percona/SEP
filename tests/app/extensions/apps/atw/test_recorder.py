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

"""Tests for the ATW run-result recorder that denormalizes a run's outcome."""

from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_mock import MockerFixture
from sqlmodel.ext.asyncio.session import AsyncSession

from app.extensions.apps.atw.crud import AtwIncidentExecutionManager, AtwIncidentManager
from app.extensions.apps.atw.models import AtwIncident, AtwIncidentExecution
from app.extensions.apps.atw.recorder import record_atw_run, RUN_RESULT_RECORDER
from app.tasks.hook_resolver import resolve_hook
from app.tasks.models import TaskHistory, TaskHistoryStatusEnum
from tests.app.factories import build_task_history, TaskFactory

_FINISHED = datetime(2026, 9, 16, 1, 5, tzinfo=UTC)
_HISTORY_ID = 41
_OTHER_HISTORY_ID = 99


@pytest.fixture
def _recorder_uses_test_session(mocker: MockerFixture, session: AsyncSession) -> None:
    """Point the recorder's own extensions session at the test's in-memory session.

    ``record_atw_run`` writes on a session it opens itself: ``atw_incident_execution``
    is extensions-owned, not on the tasks database the recorder seam hands in. Patching the
    maker to yield the test session lets the write and the assertions share one
    in-memory database, and pins the recorder to the *sep* maker.
    """
    maker = MagicMock()
    maker.return_value.__aenter__ = AsyncMock(return_value=session)
    maker.return_value.__aexit__ = AsyncMock(return_value=False)
    mocker.patch(
        "app.extensions.apps.atw.recorder.get_async_session_maker", return_value=maker
    )


def _history(
    *,
    status: TaskHistoryStatusEnum = TaskHistoryStatusEnum.FAILED,
    history_id: int = _HISTORY_ID,
) -> TaskHistory:
    """Build an unsaved ``TaskHistory`` the recorder can read its outcome off."""
    history = build_task_history(TaskFactory.build(data={"meta": {}}), status=status)
    history.id = history_id
    history.finished_at = _FINISHED
    return history


async def _seed_execution(
    session: AsyncSession, *, task_history_id: int = _HISTORY_ID
) -> AtwIncidentExecution:
    """Seed one unresolved execution row pointing at ``task_history_id``."""
    incident = await AtwIncidentManager.save(session, AtwIncident(created_by="alice"))
    return await AtwIncidentExecutionManager.save(
        session,
        AtwIncidentExecution(
            incident_id=incident.id,
            task_history_id=task_history_id,
            snippet_filename="diag.sh",
        ),
    )


class TestRecorderPath:
    """Check the recorder path the ATW proxy task stamps onto its runs."""

    def test_recorder_path_resolves_through_the_hook_allow_list(self) -> None:
        """Ensure the declared path resolves, so no tasks-service change is needed."""
        assert resolve_hook(RUN_RESULT_RECORDER) is record_atw_run


@pytest.mark.usefixtures("_recorder_uses_test_session")
class TestRecordAtwRun:
    """Check what the recorder writes onto the matching execution row."""

    @pytest.mark.asyncio
    async def test_terminal_status_writes_status_and_finished_at(
        self, session: AsyncSession
    ) -> None:
        """Ensure a terminal run fills both denormalized outcome columns."""
        execution = await _seed_execution(session)

        await record_atw_run(session, _history(), None)

        await session.refresh(execution)
        assert execution.terminal_status == TaskHistoryStatusEnum.FAILED.value
        assert execution.finished_at is not None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status",
        [status for status in TaskHistoryStatusEnum if status.is_terminal()],
    )
    async def test_every_terminal_status_is_recorded_verbatim(
        self, session: AsyncSession, status: TaskHistoryStatusEnum
    ) -> None:
        """Ensure the recorder stores the status it observed, classifying nothing."""
        execution = await _seed_execution(session)

        await record_atw_run(session, _history(status=status), None)

        await session.refresh(execution)
        assert execution.terminal_status == status.value

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status",
        [status for status in TaskHistoryStatusEnum if not status.is_terminal()],
    )
    async def test_non_terminal_status_writes_nothing(
        self, session: AsyncSession, status: TaskHistoryStatusEnum
    ) -> None:
        """Ensure an in-flight run leaves the row unresolved for a later call."""
        execution = await _seed_execution(session)

        await record_atw_run(session, _history(status=status), None)

        await session.refresh(execution)
        assert execution.terminal_status is None
        assert execution.finished_at is None

    @pytest.mark.asyncio
    async def test_unknown_task_history_id_writes_nothing_and_does_not_raise(
        self, session: AsyncSession
    ) -> None:
        """Ensure a run no ATW row references is a silent no-op, not an error."""
        execution = await _seed_execution(session)

        await record_atw_run(session, _history(history_id=_OTHER_HISTORY_ID), None)

        await session.refresh(execution)
        assert execution.terminal_status is None

    @pytest.mark.asyncio
    async def test_second_call_is_idempotent(self, session: AsyncSession) -> None:
        """Ensure a re-invocation rewrites the same values rather than duplicating."""
        execution = await _seed_execution(session)

        await record_atw_run(session, _history(), None)
        await record_atw_run(session, _history(), None)

        await session.refresh(execution)
        assert execution.terminal_status == TaskHistoryStatusEnum.FAILED.value
        assert (
            await AtwIncidentExecutionManager.count(
                session, incident_id=execution.incident_id
            )
            == 1
        )

    @pytest.mark.asyncio
    async def test_result_payload_is_not_required(self, session: AsyncSession) -> None:
        """Ensure a reported result is ignored rather than parsed for the outcome."""
        execution = await _seed_execution(session)

        await record_atw_run(session, _history(), {"unexpected": "payload"})

        await session.refresh(execution)
        assert execution.terminal_status == TaskHistoryStatusEnum.FAILED.value
