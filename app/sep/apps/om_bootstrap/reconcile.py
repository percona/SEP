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

"""Reconcile dispatched steps against their Nomad dispatch's real status.

Deliberately narrow: this module only ever *translates* a ``TaskHistory``'s
status onto the :class:`~app.sep.apps.om_bootstrap.strategy.StepRecord` that
dispatched it -- it never decides to dispatch the *next* step, retry a failed
one, or roll a run back. Those are PMM's ``om`` service's job, driving the state
machine as the HA-leader-only stepper (PMM-15347/plan.md §4 item 9): it reads a
run's current state through the API and decides what happens next.
``om_bootstrap`` only ever answers "is this step still running", mechanically,
so PMM's driver has something true to read.

``finished_at`` is stamped with the reconciliation's own clock, not read back
from ``TaskHistory``: this runs on a polling interval, not a push, so the two
times differ by at most that interval -- an acceptable approximation for a
receipt, not a claim of exact timing.

``detail`` on a non-``SUCCESS`` terminal status is currently just the
``TaskHistory`` status name -- it does not yet read the dispatch's stderr for a
real error message (the way ``om_inventory/dispatch.py``'s ``_read_stdout``
does for its own purpose). A worthwhile follow-up, not done here to keep this
module to exactly the one thing its docstring claims.
"""

from app.core.requests import RemoteAPI
from app.core.utils.date_time import utc_now
from app.sep.apps.om_bootstrap.dispatch import cleanup_step_script
from app.sep.apps.om_bootstrap.models import BootstrapRun
from app.sep.apps.om_bootstrap.persistence import dump_host_states, parse_host_states
from app.sep.apps.om_bootstrap.strategy import StepRecord, StepStatus
from app.tasks.models import TaskHistoryStatusEnum

__all__ = ["reconcile_run", "reconcile_step"]

#: ``TaskHistory`` statuses that mean "still in flight" -- everything else is
#: terminal, matching ``om_inventory/dispatch.py``'s own ``_wait_for_terminal``.
_IN_FLIGHT_STATUSES = frozenset(
    {TaskHistoryStatusEnum.PENDING.value, TaskHistoryStatusEnum.RUNNING.value}
)


async def reconcile_step(tasks_api: RemoteAPI, step: StepRecord) -> StepRecord:
    """Check one step's dispatch and translate it if it reached a terminal status.

    A no-op, returning ``step`` unchanged, for a step that is not
    :attr:`~app.sep.apps.om_bootstrap.strategy.StepStatus.RUNNING`, carries no
    :attr:`~app.sep.apps.om_bootstrap.strategy.StepRecord.task_history_id` (not
    yet dispatched), or whose dispatch is still in flight.

    :param tasks_api: The Tasks API client.
    :param step: The step to check.
    :return: ``step`` itself when nothing changed, or a new
        :class:`~app.sep.apps.om_bootstrap.strategy.StepRecord` reflecting the
        dispatch's terminal status.
    """
    if step.status != StepStatus.RUNNING or step.task_history_id is None:
        return step
    history = await tasks_api.get(f"/history/{step.task_history_id}")
    task_status = history["status"]
    if task_status in _IN_FLIGHT_STATUSES:
        return step
    if task_status == TaskHistoryStatusEnum.SUCCESS.value:
        return step.model_copy(
            update={"status": StepStatus.SUCCEEDED, "finished_at": utc_now()}
        )
    return step.model_copy(
        update={
            "status": StepStatus.FAILED,
            "finished_at": utc_now(),
            "detail": f"Task history {step.task_history_id} ended {task_status}",
        }
    )


async def reconcile_run(tasks_api: RemoteAPI, run: BootstrapRun) -> bool:
    """Reconcile every running step across every host in ``run``, in place.

    Mutates ``run.hosts`` directly when anything changed; the caller is
    responsible for committing the session. A finished step's scratch script
    (:func:`~app.sep.apps.om_bootstrap.dispatch.cleanup_step_script`) is removed
    as part of reconciling it, win or lose -- nothing downstream needs it once
    the dispatch that read it is done.

    :param tasks_api: The Tasks API client.
    :param run: The run to reconcile.
    :return: Whether anything changed -- callers use this to skip a write when
        every step was still in flight.
    """
    states = parse_host_states(run)
    changed = False
    for state in states:
        for index, step in enumerate(state.steps):
            reconciled = await reconcile_step(tasks_api, step)
            if reconciled is step:
                continue
            state.steps[index] = reconciled
            changed = True
            cleanup_step_script(str(run.id), state.host, step.name)
    if changed:
        run.hosts = dump_host_states(states)
    return changed
