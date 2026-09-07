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

"""Assert BootstrapRun persists and round-trips its hosts document correctly."""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.sep.apps.om_bootstrap.models import BootstrapRun, BootstrapRunStatus
from app.sep.apps.om_bootstrap.persistence import dump_host_states, parse_host_states
from app.sep.apps.om_bootstrap.strategy import (
    HostBootstrapState,
    InstallMethod,
    OperatingSystem,
    StepRecord,
    StepStatus,
)

RUNNING_STEP_TASK_HISTORY_ID = 42


def _host_states() -> list[HostBootstrapState]:
    return [
        HostBootstrapState(
            host="node00",
            steps=[
                StepRecord(name="pre_check", status=StepStatus.SUCCEEDED),
                StepRecord(
                    name="configure_repository",
                    status=StepStatus.RUNNING,
                    task_history_id=RUNNING_STEP_TASK_HISTORY_ID,
                ),
                StepRecord(name="install_package"),
            ],
        ),
        HostBootstrapState(host="node01", steps=[StepRecord(name="pre_check")]),
    ]


class TestDumpAndParseHostStatesRoundTrip:
    """Assert the plain-JSON shape a run persists survives the round trip."""

    def test_round_trips_without_a_database(self) -> None:
        """dump_host_states then parse_host_states returns equivalent typed state."""
        original = _host_states()

        parsed = parse_host_states(
            BootstrapRun(
                install_method=InstallMethod.PACKAGES,
                os=OperatingSystem.UBUNTU,
                mongodb_version="8.0",
                replica_set_name="rs-test",
                hosts=dump_host_states(original),
            )
        )

        assert parsed == original

    def test_running_step_carries_its_task_history_id_through(self) -> None:
        """The dispatch-tracking field on StepRecord is not dropped by the round trip."""
        parsed = parse_host_states(
            BootstrapRun(
                install_method=InstallMethod.PACKAGES,
                os=OperatingSystem.UBUNTU,
                mongodb_version="8.0",
                replica_set_name="rs-test",
                hosts=dump_host_states(_host_states()),
            )
        )

        running_step = parsed[0].steps[1]
        assert running_step.task_history_id == RUNNING_STEP_TASK_HISTORY_ID


class TestBootstrapRunPersistence:
    """Assert a run actually survives a database round trip, not just in memory."""

    @pytest.mark.asyncio
    async def test_insert_and_read_back(self, session: AsyncSession) -> None:
        """The enum and JSON columns actually work end to end, not just in the model."""
        run = BootstrapRun(
            install_method=InstallMethod.PACKAGES,
            os=OperatingSystem.ROCKY,
            mongodb_version="7.0",
            replica_set_name="rs-persisted",
            hosts=dump_host_states(_host_states()),
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

        reloaded = await session.get(BootstrapRun, run.id)

        assert reloaded is not None
        assert reloaded.status == BootstrapRunStatus.RUNNING
        assert reloaded.install_method == InstallMethod.PACKAGES
        assert reloaded.os == OperatingSystem.ROCKY
        assert parse_host_states(reloaded) == _host_states()
