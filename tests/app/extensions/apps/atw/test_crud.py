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

from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pytest_mock import MockerFixture
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import HTTPNotFoundException
from app.core.pagination.models import Pagination
from app.core.utils.date_time import utc_now
from app.extensions.apps.atw.crud import AtwIncidentExecutionManager, AtwIncidentManager
from app.extensions.apps.atw.models import AtwIncident, AtwIncidentExecution
from app.tasks.models import TaskHistoryStatusEnum

_EXPECTED_INCIDENT_COUNT = 2
_EXECUTION_TASK_IDS = (1, 2)

#: The statuses the failed count must include. Spelled out here from enum members
#: rather than imported from the manager module, so the test states the contract
#: instead of restating the implementation.
_EXPECTED_FAILED_STATUSES = frozenset(
    {
        TaskHistoryStatusEnum.FAILED,
        TaskHistoryStatusEnum.LOST,
        TaskHistoryStatusEnum.STALE,
        TaskHistoryStatusEnum.UNLAUNCHABLE,
    }
)
_THREE_RUNS = 3
_FOUR_RUNS = 4
_TWO_FAILED = 2
_TWO_ROWS = 2


async def _save_execution(
    session: AsyncSession,
    incident: AtwIncident,
    *,
    task_history_id: int,
    terminal_status: TaskHistoryStatusEnum | None = None,
    finished_at: datetime | None = None,
    created_at: datetime | None = None,
    outcome_unrecoverable: bool = False,
    reconcile_attempted_at: datetime | None = None,
) -> AtwIncidentExecution:
    """Persist one execution row under ``incident``, defaulting to unresolved.

    :param session: The database session.
    :param incident: The incident the execution is grouped under.
    :param task_history_id: The upstream history id the row points at.
    :param terminal_status: The recorded outcome, or ``None`` while unknown.
    :param finished_at: When the run finished, as the tasks service reported it.
    :param created_at: An explicit dispatch time, for ordering assertions.
    :param outcome_unrecoverable: Whether the upstream row is gone for good.
    :param reconcile_attempted_at: When the sweep last examined the row.
    :return: The saved execution row.
    """
    execution = AtwIncidentExecution(
        incident_id=incident.id,
        task_history_id=task_history_id,
        snippet_filename="diag.sh",
        terminal_status=None if terminal_status is None else terminal_status.value,
        finished_at=finished_at,
        outcome_unrecoverable=outcome_unrecoverable,
        reconcile_attempted_at=reconcile_attempted_at,
    )
    if created_at is not None:
        execution.created_at = created_at
    return await AtwIncidentExecutionManager.save(session, execution)


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


class TestAggregateByIncident:
    """Check the grouped run aggregate that feeds the incident payload."""

    @pytest.mark.asyncio
    async def test_empty_id_list_returns_empty_map_without_querying(
        self, session: AsyncSession, mocker: MockerFixture
    ) -> None:
        """Ensure an empty page short-circuits instead of emitting a SQL statement."""
        spy = mocker.spy(AtwIncidentExecutionManager, "_exec")

        assert (
            await AtwIncidentExecutionManager.aggregate_by_incident(session, []) == {}
        )
        assert spy.call_count == 0

    @pytest.mark.asyncio
    async def test_incident_with_no_runs_is_absent_from_map(
        self, session: AsyncSession
    ) -> None:
        """Ensure a run-less incident yields no row, leaving the caller to zero it."""
        incident = await AtwIncidentManager.save(
            session, AtwIncident(created_by="alice")
        )

        aggregates = await AtwIncidentExecutionManager.aggregate_by_incident(
            session, [incident.id]
        )

        assert aggregates == {}

    @pytest.mark.asyncio
    async def test_counts_runs_and_only_failed_outcomes(
        self, session: AsyncSession
    ) -> None:
        """Ensure run_count counts every row and failed_run_count only failures."""
        incident = await AtwIncidentManager.save(
            session, AtwIncident(created_by="alice")
        )
        await _save_execution(
            session,
            incident,
            task_history_id=1,
            terminal_status=TaskHistoryStatusEnum.FAILED,
        )
        await _save_execution(
            session,
            incident,
            task_history_id=2,
            terminal_status=TaskHistoryStatusEnum.LOST,
        )
        await _save_execution(
            session,
            incident,
            task_history_id=3,
            terminal_status=TaskHistoryStatusEnum.SUCCESS,
        )

        aggregates = await AtwIncidentExecutionManager.aggregate_by_incident(
            session, [incident.id]
        )

        assert aggregates[incident.id].run_count == _THREE_RUNS
        assert aggregates[incident.id].failed_run_count == _TWO_FAILED

    @pytest.mark.asyncio
    async def test_unresolved_runs_count_towards_neither_failure_nor_absence(
        self, session: AsyncSession
    ) -> None:
        """Ensure a run with no recorded outcome is counted but not called failed."""
        incident = await AtwIncidentManager.save(
            session, AtwIncident(created_by="alice")
        )
        await _save_execution(session, incident, task_history_id=1)

        aggregates = await AtwIncidentExecutionManager.aggregate_by_incident(
            session, [incident.id]
        )

        assert aggregates[incident.id].run_count == 1
        assert aggregates[incident.id].failed_run_count == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", list(TaskHistoryStatusEnum))
    async def test_failed_classification_covers_every_status(
        self, session: AsyncSession, status: TaskHistoryStatusEnum
    ) -> None:
        """Ensure every status is classified as failed or not, with none unclassified.

        Driven from ``list(TaskHistoryStatusEnum)`` so a member added upstream fails
        this test rather than silently falling into "not counted".
        """
        incident = await AtwIncidentManager.save(
            session, AtwIncident(created_by="alice")
        )
        await _save_execution(
            session, incident, task_history_id=1, terminal_status=status
        )

        aggregates = await AtwIncidentExecutionManager.aggregate_by_incident(
            session, [incident.id]
        )

        expected = 1 if status in _EXPECTED_FAILED_STATUSES else 0
        assert aggregates[incident.id].failed_run_count == expected

    @pytest.mark.asyncio
    async def test_groups_multiple_incidents_in_one_call(
        self, session: AsyncSession
    ) -> None:
        """Ensure one call keys its result per incident rather than mixing rows."""
        first = await AtwIncidentManager.save(session, AtwIncident(created_by="alice"))
        second = await AtwIncidentManager.save(session, AtwIncident(created_by="bob"))
        await _save_execution(
            session,
            first,
            task_history_id=1,
            terminal_status=TaskHistoryStatusEnum.FAILED,
        )
        await _save_execution(
            session,
            second,
            task_history_id=1,
            terminal_status=TaskHistoryStatusEnum.SUCCESS,
        )

        aggregates = await AtwIncidentExecutionManager.aggregate_by_incident(
            session, [first.id, second.id]
        )

        assert aggregates[first.id].failed_run_count == 1
        assert aggregates[second.id].failed_run_count == 0

    @pytest.mark.asyncio
    async def test_last_execution_at_is_timezone_aware(
        self, session: AsyncSession
    ) -> None:
        """Ensure the aggregated timestamp survives the type decorator tz-aware.

        ``func.max()`` over a ``DateTimeWithTimezone`` column is the one framework
        behaviour the plan could not verify, and a naive value here would raise a
        ``TypeError`` only later, when the route compares it against the incident's
        own ``created_at``.
        """
        incident = await AtwIncidentManager.save(
            session, AtwIncident(created_by="alice")
        )
        await _save_execution(
            session,
            incident,
            task_history_id=1,
            terminal_status=TaskHistoryStatusEnum.SUCCESS,
            finished_at=utc_now(),
        )

        aggregates = await AtwIncidentExecutionManager.aggregate_by_incident(
            session, [incident.id]
        )

        last_execution_at = aggregates[incident.id].last_execution_at
        assert last_execution_at is not None
        assert last_execution_at.tzinfo is not None

    @pytest.mark.asyncio
    async def test_last_execution_at_prefers_finished_at_over_dispatch_time(
        self, session: AsyncSession
    ) -> None:
        """Ensure a finished run reports its completion time, not its dispatch."""
        incident = await AtwIncidentManager.save(
            session, AtwIncident(created_by="alice")
        )
        dispatched = utc_now() - timedelta(hours=2)
        finished = utc_now() - timedelta(minutes=5)
        await _save_execution(
            session,
            incident,
            task_history_id=1,
            terminal_status=TaskHistoryStatusEnum.SUCCESS,
            created_at=dispatched,
            finished_at=finished,
        )

        aggregates = await AtwIncidentExecutionManager.aggregate_by_incident(
            session, [incident.id]
        )

        last_execution_at = aggregates[incident.id].last_execution_at
        assert last_execution_at is not None
        assert last_execution_at > dispatched

    @pytest.mark.asyncio
    async def test_last_execution_at_falls_back_to_dispatch_time(
        self, session: AsyncSession
    ) -> None:
        """Ensure an unresolved run still reports its dispatch time as activity."""
        incident = await AtwIncidentManager.save(
            session, AtwIncident(created_by="alice")
        )
        dispatched = utc_now() - timedelta(minutes=30)
        await _save_execution(
            session, incident, task_history_id=1, created_at=dispatched
        )

        aggregates = await AtwIncidentExecutionManager.aggregate_by_incident(
            session, [incident.id]
        )

        assert aggregates[incident.id].last_execution_at == dispatched


class TestUnresolvedBatch:
    """Check the reconciliation sweep's bounded, fair selection of rows."""

    @pytest.mark.asyncio
    async def test_excludes_resolved_and_unrecoverable_rows(
        self, session: AsyncSession
    ) -> None:
        """Ensure only rows with no outcome and no dead upstream are selected."""
        incident = await AtwIncidentManager.save(
            session, AtwIncident(created_by="alice")
        )
        unresolved = await _save_execution(session, incident, task_history_id=1)
        await _save_execution(
            session,
            incident,
            task_history_id=2,
            terminal_status=TaskHistoryStatusEnum.SUCCESS,
        )
        await _save_execution(
            session, incident, task_history_id=3, outcome_unrecoverable=True
        )

        rows = await AtwIncidentExecutionManager.unresolved_batch(session, limit=10)

        assert [row.id for row in rows] == [unresolved.id]

    @pytest.mark.asyncio
    async def test_limit_bounds_the_tick(self, session: AsyncSession) -> None:
        """Ensure the batch size caps how many rows one tick examines."""
        incident = await AtwIncidentManager.save(
            session, AtwIncident(created_by="alice")
        )
        for task_history_id in (1, 2, 3):
            await _save_execution(session, incident, task_history_id=task_history_id)

        rows = await AtwIncidentExecutionManager.unresolved_batch(session, limit=2)

        assert len(rows) == _TWO_ROWS

    @pytest.mark.asyncio
    async def test_selection_is_least_recently_attempted_first(
        self, session: AsyncSession
    ) -> None:
        """Ensure an already-attempted older row yields its slot to a newer one.

        This is the regression test for oldest-first selection, which does not
        terminate: a row that is legitimately still running stays eligible forever
        and, being among the oldest, re-occupies the batch on every tick while
        everything behind it starves. With ``limit=1`` the older row must be
        examined on the first tick and the newer one on the second.
        """
        incident = await AtwIncidentManager.save(
            session, AtwIncident(created_by="alice")
        )
        older = await _save_execution(
            session,
            incident,
            task_history_id=1,
            created_at=utc_now() - timedelta(hours=2),
        )
        newer = await _save_execution(
            session,
            incident,
            task_history_id=2,
            created_at=utc_now() - timedelta(hours=1),
        )

        first_tick = await AtwIncidentExecutionManager.unresolved_batch(
            session, limit=1
        )
        assert [row.id for row in first_tick] == [older.id]

        older.reconcile_attempted_at = utc_now()
        await AtwIncidentExecutionManager.save(session, older)

        second_tick = await AtwIncidentExecutionManager.unresolved_batch(
            session, limit=1
        )
        assert [row.id for row in second_tick] == [newer.id]


class TestRunAggregatesOnRealPostgres:
    """Run the new Core SQL on the other supported engine, not just SQLite.

    SQLite is the permissive engine of the two and is no stand-in for PostgreSQL
    here: ``count(case(...))``, ``max(coalesce(...))`` over a timezone-aware column,
    and a boolean ``IS FALSE`` predicate are exactly where the dialects diverge, and
    a PostgreSQL-only defect would stay green through the whole SQLite suite.
    """

    @pytest.mark.postgres
    @pytest.mark.asyncio
    async def test_aggregate_matches_sqlite_and_returns_aware_timestamps(
        self, postgres_session: AsyncSession
    ) -> None:
        """Ensure the grouped aggregate runs on PostgreSQL with the same results."""
        incident = await AtwIncidentManager.save(
            postgres_session, AtwIncident(created_by="alice")
        )
        finished = utc_now()
        await _save_execution(
            postgres_session,
            incident,
            task_history_id=1,
            terminal_status=TaskHistoryStatusEnum.FAILED,
            finished_at=finished,
        )
        await _save_execution(
            postgres_session,
            incident,
            task_history_id=2,
            terminal_status=TaskHistoryStatusEnum.UNLAUNCHABLE,
            finished_at=finished,
        )
        await _save_execution(
            postgres_session,
            incident,
            task_history_id=3,
            terminal_status=TaskHistoryStatusEnum.SUCCESS,
        )
        await _save_execution(postgres_session, incident, task_history_id=4)

        aggregates = await AtwIncidentExecutionManager.aggregate_by_incident(
            postgres_session, [incident.id]
        )

        aggregate = aggregates[incident.id]
        assert aggregate.run_count == _FOUR_RUNS
        assert aggregate.failed_run_count == _TWO_FAILED
        assert aggregate.last_execution_at is not None
        assert aggregate.last_execution_at.tzinfo is not None

    @pytest.mark.postgres
    @pytest.mark.asyncio
    async def test_unresolved_batch_predicate_and_ordering_run_on_postgres(
        self, postgres_session: AsyncSession
    ) -> None:
        """Ensure the sweep's boolean predicate and coalesce ordering hold on PostgreSQL."""
        incident = await AtwIncidentManager.save(
            postgres_session, AtwIncident(created_by="alice")
        )
        older = await _save_execution(
            postgres_session,
            incident,
            task_history_id=1,
            created_at=utc_now() - timedelta(hours=2),
        )
        await _save_execution(
            postgres_session,
            incident,
            task_history_id=2,
            terminal_status=TaskHistoryStatusEnum.SUCCESS,
        )
        await _save_execution(
            postgres_session, incident, task_history_id=3, outcome_unrecoverable=True
        )

        rows = await AtwIncidentExecutionManager.unresolved_batch(
            postgres_session, limit=10
        )

        assert [row.id for row in rows] == [older.id]
