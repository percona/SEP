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

from fastapi import APIRouter, Query, Request
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
from app.sep.apps.om_bootstrap.crud import BootstrapRunManager, get_run, list_runs
from app.sep.apps.om_bootstrap.dispatch import dispatch_step
from app.sep.apps.om_bootstrap.models import BootstrapRun, BootstrapRunStatus
from app.sep.apps.om_bootstrap.persistence import (
    dump_host_states,
    dump_run_steps,
    parse_host_states,
    parse_run_steps,
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
    InstallStrategy,
    OperatingSystem,
    StepAction,
    StepRecord,
    StepStatus,
)
from app.sep.config import sep_settings
from app.sep.deps import SessionDep

#: BootstrapRunStatus members :func:`finish_run` accepts -- a caller declaring the
#: run itself decided to give up. SUCCEEDED is deliberately excluded: reconciling
#: a run to SUCCEEDED is a fact :func:`~app.sep.apps.om_bootstrap.reconcile.reconcile_run`
#: infers on its own (see its own docstring), never something a caller requests.
_FINISHABLE_STATUSES = frozenset(
    {BootstrapRunStatus.FAILED, BootstrapRunStatus.ROLLED_BACK}
)


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


class DispatchStepRequest(BaseModel):
    """Optional body for any ``:dispatch`` route.

    :param params: Per-dispatch values the step being dispatched needs but
        cannot compute itself -- a keyFile's content, a generated
        monitoring-user password. See
        :class:`~app.sep.apps.om_bootstrap.strategy.InstallStrategy`'s own
        docstring for why these are never persisted by ``om_bootstrap``: PMM's
        stepper holds their durable, encrypted copy (PMM-15347/questions.md Q7)
        and hands one to a single dispatch, transiently, through this field.
        Empty for a step that needs none.
    """

    params: dict[str, str] = {}


class FinishRunRequest(BaseModel):
    """Body for :func:`finish_run` -- the stepper recording its own decision.

    :param status: The run's new terminal status. Must be one of
        :data:`_FINISHABLE_STATUSES` -- :attr:`~app.sep.apps.om_bootstrap.models.BootstrapRunStatus.SUCCEEDED`
        is never requested here (see :data:`_FINISHABLE_STATUSES`'s own
        docstring).
    :param error: A human-readable reason, if any -- stored on
        :attr:`~app.sep.apps.om_bootstrap.models.BootstrapRun.error`.
    """

    status: BootstrapRunStatus
    error: str | None = None


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
        run-specific step list each host was planned with (forward steps and
        rollback steps both), not just the steps that have started
        (PMM-15347/plan.md §4 item 9).
    :param run_steps: This run's run-level steps
        (:meth:`~app.sep.apps.om_bootstrap.strategy.InstallStrategy.plan_run_steps`),
        planned up front the same way ``hosts``' steps are.
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
    run_steps: list[StepRecord]
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
        run_steps=parse_run_steps(run),
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


def _find_step(steps: list[StepRecord], step_name: str, *, what: str) -> int:
    """Return the index of ``step_name`` in ``steps``, or 404.

    Shared by every ``:dispatch`` route below -- a host's forward steps, its
    rollback steps, and a run's own run-level steps are all "find this name in
    a flat StepRecord list" the exact same way.

    :param steps: The steps to search.
    :param step_name: The name to find.
    :param what: A human-readable description of what was searched, for the
        404 detail (e.g. ``"host 'node00'"``).
    :raises HTTPNotFoundException: When no step in ``steps`` is named ``step_name``.
    :return: The index of the matching step.
    """
    index = next((i for i, step in enumerate(steps) if step.name == step_name), None)
    if index is None:
        raise HTTPNotFoundException(
            detail=f"Step {step_name!r} is not planned for {what}"
        )
    return index


def _require_not_running(step: StepRecord, step_name: str, *, what: str) -> None:
    """Raise 409 if ``step`` is already dispatching.

    :param step: The step to check.
    :param step_name: Its name, for the conflict detail.
    :param what: See :func:`_find_step`.
    :raises HTTPConflictException: When ``step.status`` is already
        :attr:`~app.sep.apps.om_bootstrap.strategy.StepStatus.RUNNING`.
    """
    if step.status == StepStatus.RUNNING:
        raise HTTPConflictException(
            detail=f"Step {step_name!r} for {what} is already running"
        )


async def _dispatch_and_record(
    tasks_api: RemoteAPI,
    request: Request,
    run_id: str,
    target_host: str,
    step_name: str,
    action: StepAction,
    step: StepRecord,
) -> StepRecord:
    """Dispatch ``action`` and return ``step`` updated to reflect it.

    Shared mechanics for every ``:dispatch`` route: only the lookup (see
    :func:`_find_step`) and the action-building differ between a per-host step,
    a rollback step, and a run-level step.

    :param tasks_api: The Tasks API client.
    :param request: The current request -- see :func:`~app.sep.apps.om_bootstrap.dispatch.dispatch_step`.
    :param run_id: The bootstrap run this step belongs to.
    :param target_host: The node name the dispatch actually runs on.
    :param step_name: The step's name.
    :param action: The step's built action.
    :param step: The step's current record, about to be dispatched.
    :return: A new :class:`~app.sep.apps.om_bootstrap.strategy.StepRecord`,
        ``RUNNING``, with :attr:`~app.sep.apps.om_bootstrap.strategy.StepRecord.attempt_count`
        incremented -- PMM's stepper reads this to enforce Adamo's decided retry
        policy (PMM-15347/questions.md Q8).
    """
    task_history_id = await dispatch_step(
        tasks_api, request, run_id, target_host, step_name, action
    )
    return step.model_copy(
        update={
            "status": StepStatus.RUNNING,
            "started_at": utc_now(),
            "finished_at": None,
            "detail": None,
            "task_history_id": task_history_id,
            "attempt_count": step.attempt_count + 1,
        }
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
            rollback_steps=[
                StepRecord(name=name) for name in strategy.plan_rollback_steps(spec)
            ],
        )
        for host in request.hosts
    ]
    run_steps = [StepRecord(name=name) for name in strategy.plan_run_steps(spec)]
    run = await BootstrapRunManager.save(
        session,
        BootstrapRun(
            install_method=to_models_install_method(request.install_method),
            os=to_models_os(request.os),
            mongodb_version=request.mongodb_version,
            replica_set_name=request.replica_set_name,
            hosts=dump_host_states(host_states),
            run_steps=dump_run_steps(run_steps),
        ),
    )
    return _run_response(run)


@router.get("/runs")
async def list_bootstrap_runs(
    session: SessionDep,
    status: BootstrapRunStatus | None = None,
    limit: int = Query(default=100, ge=1, le=100),
) -> list[RunResponse]:
    """Return runs, newest first, optionally narrowed to one status.

    The intended caller is PMM's HA-leader-only stepper (PMM-15347/plan.md §4
    item 9): it does not persist its own copy of which runs exist or where
    they are, so on every tick -- and especially right after a leader
    failover -- it re-discovers every run still in flight from here
    (``status=running``) rather than from any state of its own.

    :param session: The database session.
    :param status: Restrict to runs in this status. Omit for any status.
    :param limit: How many to return.
    :return: The runs. Does **not** reconcile in-flight steps -- unlike
        :func:`get_bootstrap_run`, a caller polling a specific run for the
        purpose of driving it forward should use that route instead.
    """
    return [
        _run_response(run)
        for run in await list_runs(session, status=status, limit=limit)
    ]


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


async def _get_run_or_404(session: SessionDep, run_id: UUID) -> BootstrapRun:
    """Return the run, or 404.

    :raises HTTPNotFoundException: When there is no such run.
    """
    run = await get_run(session, run_id)
    if run is None:
        raise HTTPNotFoundException(detail=f"Bootstrap run {run_id} not found")
    return run


def _spec_for(run: BootstrapRun) -> tuple[InstallStrategy, BootstrapSpec]:
    """Rebuild ``run``'s strategy and spec from its persisted, typed fields.

    :param run: The run to rebuild a spec for.
    :return: The run's strategy, and the spec it plans/builds steps from.
    """
    install_method = to_strategy_install_method(run.install_method)
    spec = BootstrapSpec(
        install_method=install_method,
        os=to_strategy_os(run.os),
        mongodb_version=run.mongodb_version,
        replica_set_name=run.replica_set_name,
    )
    return strategy_for(install_method), spec


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
    body: DispatchStepRequest | None = None,
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
    :param body: ``params`` this step needs -- see :class:`DispatchStepRequest`.
    :raises HTTPNotFoundException: When there is no such run, host, or step.
    :raises HTTPConflictException: When the step is already running.
    :return: The run, with the dispatched step now ``running``.
    """
    run = await _get_run_or_404(session, run_id)

    states = parse_host_states(run)
    host_state = next((state for state in states if state.host == host), None)
    if host_state is None:
        raise HTTPNotFoundException(detail=f"Host {host!r} is not part of run {run_id}")
    what = f"host {host!r}"
    step_index = _find_step(host_state.steps, step_name, what=what)
    step = host_state.steps[step_index]
    _require_not_running(step, step_name, what=what)

    strategy, spec = _spec_for(run)
    action = strategy.build_step(
        step_name, host, spec, body.params if body is not None else None
    )

    tasks_api = await _tasks_api_client()
    with tasks_api.auth(require_internal_token()):
        host_state.steps[step_index] = await _dispatch_and_record(
            tasks_api, request, str(run.id), host, step_name, action, step
        )

    run.hosts = dump_host_states(states)
    run = await BootstrapRunManager.save(session, run)
    return _run_response(run)


@router.post(
    "/runs/{run_id}/run-steps/{step_name}:dispatch",
    status_code=http_status.HTTP_202_ACCEPTED,
)
@require_minimum_role(UserRole.ADMIN)
async def dispatch_run_run_step(
    run_id: UUID,
    step_name: str,
    session: SessionDep,
    request: Request,
    body: DispatchStepRequest | None = None,
) -> RunResponse:
    """Dispatch one run-level step now, targeting the run's seed host.

    Same fire-and-forget shape as :func:`dispatch_run_step` -- see its own
    docstring. "Seed host" is ``run``'s first host, index 0, matching
    :meth:`~app.sep.apps.om_bootstrap.strategy.InstallStrategy.build_run_step`'s
    own convention for where a run-level step actually executes.

    This route does not check that every per-host step succeeded first --
    deciding *when* it is safe to call this is PMM's stepper's job, not this
    route's (see the module docstring).

    :param run_id: The run's id.
    :param step_name: The run-level step to dispatch -- one of the names the
        run was planned with.
    :param session: The database session.
    :param request: See :func:`dispatch_run_step`.
    :param body: ``params`` this step needs -- see :class:`DispatchStepRequest`.
    :raises HTTPNotFoundException: When there is no such run, run-level step, or
        the run has no hosts to target.
    :raises HTTPConflictException: When the step is already running.
    :return: The run, with the dispatched run-level step now ``running``.
    """
    run = await _get_run_or_404(session, run_id)

    states = parse_host_states(run)
    if not states:
        raise HTTPNotFoundException(detail=f"Run {run_id} has no hosts to target")
    seed_host = states[0].host

    run_steps = parse_run_steps(run)
    what = f"run {run_id}"
    step_index = _find_step(run_steps, step_name, what=what)
    step = run_steps[step_index]
    _require_not_running(step, step_name, what=what)

    strategy, spec = _spec_for(run)
    hosts = [state.host for state in states]
    action = strategy.build_run_step(
        step_name, hosts, spec, body.params if body is not None else None
    )

    tasks_api = await _tasks_api_client()
    with tasks_api.auth(require_internal_token()):
        run_steps[step_index] = await _dispatch_and_record(
            tasks_api, request, str(run.id), seed_host, step_name, action, step
        )

    run.run_steps = dump_run_steps(run_steps)
    run = await BootstrapRunManager.save(session, run)
    return _run_response(run)


@router.post(
    "/runs/{run_id}/hosts/{host}/rollback/{step_name}:dispatch",
    status_code=http_status.HTTP_202_ACCEPTED,
)
@require_minimum_role(UserRole.ADMIN)
async def dispatch_rollback_step(
    run_id: UUID,
    host: str,
    step_name: str,
    session: SessionDep,
    request: Request,
) -> RunResponse:
    """Dispatch one host's named rollback step now.

    Same fire-and-forget shape as :func:`dispatch_run_step`. Rollback steps take
    no ``params``: every :meth:`~app.sep.apps.om_bootstrap.strategy.InstallStrategy.build_rollback_step`
    a strategy defines only ever tears down what its own forward steps already
    wrote to the host, needing nothing new from the caller.

    Whether a host should be rolled back at all -- and, if so, whether to
    dispatch its rollback steps in order or all at once -- is PMM's stepper's
    call (Adamo's decided partial-failure policy, PMM-15347/questions.md Q8),
    not this route's; it only ever dispatches the one step it is asked to.

    :param run_id: The run's id.
    :param host: The host to roll back.
    :param step_name: The rollback step to dispatch -- one of the names the run
        was planned with.
    :param session: The database session.
    :param request: See :func:`dispatch_run_step`.
    :raises HTTPNotFoundException: When there is no such run, host, or rollback step.
    :raises HTTPConflictException: When the step is already running.
    :return: The run, with the dispatched rollback step now ``running``.
    """
    run = await _get_run_or_404(session, run_id)

    states = parse_host_states(run)
    host_state = next((state for state in states if state.host == host), None)
    if host_state is None:
        raise HTTPNotFoundException(detail=f"Host {host!r} is not part of run {run_id}")
    what = f"host {host!r}"
    step_index = _find_step(host_state.rollback_steps, step_name, what=what)
    step = host_state.rollback_steps[step_index]
    _require_not_running(step, step_name, what=what)

    _, spec = _spec_for(run)
    action = strategy_for(
        to_strategy_install_method(run.install_method)
    ).build_rollback_step(step_name, host, spec)

    tasks_api = await _tasks_api_client()
    with tasks_api.auth(require_internal_token()):
        host_state.rollback_steps[step_index] = await _dispatch_and_record(
            tasks_api, request, str(run.id), host, step_name, action, step
        )

    run.hosts = dump_host_states(states)
    run = await BootstrapRunManager.save(session, run)
    return _run_response(run)


@router.post("/runs/{run_id}:finish")
@require_minimum_role(UserRole.ADMIN)
async def finish_run(
    run_id: UUID, session: SessionDep, body: FinishRunRequest
) -> RunResponse:
    """Record the stepper's own decision that a run is done -- failed or rolled back.

    The one way ``run.status`` reaches :attr:`~app.sep.apps.om_bootstrap.models.BootstrapRunStatus.FAILED`
    or :attr:`~app.sep.apps.om_bootstrap.models.BootstrapRunStatus.ROLLED_BACK`:
    both are real calls only PMM's stepper makes (retries exhausted; rollback
    finished), never something ``om_bootstrap`` infers on its own -- see
    ``reconcile.py``'s module docstring for the one status it *does* infer
    (SUCCEEDED) and why that's different.

    :param run_id: The run's id.
    :param session: The database session.
    :param body: The decided terminal status, and why.
    :raises HTTPNotFoundException: When there is no such run.
    :raises HTTPBadRequestException: When ``body.status`` is not one of
        :data:`_FINISHABLE_STATUSES`.
    :raises HTTPConflictException: When the run is already terminal.
    :return: The run, now terminal.
    """
    run = await _get_run_or_404(session, run_id)
    if body.status not in _FINISHABLE_STATUSES:
        raise HTTPBadRequestException(
            detail=f"status must be one of {sorted(_FINISHABLE_STATUSES)}"
        )
    if run.status != BootstrapRunStatus.RUNNING:
        raise HTTPConflictException(
            detail=f"Run {run_id} is already {run.status.value}"
        )

    run.status = body.status
    run.finished_at = utc_now()
    run.error = body.error
    run = await BootstrapRunManager.save(session, run)
    return _run_response(run)
