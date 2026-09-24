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

"""Define database operations for ATW incidents and their executions."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from pydantic import UUID4
from sqlalchemy import case, func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db.crud import BaseSQLModelChildManager, BaseSQLModelManager
from app.core.utils.date_time import make_datetime_utc
from app.extensions.apps.atw.models import AtwIncident, AtwIncidentExecution, AtwSendLog
from app.tasks.models import TaskHistoryStatusEnum

#: The run outcomes the incident payload's failed count includes. ``STOPPED`` is an
#: operator's own choice rather than a fault, and ``PENDING``/``RUNNING`` have not
#: finished. ``UNLAUNCHABLE`` *is* included, against its own docstring's framing:
#: it separates an environment fault from a script fault, not a failure from a
#: success, and it is the common outcome for the sudo-requiring builtins.
FAILED_RUN_STATUSES: frozenset[TaskHistoryStatusEnum] = frozenset(
    {
        TaskHistoryStatusEnum.FAILED,
        TaskHistoryStatusEnum.LOST,
        TaskHistoryStatusEnum.STALE,
        TaskHistoryStatusEnum.UNLAUNCHABLE,
    }
)

#: ``FAILED_RUN_STATUSES`` in a stable order for the query's ``IN`` clause. The
#: members are bound through the column's own enum type, so the comparison follows
#: whatever representation that type stores rather than assuming one.
_FAILED_STATUS_BINDS: tuple[TaskHistoryStatusEnum, ...] = tuple(
    sorted(FAILED_RUN_STATUSES)
)


@dataclass(frozen=True, slots=True)
class IncidentRunAggregate:
    """Carry one incident's run totals as a single grouped-query row.

    :param run_count: How many executions are grouped under the incident.
    :param failed_run_count: How many of them recorded a failed outcome.
    :param last_execution_at: The latest of those executions' completion times,
        falling back to dispatch time for a run that has not finished.
    """

    run_count: int
    failed_run_count: int
    last_execution_at: datetime | None


class AtwIncidentManager(BaseSQLModelManager):
    """Manage AtwIncident CRUD operations.

    :cvar Model: The SQLModel class this manager is responsible for (``AtwIncident``).
    """

    Model = AtwIncident


class AtwIncidentExecutionManager(BaseSQLModelChildManager):
    """Manage AtwIncidentExecution CRUD operations, scoped to a parent incident.

    :cvar Model: The SQLModel class this manager handles (``AtwIncidentExecution``).
    :cvar ParentManager: The manager for the parent incident (``AtwIncidentManager``).
    :cvar connected_by: The foreign-key field linking an execution to its incident.
    """

    Model = AtwIncidentExecution
    ParentManager = AtwIncidentManager
    connected_by = "incident_id"

    @classmethod
    async def aggregate_by_incident(
        cls, session: AsyncSession, incident_ids: Sequence[UUID4]
    ) -> dict[UUID4, IncidentRunAggregate]:
        """Summarize run totals for a whole page of incidents in one query.

        Issues a single ``GROUP BY incident_id`` statement rather than a per-row
        lookup, and reads only PMM Extensions side columns, so rendering a page costs no
        upstream task-history request however many runs an incident holds.

        ``count(case(...))`` counts only the matching rows because the implicit
        ``else_`` is ``NULL`` and ``count`` skips nulls; ``max(coalesce(...))``
        keeps the three-way comparison out of SQL, which SQLAlchemy has no portable
        spelling for. An incident with no executions produces no row and is
        therefore absent from the result — the caller substitutes a zero aggregate,
        which is what lets a run-less incident report its own timestamps.

        :param session: The database session.
        :param incident_ids: The incidents to summarize; an empty sequence
            short-circuits without emitting SQL.
        :return: One aggregate per incident that has at least one execution, keyed
            by incident id.
        """
        if not incident_ids:
            return {}
        query = (
            select(
                col(AtwIncidentExecution.incident_id),
                func.count().label("run_count"),
                func.count(
                    case(
                        (
                            col(AtwIncidentExecution.terminal_status).in_(
                                _FAILED_STATUS_BINDS
                            ),
                            1,
                        )
                    )
                ).label("failed_run_count"),
                func.max(
                    func.coalesce(
                        col(AtwIncidentExecution.finished_at),
                        col(AtwIncidentExecution.created_at),
                    )
                ).label("last_execution_at"),
            )
            .where(col(AtwIncidentExecution.incident_id).in_(incident_ids))
            .group_by(col(AtwIncidentExecution.incident_id))
        )
        rows = await cls._exec(session, query)
        return {
            incident_id: IncidentRunAggregate(
                run_count=run_count,
                failed_run_count=failed_run_count,
                # Normalized because whether the type decorator applies to a
                # function's return is dialect-dependent, and a naive value would
                # raise only later, when the route compares it against the
                # incident's own aware timestamps.
                last_execution_at=None
                if last_execution_at is None
                else make_datetime_utc(last_execution_at),
            )
            for incident_id, run_count, failed_run_count, last_execution_at in rows
        }

    @classmethod
    async def unresolved_batch(
        cls,
        session: AsyncSession,
        limit: int,
        # pagination-ok: the caller's batch size bounds the result directly, and this
        # feeds a worker sweep rather than a paginated response — there is no offset
        # for a caller to walk, because each tick re-selects from the live unresolved
        # set after the previous tick moved its attempt cursor.
    ) -> list[AtwIncidentExecution]:
        """Select a bounded batch of executions whose outcome is still unknown.

        Ordered least-recently-attempted first, **not** oldest-first: a row that is
        legitimately still running, or whose upstream keeps answering 503, stays
        eligible forever, and under oldest-first it re-occupies a batch slot on
        every tick so nothing behind it is ever examined. Ordering by the sweep's
        own attempt cursor makes each tick a round-robin, so every row is reached
        within ``ceil(unresolved / limit)`` ticks.

        ``coalesce`` supplies the ordering key for a row the sweep has not touched
        yet, which sorts it by its dispatch time and so naturally ahead of rows
        already attempted after it. That avoids needing a nulls-first ordering term,
        which the project ships no primitive for.

        :param session: The database session.
        :param limit: The most rows one tick may examine.
        :return: The selected executions, least-recently-attempted first.
        """
        query = (
            select(AtwIncidentExecution)
            .where(
                col(AtwIncidentExecution.terminal_status).is_(None),
                col(AtwIncidentExecution.outcome_unrecoverable).is_(False),
            )
            .order_by(
                func.coalesce(
                    col(AtwIncidentExecution.reconcile_attempted_at),
                    col(AtwIncidentExecution.created_at),
                ).asc(),
                # utc_now() truncates to whole seconds, so the key above ties
                # readily; the primary key breaks them into a stable order.
                col(AtwIncidentExecution.id).asc(),
            )
            .limit(limit)
        )
        rows = await cls._exec(session, query)
        return list(rows.all())


class AtwSendLogManager(BaseSQLModelChildManager):
    """Manage AtwSendLog CRUD operations, scoped to a parent incident.

    :cvar Model: The SQLModel class this manager handles (``AtwSendLog``).
    :cvar ParentManager: The manager for the parent incident (``AtwIncidentManager``).
    :cvar connected_by: The foreign-key field linking a send log to its incident.
    """

    Model = AtwSendLog
    ParentManager = AtwIncidentManager
    connected_by = "incident_id"
