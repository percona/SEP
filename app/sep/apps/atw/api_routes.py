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

"""Define the JSON API router for the ATW plugin."""

import asyncio
import logging
from collections import defaultdict
from typing import Annotated, Any, cast

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, UUID4

from app.core.pagination import PaginatedResponse
from app.core.pagination.deps import PaginationDep
from app.core.requests import RemoteAPI
from app.core.utils.fields import NonEmptyStr, UTCDatetime
from app.core.utils.iterators import unique_everseen
from app.sep.apps.atw.categories import (
    ATWCategory,
    CATEGORY_ROOT_LABELS,
    derive_category_root,
)
from app.sep.apps.atw.crud import AtwIncidentExecutionManager, AtwIncidentManager
from app.sep.apps.atw.deps import AtwIncidentDep
from app.sep.apps.atw.models import (
    AtwIncident,
    AtwIncidentExecution,
    AtwIncidentResponse,
    AtwIncidentUpdate,
    AtwIncidentWrite,
)
from app.sep.apps.atw.schema import atw_schema
from app.sep.apps.framework.api import schema_endpoint
from app.sep.apps.framework.schema import AnyField, BoolField, HostField
from app.sep.apps.framework.script_helpers import execute_script
from app.sep.apps.framework.script_source import (
    ARBITRARY_ARGS_SCHEMA,
    make_script_dep,
    ScriptExecuteWrite,
    ScriptExecutionResponse,
)
from app.sep.apps.labels import EXECUTION_HOST_LABEL
from app.sep.apps.snippets.schema import (
    EXECUTOR_HOST_FIELD_NAME,
    SCRIPT_PREVIEW_FIELD_NAME,
    SUDO_FIELD_NAME,
)
from app.sep.apps.snippets.script_source import snippet_source, SnippetScript
from app.sep.deps import ApiCurrentUser, SessionDep, TaskAPI
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models import Snippet
from app.tasks.models import TaskHistoryStatusEnum

logger = logging.getLogger(__name__)

ATW_META_KEY = "atw"
ATW_META_WARNING = (
    f"Ignoring meta[{ATW_META_KEY!r}] for snippet %s: expected list, got %s"
)
ATW_HYDRATION_WARNING = (
    "Task history %s could not be hydrated for the ATW incident page"
)
NO_TASK_ID_ERROR = "Dispatched, but the Tasks API returned no task id; not recorded."
UNRECORDED_EXECUTION_ERROR = "Dispatched, but the execution row could not be recorded"

_MIN_SHARED_DECLARERS = 2
_SYNTHETIC_FIELD_NAMES = frozenset(
    {EXECUTOR_HOST_FIELD_NAME, SUDO_FIELD_NAME, SCRIPT_PREVIEW_FIELD_NAME}
)
_resolve_snippet = make_script_dep(snippet_source)


class ATWSnippetSummary(BaseModel):
    """Represent one snippet entry under an ATW category.

    :param name: The snippet filename, used as its API identifier.
    :type name: str
    :param title: The snippet display title.
    :type title: str
    :param description: The snippet free-text description.
    :type description: str
    """

    name: str
    title: str
    description: str


class ATWCategoryListing(BaseModel):
    """Represent one ATW category row and its snippet members.

    :param category_root: The top-level product/category root.
    :type category_root: str
    :param parent_category: The parent category enum name.
    :type parent_category: str
    :param parent_category_label: The parent category display label.
    :type parent_category_label: str
    :param category: The ATW leaf category enum name.
    :type category: str
    :param category_label: The ATW leaf category display label.
    :type category_label: str
    :param snippet_count: Number of snippets in this category.
    :type snippet_count: int
    :param snippets: Snippet summaries belonging to this category.
    :type snippets: list[ATWSnippetSummary]
    """

    category_root: str
    parent_category: str
    parent_category_label: str
    category: str
    category_label: str
    snippet_count: int
    snippets: list[ATWSnippetSummary]


class ATWSnippetSchema(BaseModel):
    """Represent the fields one selected snippet still owns after merging.

    :param snippet_filename: The snippet the remaining fields belong to.
    :param fields: The snippet's parameter fields that did not merge into the
        shared section.
    """

    snippet_filename: NonEmptyStr
    fields: list[AnyField]


class ATWMergedSchemaResponse(BaseModel):
    """Represent the execution form for a batch of selected snippets.

    A purpose-built DTO rather than a plain
    :class:`~app.sep.apps.framework.schema.AppSchema`: the renderer needs to map
    every non-shared field back to the snippet that declared it, and an
    ``AppSchema`` section carries only a display title.

    :param shared: The batch-level execution fields followed by every parameter
        the selection declares identically.
    :param per_snippet: The remaining per-snippet fields, in request order.
    """

    shared: list[AnyField]
    per_snippet: list[ATWSnippetSchema]


class ATWBatchExecuteItemWrite(BaseModel):
    """Define one snippet execution within a batch.

    :param snippet_filename: The snippet to execute.
    :param args: Per-snippet arguments keyed by frontmatter parameter name;
        they override same-named entries in the batch's ``shared_args``.
    """

    snippet_filename: NonEmptyStr
    args: dict[str, Any] = Field(default={}, json_schema_extra=ARBITRARY_ARGS_SCHEMA)


class ATWBatchExecuteWrite(BaseModel):
    """Define the batch-execute payload for one incident.

    :param executor_host: The executor every item in the batch runs on.
    :param sudo: The sudo choice applied to every item; snippets whose sudo
        option is not optional ignore it.
    :param shared_args: Arguments offered to every item, filtered per snippet to
        the parameters that snippet declares.
    :param items: The snippets to execute, at least one.
    """

    executor_host: NonEmptyStr = Field(title=EXECUTION_HOST_LABEL)
    sudo: bool = False
    shared_args: dict[str, Any] = Field(
        default={}, json_schema_extra=ARBITRARY_ARGS_SCHEMA
    )
    items: list[ATWBatchExecuteItemWrite] = Field(min_length=1)


class ATWBatchExecuteItemResponse(BaseModel):
    """Describe the outcome of one item in a batch execution.

    :param snippet_filename: The snippet this item requested.
    :param task_name: The Tasks-API task name the snippet dispatched under, when
        the dispatch itself succeeded.
    :param task_history_id: The created task-history id, when the Tasks API
        returned one.
    :param error: The failure detail when the item did not complete — a message
        or a validation-error list, depending on what rejected it.
    """

    snippet_filename: NonEmptyStr
    task_name: NonEmptyStr | None = None
    task_history_id: int | None = None
    error: Any | None = None


class ATWBatchExecuteResponse(BaseModel):
    """Collect every item's outcome for one batch execution.

    Partial success lives in the body: the request is created (``201``) whenever
    the incident resolves, and each item carries its own dispatch result or error.

    :param items: One entry per requested item, in request order.
    """

    items: list[ATWBatchExecuteItemResponse]


class ATWIncidentExecutionResponse(BaseModel):
    """Represent one recorded incident execution, hydrated with live task status.

    The hydrated fields are ``None`` when the Tasks API could not be reached for
    that row; the locally-recorded fields are always present.

    :param id: The execution row's UUID primary key.
    :param snippet_filename: The executed snippet's filename.
    :param task_history_id: The tasks-service execution this row references.
    :param created_at: When the execution was recorded.
    :param task_status: The upstream execution status.
    :param started_at: When the upstream execution started.
    :param finished_at: When the upstream execution finished.
    :param has_logs: Whether the upstream execution has readable logs.
    """

    id: UUID4
    snippet_filename: str
    task_history_id: int
    created_at: UTCDatetime
    task_status: TaskHistoryStatusEnum | None = None
    started_at: UTCDatetime | None = None
    finished_at: UTCDatetime | None = None
    has_logs: bool | None = None


router = APIRouter()
schema_endpoint(router=router, plugin_schema=atw_schema)


def _build_summary(snippet: Snippet) -> ATWSnippetSummary:
    return ATWSnippetSummary(
        name=snippet.filename,
        title=snippet.title,
        description=snippet.description,
    )


@router.get("/")
async def atw_api_list(session: SessionDep) -> list[ATWCategoryListing]:
    """List ATW-tagged snippets grouped by category.

    Categories with no matching snippets are omitted to keep the payload small;
    the ATW enum still defines the full taxonomy for validation (plugin schema).

    :param session: The database session.
    :return: One listing row per category that has at least one snippet.
    """
    snippets = await SnippetManager.list(session)
    snippets_by_cell = defaultdict(list)
    for snippet in snippets:
        root = derive_category_root(snippet.meta.get("service_type"))
        tags = []
        if ATW_META_KEY in snippet.meta:
            raw_atw = snippet.meta[ATW_META_KEY]
            if isinstance(raw_atw, list):
                tags = raw_atw
            else:
                logger.warning(
                    ATW_META_WARNING,
                    snippet.filename,
                    type(raw_atw).__name__,
                )
        for tag in dict.fromkeys(tags):
            snippets_by_cell[(root, tag)].append(snippet)

    grouped = []
    for root_label in CATEGORY_ROOT_LABELS.values():
        for category in ATWCategory:
            cell_snippets = snippets_by_cell.get((root_label, category.name), [])
            if not cell_snippets:
                continue
            category_snippets = [_build_summary(snippet) for snippet in cell_snippets]
            grouped.append(
                ATWCategoryListing(
                    category_root=root_label,
                    parent_category=category.parent.name,
                    parent_category_label=category.parent.value,
                    category=category.name,
                    category_label=category.value,
                    snippet_count=len(category_snippets),
                    snippets=category_snippets,
                )
            )

    return grouped


@router.post("/incidents/", status_code=status.HTTP_201_CREATED)
async def atw_create_incident(
    session: SessionDep,
    current_user: ApiCurrentUser,
    body: AtwIncidentWrite,
) -> AtwIncidentResponse:
    """Create a diagnostic incident owned by the current user.

    :param session: The database session.
    :param current_user: The authenticated user, stamped as ``created_by``.
    :param body: The incident create payload.
    :return: The created incident.
    """
    incident = AtwIncident(**body.model_dump(), created_by=current_user.username)
    saved = await AtwIncidentManager.save(session, incident)
    return AtwIncidentResponse.model_validate(saved)


@router.get("/incidents/")
async def atw_list_incidents(
    session: SessionDep, pagination: PaginationDep
) -> PaginatedResponse[AtwIncidentResponse]:
    """List diagnostic incidents, newest first.

    :param session: The database session.
    :param pagination: The offset/limit window for the page.
    :return: A paginated page of incidents, newest first.
    """
    page = await AtwIncidentManager.list_paginated(session, pagination=pagination)
    items = [AtwIncidentResponse.model_validate(incident) for incident in page.items]
    return PaginatedResponse.from_pagination(items, page.total, pagination)


@router.get("/incidents/{incident_id}")
async def atw_get_incident(incident: AtwIncidentDep) -> AtwIncidentResponse:
    """Retrieve a single diagnostic incident by id.

    :param incident: The incident resolved from the ``incident_id`` path parameter.
    :return: The matching incident.
    """
    return AtwIncidentResponse.model_validate(incident)


@router.patch("/incidents/{incident_id}")
async def atw_update_incident(
    session: SessionDep, incident: AtwIncidentDep, body: AtwIncidentUpdate
) -> AtwIncidentResponse:
    """Update a diagnostic incident's name or support-case reference.

    :param session: The database session.
    :param incident: The incident resolved from the ``incident_id`` path parameter.
    :param body: The partial update payload; unset fields are untouched.
    :return: The updated incident.
    """
    updated = await AtwIncidentManager.update(session, incident, body)
    return AtwIncidentResponse.model_validate(updated)


@router.delete(
    "/incidents/{incident_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def atw_delete_incident(session: SessionDep, incident: AtwIncidentDep) -> None:
    """Delete a diagnostic incident and cascade its execution rows.

    :param session: The database session.
    :param incident: The incident resolved from the ``incident_id`` path parameter.
    """
    await AtwIncidentManager.delete(session, incident)


def _parameter_fields(script: SnippetScript) -> list[AnyField]:
    """Return a snippet's parameter fields, without the synthetic execution ones.

    The per-snippet schema appends an executor-host selector, a sudo toggle, and a
    script-preview pane to the frontmatter parameters. Those are batch-level or
    presentational, so a merged batch form owns them once (or not at all) rather
    than repeating them per snippet.

    :param script: The resolved snippet whose form schema is flattened.
    :return: Every parameter field the snippet declares, in schema order.
    """
    return [
        field
        for section in snippet_source.build_form_schema(script).forms
        for field in section.fields
        if field.name not in _SYNTHETIC_FIELD_NAMES
    ]


def _batch_execution_fields(scripts: list[SnippetScript]) -> list[AnyField]:
    """Build the batch-level execution fields the whole selection shares.

    These mirror :class:`ATWBatchExecuteWrite`'s own ``executor_host`` / ``sudo``
    inputs, so they are shared by construction rather than by the merge rule. One
    toggle drives the whole batch, so it starts checked only when *every*
    optional-sudo snippet in the selection would start checked on its own form —
    a selection that disagrees falls back to unchecked rather than silently
    escalating the snippets that default to no sudo.

    :param scripts: The resolved snippets the batch form covers.
    :return: The executor-host field, plus a sudo toggle when at least one
        selected snippet leaves sudo to the caller.
    """
    fields = [
        cast(
            AnyField,
            HostField(
                name=EXECUTOR_HOST_FIELD_NAME,
                label=EXECUTION_HOST_LABEL,
                required=True,
            ),
        )
    ]
    optional_sudo = [script for script in scripts if script.snippet.sudo.is_optional]
    if optional_sudo:
        fields.append(
            cast(
                AnyField,
                BoolField(
                    name=SUDO_FIELD_NAME,
                    label="Run with sudo",
                    default=all(
                        script.snippet.sudo.sudo_default for script in optional_sudo
                    ),
                    description=(
                        "Prepend sudo to the interpreter for every snippet in the "
                        "batch that leaves sudo optional."
                    ),
                ),
            )
        )
    return fields


def _shared_field_names(declarations: dict[str, list[AnyField]]) -> set[str]:
    """Return the parameter names that merge into the batch's shared section.

    A parameter merges only when two or more selected snippets declare it *and*
    every declaration serialises identically — the wire form is what the renderer
    consumes, so byte-identity there is the sharing contract. Cosmetically similar
    but differing declarations (a per-product default, a required-vs-optional
    divergence) stay per-snippet, where they mean different things.

    :param declarations: Every declaration of each parameter name, keyed by name.
    :return: The names whose declarations are unanimous across two or more snippets.
    """
    shared = set()
    for name, fields in declarations.items():
        if len(fields) < _MIN_SHARED_DECLARERS:
            continue
        dumps = [field.model_dump(by_alias=True) for field in fields]
        if all(dump == dumps[0] for dump in dumps[1:]):
            shared.add(name)
    return shared


@router.get("/execution-schema/")
async def atw_execution_schema(
    snippet_filename: Annotated[
        list[str],
        Query(min_length=1, description="Snippet filenames to build a batch form for."),
    ],
) -> ATWMergedSchemaResponse:
    """Build one execution form covering several snippets, merging common parameters.

    Unknown or unsafe filenames fail the whole request — a form the caller cannot
    fill for every selected snippet is not a partial success.

    :param snippet_filename: The selected snippet filenames, repeated per snippet
        and deduplicated order-preserving.
    :return: The shared section followed by each snippet's remaining fields.
    :raises HTTPBadRequestException: When a filename attempts directory traversal.
    :raises HTTPNotFoundException: When a filename matches no snippet.
    """
    scripts = [
        await _resolve_snippet(filename)
        for filename in unique_everseen(snippet_filename)
    ]
    fields_per_script = [_parameter_fields(script) for script in scripts]

    declarations = defaultdict(list)
    for fields in fields_per_script:
        for field in fields:
            declarations[field.name].append(field)
    shared_names = _shared_field_names(declarations)

    shared = _batch_execution_fields(scripts)
    shared += [
        fields[0] for name, fields in declarations.items() if name in shared_names
    ]
    return ATWMergedSchemaResponse(
        shared=shared,
        per_snippet=[
            ATWSnippetSchema(
                snippet_filename=script.filename,
                fields=[field for field in fields if field.name not in shared_names],
            )
            for script, fields in zip(scripts, fields_per_script, strict=True)
        ],
    )


async def _dispatch_batch_item(
    body: ATWBatchExecuteWrite,
    item: ATWBatchExecuteItemWrite,
    tasks_api: RemoteAPI,
) -> ScriptExecutionResponse:
    """Resolve one batch item, narrow the shared args to it, and dispatch it.

    Shared arguments are filtered to the parameters the snippet actually declares,
    so a batch may offer a value no single snippet accepts, and the item's own
    ``args`` then override what remains.

    :param body: The batch payload supplying the executor host, sudo choice, and
        shared arguments.
    :param item: The item naming the snippet and its own argument overrides.
    :param tasks_api: The authenticated Tasks API client.
    :return: The dispatched task name, the created task-history id (``None`` when
        the Tasks API returned none), and the resolved snippet filename.
    :raises HTTPException: When the snippet cannot be resolved, its arguments fail
        validation, it is not executable, or the Tasks API returns an error status.
    :raises OSError: Propagated from ``execute_script`` when the Tasks API
        transport itself fails.
    """
    script = await _resolve_snippet(item.snippet_filename)
    declared = {field.name for field in _parameter_fields(script)}
    args = {name: value for name, value in body.shared_args.items() if name in declared}
    args.update(item.args)
    return await execute_script(
        snippet_source,
        script,
        ScriptExecuteWrite(executor_host=body.executor_host, sudo=body.sudo, args=args),
        tasks_api,
    )


def _failure_detail(exc: Exception) -> Any:
    """Return the client-facing detail for a failed batch item.

    :param exc: The exception that ended the item.
    :return: The exception's HTTP detail, or its message for a transport error.
    """
    return exc.detail if isinstance(exc, HTTPException) else str(exc)


@router.post(
    "/incidents/{incident_id}/executions/", status_code=status.HTTP_201_CREATED
)
async def atw_batch_execute(
    session: SessionDep,
    incident: AtwIncidentDep,
    body: ATWBatchExecuteWrite,
    tasks_api: TaskAPI,
) -> ATWBatchExecuteResponse:
    """Execute several snippets against one incident, reporting each item separately.

    One failing item never blocks the rest: each is dispatched and recorded inside
    its own guard, and the response always carries an entry per requested item. A
    failed attempt produces no task-history row to reference, so it is reported
    here rather than persisted.

    Every per-item guard rolls the shared session back before the loop continues,
    or one failed write would leave the transaction aborted and doom every later
    item on PostgreSQL. ``incident.id`` is read once up front for the same reason:
    a rollback expires the instance, and re-reading it would trigger a lazy load.

    :param session: The database session.
    :param incident: The incident resolved from the ``incident_id`` path parameter.
    :param body: The batch payload.
    :param tasks_api: The authenticated Tasks API client.
    :return: One outcome entry per requested item, in request order.
    """
    incident_id = incident.id
    items = []
    for item in body.items:
        try:
            dispatched = await _dispatch_batch_item(body, item, tasks_api)
        except (HTTPException, OSError) as exc:
            await session.rollback()
            items.append(
                ATWBatchExecuteItemResponse(
                    snippet_filename=item.snippet_filename,
                    error=_failure_detail(exc),
                )
            )
            continue
        if dispatched.task_id is None:
            items.append(
                ATWBatchExecuteItemResponse(
                    snippet_filename=item.snippet_filename,
                    task_name=dispatched.task_name,
                    error=NO_TASK_ID_ERROR,
                )
            )
            continue
        try:
            await AtwIncidentExecutionManager.save(
                session,
                AtwIncidentExecution(
                    incident_id=incident_id,
                    task_history_id=dispatched.task_id,
                    snippet_filename=dispatched.snippet_filename,
                ),
            )
        except (HTTPException, OSError) as exc:
            await session.rollback()
            items.append(
                ATWBatchExecuteItemResponse(
                    snippet_filename=item.snippet_filename,
                    task_name=dispatched.task_name,
                    task_history_id=dispatched.task_id,
                    error=f"{UNRECORDED_EXECUTION_ERROR}: {_failure_detail(exc)}",
                )
            )
            continue
        items.append(
            ATWBatchExecuteItemResponse(
                snippet_filename=item.snippet_filename,
                task_name=dispatched.task_name,
                task_history_id=dispatched.task_id,
            )
        )
    return ATWBatchExecuteResponse(items=items)


async def _fetch_task_history(
    tasks_api: RemoteAPI, task_history_id: int
) -> dict[str, Any]:
    """Fetch one task-history row, degrading an upstream failure to no data.

    Mirrors the topology page's fan-out over the same endpoint, but keeps the page
    alive when a single row cannot be hydrated: a deleted or unreachable execution
    should blank that row's live fields, not fail the whole listing.

    :param tasks_api: The authenticated Tasks API client.
    :param task_history_id: The execution to look up.
    :return: The upstream task-history payload, or an empty mapping on failure.
    """
    try:
        return await tasks_api.get(f"/history/{task_history_id}")
    except (HTTPException, OSError):
        logger.warning(ATW_HYDRATION_WARNING, task_history_id, exc_info=True)
        return {}


def _build_execution_response(
    execution: AtwIncidentExecution, history: dict[str, Any]
) -> ATWIncidentExecutionResponse:
    """Merge a recorded execution row with its upstream task-history payload.

    :param execution: The locally-recorded execution row.
    :param history: The upstream task-history payload, empty when unavailable.
    :return: The combined execution response.
    """
    return ATWIncidentExecutionResponse(
        id=execution.id,
        snippet_filename=execution.snippet_filename,
        task_history_id=execution.task_history_id,
        created_at=execution.created_at,
        task_status=history.get("status"),
        started_at=history.get("started_at"),
        finished_at=history.get("finished_at"),
        has_logs=history.get("has_logs"),
    )


@router.get("/incidents/{incident_id}/executions/")
async def atw_list_incident_executions(
    session: SessionDep,
    incident: AtwIncidentDep,
    pagination: PaginationDep,
    tasks_api: TaskAPI,
) -> PaginatedResponse[ATWIncidentExecutionResponse]:
    """List one incident's snippet executions, newest first, with live task status.

    :param session: The database session.
    :param incident: The incident resolved from the ``incident_id`` path parameter.
    :param pagination: The offset/limit window for the page.
    :param tasks_api: The authenticated Tasks API client.
    :return: A paginated page of executions hydrated from the Tasks API.
    """
    page = await AtwIncidentExecutionManager.list_paginated(
        session, pagination=pagination, incident_id=incident.id
    )
    histories = await asyncio.gather(
        *(
            _fetch_task_history(tasks_api, execution.task_history_id)
            for execution in page.items
        )
    )
    items = [
        _build_execution_response(execution, history)
        for execution, history in zip(page.items, histories, strict=True)
    ]
    return PaginatedResponse.from_pagination(items, page.total, pagination)
