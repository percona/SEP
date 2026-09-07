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

"""Assert HostBootstrapState derives its status from its steps, not a stored field."""

from app.sep.apps.om_bootstrap.strategy import (
    HostBootstrapState,
    StepRecord,
    StepStatus,
)


def _state(*statuses: StepStatus) -> HostBootstrapState:
    return HostBootstrapState(
        host="node00",
        steps=[
            StepRecord(name=f"step{i}", status=status)
            for i, status in enumerate(statuses)
        ],
    )


class TestHostBootstrapStateStatus:
    """One case per :meth:`HostBootstrapState.status` branch."""

    def test_all_pending_is_pending(self) -> None:
        """A run nothing has touched yet reports pending, not running."""
        assert (
            _state(StepStatus.PENDING, StepStatus.PENDING).status == StepStatus.PENDING
        )

    def test_one_running_is_running(self) -> None:
        """One step actively running makes the whole host running."""
        state = _state(StepStatus.SUCCEEDED, StepStatus.RUNNING, StepStatus.PENDING)

        assert state.status == StepStatus.RUNNING

    def test_a_finished_step_ahead_of_pending_ones_is_running(self) -> None:
        """A succeeded step followed by an untouched one means the run is mid-flight."""
        state = _state(StepStatus.SUCCEEDED, StepStatus.PENDING)

        assert state.status == StepStatus.RUNNING

    def test_all_succeeded_is_succeeded(self) -> None:
        """Every step succeeding is what "done" actually means."""
        state = _state(StepStatus.SUCCEEDED, StepStatus.SUCCEEDED)

        assert state.status == StepStatus.SUCCEEDED

    def test_succeeded_and_skipped_is_succeeded(self) -> None:
        """A skipped step (e.g. a TLS step on a non-TLS spec) does not block completion."""
        state = _state(StepStatus.SUCCEEDED, StepStatus.SKIPPED)

        assert state.status == StepStatus.SUCCEEDED

    def test_any_failed_is_failed_even_after_a_success(self) -> None:
        """One failure fails the host regardless of what already succeeded."""
        state = _state(StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.PENDING)

        assert state.status == StepStatus.FAILED

    def test_pending_finalize_steps_do_not_make_a_succeeded_host_unfinished(
        self,
    ) -> None:
        """Every finalize step stays pending until the run-level steps succeed.

        A host whose forward steps all succeeded must still read as succeeded
        even though its finalize_steps haven't started yet -- otherwise a
        perfectly normal, still-in-progress run would never satisfy
        nextRunStepAction's own "every host succeeded" gate.
        """
        state = HostBootstrapState(
            host="node00",
            steps=[StepRecord(name="only-step", status=StepStatus.SUCCEEDED)],
            finalize_steps=[StepRecord(name="enable_auth")],
        )

        assert state.status == StepStatus.SUCCEEDED
