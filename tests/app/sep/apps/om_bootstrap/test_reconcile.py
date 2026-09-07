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

"""Assert reconciliation translates TaskHistory status onto StepRecord, and nothing more."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.sep.apps.om_bootstrap import reconcile
from app.sep.apps.om_bootstrap.models import BootstrapRun
from app.sep.apps.om_bootstrap.persistence import dump_host_states, parse_host_states
from app.sep.apps.om_bootstrap.strategy import (
    HostBootstrapState,
    InstallMethod,
    OperatingSystem,
    StepRecord,
    StepStatus,
)

TASK_HISTORY_ID = 99


def _tasks_api(history_status: str) -> AsyncMock:
    api = AsyncMock()
    api.get.return_value = {"status": history_status}
    return api


class TestReconcileStep:
    """Assert reconcile_step's four outcomes: no-op x3, and a real transition."""

    @pytest.mark.asyncio
    async def test_a_pending_step_is_untouched(self) -> None:
        """A step that hasn't even started dispatching has nothing to reconcile."""
        step = StepRecord(name="pre_check", status=StepStatus.PENDING)

        result = await reconcile.reconcile_step(AsyncMock(), step)

        assert result is step

    @pytest.mark.asyncio
    async def test_a_running_step_with_no_task_history_id_is_untouched(self) -> None:
        """A step marked running but never actually dispatched is left alone."""
        step = StepRecord(name="pre_check", status=StepStatus.RUNNING)

        result = await reconcile.reconcile_step(AsyncMock(), step)

        assert result is step

    @pytest.mark.asyncio
    async def test_a_still_running_dispatch_is_untouched(self) -> None:
        """Polling a dispatch that hasn't finished yet changes nothing."""
        step = StepRecord(
            name="install_package",
            status=StepStatus.RUNNING,
            task_history_id=TASK_HISTORY_ID,
        )

        result = await reconcile.reconcile_step(_tasks_api("running"), step)

        assert result is step

    @pytest.mark.asyncio
    async def test_a_succeeded_dispatch_marks_the_step_succeeded(self) -> None:
        """A SUCCESS TaskHistory status becomes StepStatus.SUCCEEDED, with a finish time."""
        step = StepRecord(
            name="install_package",
            status=StepStatus.RUNNING,
            task_history_id=TASK_HISTORY_ID,
        )

        result = await reconcile.reconcile_step(_tasks_api("success"), step)

        assert result.status == StepStatus.SUCCEEDED
        assert result.finished_at is not None
        assert result.task_history_id == TASK_HISTORY_ID

    @pytest.mark.asyncio
    async def test_a_failed_dispatch_marks_the_step_failed_with_detail(self) -> None:
        """A non-SUCCESS terminal status becomes StepStatus.FAILED, with a detail message."""
        step = StepRecord(
            name="install_package",
            status=StepStatus.RUNNING,
            task_history_id=TASK_HISTORY_ID,
        )

        result = await reconcile.reconcile_step(_tasks_api("failed"), step)

        assert result.status == StepStatus.FAILED
        assert result.detail is not None
        assert str(TASK_HISTORY_ID) in result.detail

    @pytest.mark.asyncio
    async def test_a_lost_dispatch_is_also_treated_as_failed(self) -> None:
        """LOST/STOPPED/STALE are all terminal-but-not-success -- none are silently ignored."""
        step = StepRecord(
            name="install_package",
            status=StepStatus.RUNNING,
            task_history_id=TASK_HISTORY_ID,
        )

        result = await reconcile.reconcile_step(_tasks_api("lost"), step)

        assert result.status == StepStatus.FAILED


class TestReconcileRun:
    """Assert reconcile_run updates run.hosts in place and reports whether anything changed."""

    def _run(self, steps: list[StepRecord]) -> BootstrapRun:
        return BootstrapRun(
            install_method=InstallMethod.PACKAGES,
            os=OperatingSystem.UBUNTU,
            mongodb_version="8.0",
            replica_set_name="rs-test",
            hosts=dump_host_states(
                [HostBootstrapState(host="node00", steps=steps)]
            ),
        )

    @pytest.mark.asyncio
    async def test_returns_false_when_nothing_changed(self) -> None:
        """A run with only pending/in-flight steps reports no change to commit."""
        run = self._run([StepRecord(name="pre_check", status=StepStatus.PENDING)])

        changed = await reconcile.reconcile_run(AsyncMock(), run)

        assert changed is False

    @pytest.mark.asyncio
    async def test_persists_a_transitioned_step_back_onto_the_run(self) -> None:
        """A completed dispatch's new status lands back in run.hosts, not just in memory."""
        run = self._run(
            [
                StepRecord(
                    name="install_package",
                    status=StepStatus.RUNNING,
                    task_history_id=TASK_HISTORY_ID,
                )
            ]
        )

        changed = await reconcile.reconcile_run(_tasks_api("success"), run)

        assert changed is True
        reloaded = parse_host_states(run)
        assert reloaded[0].steps[0].status == StepStatus.SUCCEEDED

    @pytest.mark.asyncio
    async def test_cleans_up_the_scratch_script_for_a_transitioned_step(self) -> None:
        """A step that just reached a terminal status has its scratch script removed."""
        run = self._run(
            [
                StepRecord(
                    name="install_package",
                    status=StepStatus.RUNNING,
                    task_history_id=TASK_HISTORY_ID,
                )
            ]
        )
        run.id = uuid4()

        with patch(
            "app.sep.apps.om_bootstrap.reconcile.cleanup_step_script"
        ) as cleanup:
            await reconcile.reconcile_run(_tasks_api("success"), run)

        cleanup.assert_called_once_with(str(run.id), "node00", "install_package")

    @pytest.mark.asyncio
    async def test_does_not_clean_up_a_step_still_in_flight(self) -> None:
        """A step whose dispatch hasn't finished keeps its script -- nothing to clean up yet."""
        run = self._run(
            [
                StepRecord(
                    name="install_package",
                    status=StepStatus.RUNNING,
                    task_history_id=TASK_HISTORY_ID,
                )
            ]
        )

        with patch(
            "app.sep.apps.om_bootstrap.reconcile.cleanup_step_script"
        ) as cleanup:
            await reconcile.reconcile_run(_tasks_api("running"), run)

        cleanup.assert_not_called()
