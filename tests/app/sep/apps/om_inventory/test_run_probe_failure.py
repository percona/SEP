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

"""Test that ``run_probe`` marks a run failed for the whole width of its own work.

Only ``_sweep`` used to sit inside the ``try``/``except`` that calls ``_fail_run``.
A raise while writing what the sweep found -- ``_persist_estate`` -- or while closing
the run out -- ``_finalise`` -- propagated past both without anything marking the row
failed, leaving it ``RUNNING`` forever: the one status a caller polling ``GET
/runs/{run_id}`` can never treat as "done, try again".

Pruning (``prune_runs``) is deliberately excluded from that widened path: a run that
persisted and finalised successfully is already done, and a pruning failure afterwards
must not rewrite its terminal status.
"""

from contextlib import nullcontext
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.sep.apps.om_inventory import service as service_module
from app.sep.apps.om_inventory.crud import ProbeRunManager
from app.sep.apps.om_inventory.models import ProbeRun, ProbeRunStatus
from app.sep.apps.om_inventory.service import run_probe, SweepOutcome

#: One resolved, one answered: ``_terminal_status`` reads this as a clean SUCCESS,
#: so a run that reaches it and is *not* rewritten afterwards is unambiguous.
CLEAN_OUTCOME = SweepOutcome(resolved=1, answered=1)


def _session_maker(session: AsyncSession):
    """Build the ``get_async_session_maker`` stand-in the sweep functions expect.

    Every caller in ``service.py`` does ``async with session_maker() as session:``,
    so the replacement has to be a zero-argument callable returning something
    ``async with``-able. :class:`contextlib.nullcontext` supports the async
    protocol as well as the sync one, and handing back the same test session on
    every call is exactly what lets assertions see what ``run_probe`` wrote.

    :param session: The test session every call should reuse.
    :return: The stand-in callable.
    """
    return lambda: nullcontext(session)


class TestPersistOrFinaliseFailureMarksTheRunFailed:
    """A raise after ``_sweep`` returns must still reach ``_fail_run``."""

    @pytest.mark.asyncio
    async def test_a_persist_estate_failure_fails_the_run(
        self, session: AsyncSession
    ) -> None:
        """``_persist_estate`` raising leaves the run ``FAILED``, not ``RUNNING``.

        :param session: The database session.
        """
        run = await ProbeRunManager.save(session, ProbeRun())

        with (
            patch.object(
                service_module,
                "get_async_session_maker",
                return_value=_session_maker(session),
            ),
            patch.object(
                service_module, "_sweep", AsyncMock(return_value=CLEAN_OUTCOME)
            ),
            patch.object(
                service_module,
                "_persist_estate",
                AsyncMock(side_effect=RuntimeError("disk full")),
            ),
        ):
            returned_id = await run_probe(execution_id=run.id, node_ids=[])

        assert returned_id == run.id
        stored = await ProbeRunManager.get(session, id=run.id)
        assert stored.status == ProbeRunStatus.FAILED
        assert stored.finished_at is not None
        assert stored.error == "disk full"

    @pytest.mark.asyncio
    async def test_a_finalise_failure_fails_the_run(
        self, session: AsyncSession
    ) -> None:
        """``_finalise`` raising leaves the run ``FAILED``, not ``RUNNING``.

        ``_persist_estate`` runs for real here (with nothing for it to write, since
        ``CLEAN_OUTCOME`` carries no hosts or services) so this pins the *second*
        half of the widened window, not just the first.

        :param session: The database session.
        """
        run = await ProbeRunManager.save(session, ProbeRun())

        with (
            patch.object(
                service_module,
                "get_async_session_maker",
                return_value=_session_maker(session),
            ),
            patch.object(
                service_module, "_sweep", AsyncMock(return_value=CLEAN_OUTCOME)
            ),
            patch.object(
                service_module,
                "_finalise",
                AsyncMock(side_effect=RuntimeError("constraint violation")),
            ),
        ):
            returned_id = await run_probe(execution_id=run.id, node_ids=[])

        assert returned_id == run.id
        stored = await ProbeRunManager.get(session, id=run.id)
        assert stored.status == ProbeRunStatus.FAILED
        assert stored.finished_at is not None
        assert stored.error == "constraint violation"


class TestPruneFailureStaysOutsideTheFailurePath:
    """A raise from pruning must not rewrite an already-finalised run."""

    @pytest.mark.asyncio
    async def test_a_prune_failure_does_not_touch_the_finished_run(
        self, session: AsyncSession
    ) -> None:
        """Pruning is not covered by the same ``try`` as persist/finalise.

        The run is written to ``SUCCESS`` by the real ``_finalise`` before pruning
        ever runs. If pruning's failure were folded into the failure path, this run
        would come back ``FAILED`` with pruning's exception as its error; instead it
        must keep exactly what ``_finalise`` wrote, and ``run_probe`` propagates the
        pruning exception rather than swallowing it.

        :param session: The database session.
        """
        run = await ProbeRunManager.save(session, ProbeRun())

        with (
            patch.object(
                service_module,
                "get_async_session_maker",
                return_value=_session_maker(session),
            ),
            patch.object(
                service_module, "_sweep", AsyncMock(return_value=CLEAN_OUTCOME)
            ),
            patch.object(
                service_module,
                "prune_runs",
                AsyncMock(side_effect=RuntimeError("prune boom")),
            ),
            pytest.raises(RuntimeError, match="prune boom"),
        ):
            await run_probe(execution_id=run.id, node_ids=[])

        stored = await ProbeRunManager.get(session, id=run.id)
        assert stored.status == ProbeRunStatus.SUCCESS
        assert stored.finished_at is not None
        assert stored.error is None
