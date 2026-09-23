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

import aiohttp
import pytest
from fastapi import HTTPException

from app.core.exceptions import (
    HTTPBadGatewayException,
    HTTPGoneException,
    HTTPNotFoundException,
)
from app.sep.apps.om_bootstrap import reconcile
from app.sep.apps.om_bootstrap.models import BootstrapRun, BootstrapRunStatus
from app.sep.apps.om_bootstrap.persistence import (
    dump_host_states,
    dump_run_steps,
    parse_host_states,
    parse_run_steps,
)
from app.sep.apps.om_bootstrap.strategy import (
    HostBootstrapState,
    StepRecord,
    StepStatus,
)
from tests.app.sep.apps.om_bootstrap.factories import BootstrapRunFactory

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

    @pytest.mark.asyncio
    async def test_a_malformed_history_payload_raises_instead_of_hanging_forever(
        self,
    ) -> None:
        """A non-dict TaskHistory body is a bad upstream answer, not "still running"."""
        step = StepRecord(
            name="install_package",
            status=StepStatus.RUNNING,
            task_history_id=TASK_HISTORY_ID,
        )
        tasks_api = AsyncMock()
        tasks_api.get.return_value = None

        with pytest.raises(HTTPBadGatewayException):
            await reconcile.reconcile_step(tasks_api, step)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", [{}, {"status": None}, {"status": 3}])
    async def test_a_history_payload_without_a_string_status_raises(
        self, payload: dict[str, object]
    ) -> None:
        """Reject a TaskHistory without a readable status as a bad upstream answer."""
        step = StepRecord(
            name="install_package",
            status=StepStatus.RUNNING,
            task_history_id=TASK_HISTORY_ID,
        )
        tasks_api = AsyncMock()
        tasks_api.get.return_value = payload

        with pytest.raises(HTTPBadGatewayException):
            await reconcile.reconcile_step(tasks_api, step)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error",
        [HTTPNotFoundException(detail="gone"), HTTPGoneException(detail="gone")],
    )
    async def test_a_vanished_history_record_marks_the_step_failed(
        self, error: HTTPException
    ) -> None:
        """Fail the step on a 404/410, since its dispatch can never be read again."""
        step = StepRecord(
            name="install_package",
            status=StepStatus.RUNNING,
            task_history_id=TASK_HISTORY_ID,
        )
        tasks_api = AsyncMock()
        tasks_api.get.side_effect = error

        result = await reconcile.reconcile_step(tasks_api, step)

        assert result.status == StepStatus.FAILED
        assert result.finished_at is not None
        assert result.detail is not None
        assert "no longer exists" in result.detail

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error",
        [
            aiohttp.ClientConnectionError("refused"),
            TimeoutError(),
            HTTPException(status_code=503, detail="unavailable"),
        ],
    )
    async def test_a_transient_read_failure_leaves_the_step_running(
        self, error: Exception
    ) -> None:
        """Leave the step running when the Tasks API is unreachable or failing."""
        step = StepRecord(
            name="install_package",
            status=StepStatus.RUNNING,
            task_history_id=TASK_HISTORY_ID,
        )
        tasks_api = AsyncMock()
        tasks_api.get.side_effect = error

        result = await reconcile.reconcile_step(tasks_api, step)

        assert result is step


class TestReconcileRun:
    """Assert reconcile_run updates run.hosts in place and reports whether anything changed."""

    def _run(
        self,
        steps: list[StepRecord],
        *,
        rollback_steps: list[StepRecord] | None = None,
        run_steps: list[StepRecord] | None = None,
    ) -> BootstrapRun:
        return BootstrapRunFactory.build(
            hosts=dump_host_states(
                [
                    HostBootstrapState(
                        host="node00",
                        steps=steps,
                        rollback_steps=rollback_steps or [],
                    )
                ]
            ),
            run_steps=dump_run_steps(run_steps or []),
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

    @pytest.mark.asyncio
    async def test_reconciles_run_level_steps_too(self) -> None:
        """A run-level dispatch's outcome lands in run.run_steps, not just hosts."""
        run = self._run(
            [StepRecord(name="verify", status=StepStatus.SUCCEEDED)],
            run_steps=[
                StepRecord(
                    name="rs_initiate",
                    status=StepStatus.RUNNING,
                    task_history_id=TASK_HISTORY_ID,
                )
            ],
        )

        changed = await reconcile.reconcile_run(_tasks_api("success"), run)

        assert changed is True
        assert parse_run_steps(run)[0].status == StepStatus.SUCCEEDED

    @pytest.mark.asyncio
    async def test_cleans_up_a_run_level_step_under_the_seed_host(self) -> None:
        """A run-level step's scratch script is named under the run's first host."""
        run = self._run(
            [StepRecord(name="verify", status=StepStatus.SUCCEEDED)],
            run_steps=[
                StepRecord(
                    name="rs_initiate",
                    status=StepStatus.RUNNING,
                    task_history_id=TASK_HISTORY_ID,
                )
            ],
        )
        run.id = uuid4()

        with patch(
            "app.sep.apps.om_bootstrap.reconcile.cleanup_step_script"
        ) as cleanup:
            await reconcile.reconcile_run(_tasks_api("success"), run)

        cleanup.assert_called_once_with(str(run.id), "node00", "rs_initiate")

    @pytest.mark.asyncio
    async def test_reconciles_rollback_steps_too(self) -> None:
        """A rollback dispatch's outcome lands in the host's rollback_steps."""
        run = self._run(
            [StepRecord(name="install_package", status=StepStatus.FAILED)],
            rollback_steps=[
                StepRecord(
                    name="stop_service",
                    status=StepStatus.RUNNING,
                    task_history_id=TASK_HISTORY_ID,
                )
            ],
        )

        changed = await reconcile.reconcile_run(_tasks_api("success"), run)

        assert changed is True
        assert parse_host_states(run)[0].rollback_steps[0].status == (
            StepStatus.SUCCEEDED
        )

    @pytest.mark.asyncio
    async def test_marks_a_fully_succeeded_run_succeeded(self) -> None:
        """Once every host and run-level step succeeds, the run itself does too."""
        run = self._run(
            [StepRecord(name="verify", status=StepStatus.SUCCEEDED)],
            run_steps=[
                StepRecord(
                    name="create_pmm_monitoring_user",
                    status=StepStatus.RUNNING,
                    task_history_id=TASK_HISTORY_ID,
                )
            ],
        )
        assert run.status == BootstrapRunStatus.RUNNING

        changed = await reconcile.reconcile_run(_tasks_api("success"), run)

        assert changed is True
        assert run.status == BootstrapRunStatus.SUCCEEDED
        assert run.finished_at is not None

    @pytest.mark.asyncio
    async def test_does_not_mark_succeeded_while_a_host_step_is_pending(self) -> None:
        """A run isn't done just because its run-level steps finished first."""
        run = self._run(
            [StepRecord(name="verify", status=StepStatus.PENDING)],
            run_steps=[StepRecord(name="rs_initiate", status=StepStatus.SUCCEEDED)],
        )

        await reconcile.reconcile_run(AsyncMock(), run)

        assert run.status == BootstrapRunStatus.RUNNING

    @pytest.mark.asyncio
    async def test_does_not_override_an_already_terminal_status(self) -> None:
        """A run the stepper already marked FAILED/ROLLED_BACK is left alone."""
        run = self._run([StepRecord(name="verify", status=StepStatus.SUCCEEDED)])
        run.status = BootstrapRunStatus.FAILED

        await reconcile.reconcile_run(AsyncMock(), run)

        assert run.status == BootstrapRunStatus.FAILED

    @pytest.mark.asyncio
    async def test_pending_rollback_steps_do_not_block_success(self) -> None:
        """A never-triggered rollback list (all PENDING) doesn't count against success."""
        run = self._run(
            [StepRecord(name="verify", status=StepStatus.SUCCEEDED)],
            rollback_steps=[StepRecord(name="stop_service")],
        )

        await reconcile.reconcile_run(AsyncMock(), run)

        assert run.status == BootstrapRunStatus.SUCCEEDED
