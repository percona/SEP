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

"""Serve bootstrap runs: create one, dispatch its steps, read its progress.

PMM's ``om`` service is the only intended caller (PMM-15347/plan.md §4 item 9):
it drives the state machine -- deciding when to dispatch which step, when to
retry, when to give up and roll back -- as the HA-leader-only stepper, reading
this router to know what happened and calling it to make something happen
next. This router itself decides none of that; it only ever does exactly what
it is asked; see ``reconcile.py``'s own docstring for the same boundary stated
from the other side.

Auth is applied at the mount level: ``/api/apps`` carries the
``IsApiAuthenticated`` router guard, and unsafe methods additionally require
the rank :func:`app.api.deps.require_minimum_role` registers per route.
Triggering a run or a step is root execution on a database host -- Adamo's
decided gate (PMM-15347/questions.md Q6) is admin-only, so both mutating routes
register :attr:`~app.core.auth.models.UserRole.ADMIN` explicitly.
"""

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi import status as http_status
from pydantic import BaseModel

from app.api.deps import require_minimum_role
from app.core.auth.models import UserRole
from app.core.config import settings
from app.core.exceptions import (
    HTTPBadRequestException,
    HTTPConflictException,
    HTTPNotFoundException,
)
from app.core.requests import RemoteAPI
from app.core.security import require_internal_token
from app.core.utils.date_time import utc_now
from app.core.utils.fields import UTCDatetime
from app.sep.apps.framework.api import schema_endpoint
from app.sep.apps.om_bootstrap.crud import BootstrapRunManager, get_run
from app.sep.apps.om_bootstrap.dispatch import dispatch_step
from app.sep.apps.om_bootstrap.models import BootstrapRun, BootstrapRunStatus
from app.sep.apps.om_bootstrap.persistence import (
    dump_host_states,
    parse_host_states,
    to_models_install_method,
    to_models_os,
    to_strategy_install_method,
    to_strategy_os,
)
from app.sep.apps.om_bootstrap.reconcile import reconcile_run
from app.sep.apps.om_bootstrap.schema import om_bootstrap_schema
from app.sep.apps.om_bootstrap.strategies import strategy_for
from app.sep.apps.om_bootstrap.strategy import (
    BootstrapSpec,
    HostBootstrapState,
    InstallMethod,
    OperatingSystem,
    StepRecord,
    StepStatus,
)
from app.sep.config import sep_settings
from app.sep.deps import SessionDep


class TriggerRunRequest(BaseModel):
    """Request one bootstrap run over a set of hosts, all sharing one spec.

    :param hosts: The hosts to provision -- one-member or three-member replica
        sets only, per Adamo's decided phase-1 scope
        (PMM-15347/questions.md Q5/Q12).
    :param install_method: Which strategy provisions every host in this run.
    :param os: Every host's OS. Mixed-OS replica sets are out of phase-1 scope.
    :param mongodb_version: The Percona Server for MongoDB version to install.
    :param replica_set_name: The replica set every host joins.
    """

    hosts: list[str]
    install_method: InstallMethod
    os: OperatingSystem
    mongodb_version: str
    replica_set_name: str


class RunResponse(BaseModel):
    """One bootstrap run, in full.

    :param id: The run's id.
    :param status: The run's lifecycle state.
    :param install_method: The run's install method.
    :param os: The run's target OS.
    :param mongodb_version: The run's MongoDB version.
    :param replica_set_name: The replica set every host in this run joins.
    :param started_at: When the run began.
    :param finished_at: When it reached a terminal status, if it has.
    :param hosts: Every host's current step-by-step progress -- the full,
        run-specific step list each host was planned with, not just the steps
        that have started (PMM-15347/plan.md §4 item 9).
    :param error: The run-level failure detail, when the run itself raised
        outside any single host's steps.
    """

    id: UUID
    status: BootstrapRunStatus
    install_method: InstallMethod
    os: OperatingSystem
    mongodb_version: str
    replica_set_name: str
    started_at: UTCDatetime
    finished_at: UTCDatetime | None
    hosts: list[HostBootstrapState]
    error: str | None


def _run_response(run: BootstrapRun) -> RunResponse:
    """Build the response DTO from a persisted run.

    :param run: The run to serialize.
    :return: The run's full state.
    """
    return RunResponse(
        id=run.id,
        status=run.status,
        install_method=to_strategy_install_method(run.install_method),
        os=to_strategy_os(run.os),
        mongodb_version=run.mongodb_version,
        replica_set_name=run.replica_set_name,
        started_at=run.started_at,
        finished_at=run.finished_at,
        hosts=parse_host_states(run),
        error=run.error,
    )


async def _tasks_api_client() -> RemoteAPI:
    """Build an unauthenticated Tasks API client -- the caller sets its own auth scope.

    Same construction om_inventory's own probe dispatch and bootstrap PoC used
    (``om_inventory/service.py``, ``om_inventory/api_routes.py``).

    :return: The Tasks API client.
    """
    return await settings.get_remote_api(
        endpoint=sep_settings.TASKS_ENDPOINT,
        ssl_cafile=settings.SSL_CAFILE,
        logger_name="tasks_api",
    )


router = APIRouter()
schema_endpoint(router=router, plugin_schema=om_bootstrap_schema)


@router.post("/runs", status_code=http_status.HTTP_201_CREATED)
@require_minimum_role(UserRole.ADMIN)
async def trigger_run(session: SessionDep, request: TriggerRunRequest) -> RunResponse:
    """Create a bootstrap run, planning every host's steps up front.

    Dispatches nothing: creating a run only plans it, so the caller (PMM's
    driver) sees the full step list for every host before anything is touched.
    Actually starting a host's first step is a separate call to
    :func:`dispatch_run_step`.

    :param session: The database session.
    :param request: The requested run.
    :raises HTTPBadRequestException: When ``request.hosts`` is empty.
    :return: The created run, every host's steps ``pending``.
    """
    if not request.hosts:
        raise HTTPBadRequestException(detail="At least one host is required")

    spec = BootstrapSpec(
        install_method=request.install_method,
        os=request.os,
        mongodb_version=request.mongodb_version,
        replica_set_name=request.replica_set_name,
    )
    strategy = strategy_for(request.install_method)
    host_states = [
        HostBootstrapState(
            host=host,
            steps=[StepRecord(name=name) for name in strategy.plan_steps(spec)],
        )
        for host in request.hosts
    ]
    run = await BootstrapRunManager.save(
        session,
        BootstrapRun(
            install_method=to_models_install_method(request.install_method),
            os=to_models_os(request.os),
            mongodb_version=request.mongodb_version,
            replica_set_name=request.replica_set_name,
            hosts=dump_host_states(host_states),
        ),
    )
    return _run_response(run)


@router.get("/runs/{run_id}")
async def get_bootstrap_run(run_id: UUID, session: SessionDep) -> RunResponse:
    """Return one run, reconciling any of its running steps first.

    Reconciling on every read (rather than relying solely on a periodic task)
    means PMM's driver always sees a step's real outcome on its very next poll,
    not after waiting for a separate schedule to catch up.

    :param run_id: The run's id.
    :param session: The database session.
    :raises HTTPNotFoundException: When there is no such run.
    :return: The run, with current step status.
    """
    run = await get_run(session, run_id)
    if run is None:
        raise HTTPNotFoundException(detail=f"Bootstrap run {run_id} not found")

    tasks_api = await _tasks_api_client()
    with tasks_api.auth(require_internal_token()):
        changed = await reconcile_run(tasks_api, run)
    if changed:
        run = await BootstrapRunManager.save(session, run)
    return _run_response(run)


@router.post(
    "/runs/{run_id}/hosts/{host}/steps/{step_name}:dispatch",
    status_code=http_status.HTTP_202_ACCEPTED,
)
@require_minimum_role(UserRole.ADMIN)
async def dispatch_run_step(
    run_id: UUID,
    host: str,
    step_name: str,
    session: SessionDep,
    request: Request,
) -> RunResponse:
    """Dispatch one host's named step now.

    Does **not** wait for the dispatch to finish -- it returns as soon as the
    Tasks API accepts it, the same fire-and-forget shape ``dispatch_step``
    itself commits to. The caller polls :func:`get_bootstrap_run` for progress.

    Re-dispatching a step already ``pending`` or ``failed`` is how PMM's driver
    implements Adamo's decided retry policy (PMM-15347/questions.md Q8) -- this
    route does not itself decide *whether* to retry, only executes the request.

    :param run_id: The run's id.
    :param host: The host to dispatch the step on.
    :param step_name: The step to dispatch -- one of the names the run was
        planned with.
    :param session: The database session.
    :param request: The current request, whose host builds the artifact
        download URL the executor fetches the step's script from.
    :raises HTTPNotFoundException: When there is no such run, host, or step.
    :raises HTTPConflictException: When the step is already running.
    :return: The run, with the dispatched step now ``running``.
    """
    run = await get_run(session, run_id)
    if run is None:
        raise HTTPNotFoundException(detail=f"Bootstrap run {run_id} not found")

    states = parse_host_states(run)
    host_state = next((state for state in states if state.host == host), None)
    if host_state is None:
        raise HTTPNotFoundException(detail=f"Host {host!r} is not part of run {run_id}")
    step_index = next(
        (i for i, step in enumerate(host_state.steps) if step.name == step_name), None
    )
    if step_index is None:
        raise HTTPNotFoundException(
            detail=f"Step {step_name!r} is not planned for host {host!r}"
        )
    step = host_state.steps[step_index]
    if step.status == StepStatus.RUNNING:
        raise HTTPConflictException(
            detail=f"Step {step_name!r} for host {host!r} is already running"
        )

    install_method = to_strategy_install_method(run.install_method)
    spec = BootstrapSpec(
        install_method=install_method,
        os=to_strategy_os(run.os),
        mongodb_version=run.mongodb_version,
        replica_set_name=run.replica_set_name,
    )
    action = strategy_for(install_method).build_step(step_name, host, spec)

    tasks_api = await _tasks_api_client()
    with tasks_api.auth(require_internal_token()):
        task_history_id = await dispatch_step(
            tasks_api, request, str(run.id), host, step_name, action
        )

    host_state.steps[step_index] = step.model_copy(
        update={
            "status": StepStatus.RUNNING,
            "started_at": utc_now(),
            "finished_at": None,
            "detail": None,
            "task_history_id": task_history_id,
        }
    )
    run.hosts = dump_host_states(states)
    run = await BootstrapRunManager.save(session, run)
    return _run_response(run)
