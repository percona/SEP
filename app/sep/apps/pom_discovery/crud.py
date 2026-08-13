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

"""Define reads and the CRUD manager for the POM Discovery table."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, delete, select

from app.core.db.crud import BaseSQLModelManager
from app.sep.apps.pom_discovery.models import ProbeRun, ProbeRunStatus


class ProbeRunManager(BaseSQLModelManager):
    """Manage :class:`ProbeRun` CRUD operations.

    :cvar Model: The SQLModel class this manager is responsible for.
    """

    Model = ProbeRun


#: Statuses a run can hold once it has stopped moving.
TERMINAL_STATUSES = (
    ProbeRunStatus.SUCCESS,
    ProbeRunStatus.PARTIAL,
    ProbeRunStatus.FAILED,
)


async def latest_terminal_run(session: AsyncSession) -> ProbeRun | None:
    """Return the newest run that finished, whatever it concluded.

    Deliberately not the newest run: a sweep in flight has no facts yet, and serving
    an empty set while one is running would make the consumer's merge lose every
    probe fact for the duration.

    :param session: The database session.
    :return: The run, or ``None`` when none has ever finished.
    """
    result = await session.exec(
        select(ProbeRun)
        .where(col(ProbeRun.status).in_(TERMINAL_STATUSES))
        .order_by(col(ProbeRun.started_at).desc())
        .limit(1)
    )
    return result.first()


async def recent_runs(session: AsyncSession, limit: int = 20) -> list[ProbeRun]:
    """Return the most recent runs, newest first.

    :param session: The database session.
    :param limit: How many to return.
    :return: The runs.
    """
    result = await session.exec(
        select(ProbeRun).order_by(col(ProbeRun.started_at).desc()).limit(limit)
    )
    return list(result.all())


async def get_run(session: AsyncSession, run_id: UUID) -> ProbeRun | None:
    """Return one run.

    :param session: The database session.
    :param run_id: The run's id.
    :return: The run, or ``None``.
    """
    return await session.get(ProbeRun, run_id)


async def running_run(session: AsyncSession) -> ProbeRun | None:
    """Return the sweep in flight, if there is one.

    :param session: The database session.
    :return: The running run, or ``None``.
    """
    result = await session.exec(
        select(ProbeRun)
        .where(ProbeRun.status == ProbeRunStatus.RUNNING)
        .order_by(col(ProbeRun.started_at).desc())
        .limit(1)
    )
    return result.first()


async def prune_runs(session: AsyncSession, keep: int) -> int:
    """Delete all but the newest ``keep`` runs.

    Every run carries its whole fact set, so the table grows by a few hundred
    kilobytes per sweep and needs bounding here rather than by an operator.

    :param session: The database session.
    :param keep: How many runs to keep.
    :return: The number deleted.
    """
    survivors = (
        select(ProbeRun.id).order_by(col(ProbeRun.started_at).desc()).limit(keep)
    )
    result = await session.exec(
        delete(ProbeRun).where(col(ProbeRun.id).not_in(survivors))  # type: ignore[call-overload]
    )
    await session.commit()
    return int(result.rowcount or 0)
