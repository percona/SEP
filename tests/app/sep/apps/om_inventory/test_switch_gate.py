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

"""Test ``run_probe``'s own ``ENABLED`` check.

``trigger_probe`` refuses a manual trigger while ``ENABLED`` is off, but beat calls
the task directly, and the worker reads ``ENABLED`` from a snapshot that can lag the
API process that accepted a trigger. In both cases the sweep must be recorded as
refused. A run left ``RUNNING`` would hold every host until ``STALE_RUN_AFTER``.
"""

from contextlib import nullcontext
from unittest.mock import AsyncMock

import pytest
from pytest_mock import MockerFixture
from sqlmodel.ext.asyncio.session import AsyncSession

from app.sep.apps.om_inventory import service as service_module
from app.sep.apps.om_inventory.config import om_inventory_settings
from app.sep.apps.om_inventory.crud import ProbeRunManager
from app.sep.apps.om_inventory.models import ProbeRun, ProbeRunStatus
from app.sep.apps.om_inventory.service import run_probe, SWITCHED_OFF_DETAIL
from tests.app.sep.apps.om_inventory.conftest import CLEAN_OUTCOME


@pytest.fixture
def _switched_off(
    mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch, session: AsyncSession
) -> None:
    """Turn ``ENABLED`` off and point ``run_probe`` at the test session.

    :param mocker: Patches the session maker and the Nomad-bound sweep.
    :param monkeypatch: Restores the real ``ENABLED`` after the test.
    :param session: The session every ``run_probe`` block should reuse.
    """
    monkeypatch.setattr(om_inventory_settings, "ENABLED", False)
    mocker.patch.object(
        service_module,
        "get_async_session_maker",
        return_value=lambda: nullcontext(session),
    )
    mocker.patch.object(service_module, "sweep", AsyncMock(return_value=CLEAN_OUTCOME))


@pytest.mark.usefixtures("_switched_off")
class TestRunProbeWhileSwitchedOff:
    """Record a refused sweep, rather than running it or leaving it in flight."""

    @pytest.mark.asyncio
    async def test_a_triggered_run_is_closed_as_skipped(
        self, session: AsyncSession
    ) -> None:
        """Close the trigger's row as ``SKIPPED``, naming the switch.

        :param session: The database session.
        """
        run = await ProbeRunManager.save(session, ProbeRun(scope=None))

        returned_id = await run_probe(execution_id=run.id, node_ids=None)

        assert returned_id == run.id
        stored = await ProbeRunManager.get(session, id=run.id)
        assert stored.status is ProbeRunStatus.SKIPPED
        assert stored.finished_at is not None
        assert stored.error == SWITCHED_OFF_DETAIL

    @pytest.mark.asyncio
    async def test_a_scheduled_run_is_recorded_as_skipped(
        self, session: AsyncSession
    ) -> None:
        """Record a beat-driven sweep as ``SKIPPED`` instead of a silent gap.

        :param session: The database session.
        """
        returned_id = await run_probe(execution_id=None, node_ids=None)

        stored = await ProbeRunManager.get(session, id=returned_id)
        assert stored.status is ProbeRunStatus.SKIPPED
        assert stored.error == SWITCHED_OFF_DETAIL
