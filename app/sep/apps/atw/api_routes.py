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
from pydantic import BaseModel

from app.core.pagination import PaginatedResponse
from app.core.pagination.deps import PaginationDep
from app.core.utils.iterators import unique_everseen
from app.sep.apps.atw.batch import (
    ATWBatchExecuteItemResponse,
    ATWBatchExecuteResponse,
    ATWBatchExecuteWrite,
    ATWIncidentExecutionResponse,
    ATWMergedSchemaResponse,
    ATWSnippetSchema,
    batch_execution_fields,
    dispatch_batch_item,
    fetch_task_history,
    MAX_BATCH_SNIPPETS,
    parameter_fields,
    resolve_snippet,
    shared_field_names,
)
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
from app.sep.deps import ApiCurrentUser, SessionDep, TaskAPI
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models import Snippet

logger = logging.getLogger(__name__)

ATW_META_KEY = "atw"
ATW_META_WARNING = (
    f"Ignoring meta[{ATW_META_KEY!r}] for snippet %s: expected list, got %s"
)
NO_TASK_ID_ERROR = "Dispatched, but the Tasks API returned no task id; not recorded."
UNRECORDED_EXECUTION_ERROR = "Dispatched, but the execution row could not be recorded"


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


@router.get("/execution-schema/")
async def atw_execution_schema(
    snippet_filename: Annotated[
        list[str],
        Query(
            min_length=1,
            max_length=MAX_BATCH_SNIPPETS,
            description="Snippet filenames to build a batch form for.",
        ),
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
        await resolve_snippet(filename)
        for filename in unique_everseen(snippet_filename)
    ]
    fields_per_script = [parameter_fields(script) for script in scripts]

    declarations = defaultdict(list)
    for fields in fields_per_script:
        for field in fields:
            declarations[field.name].append(field)
    shared_names = shared_field_names(declarations)

    shared = batch_execution_fields(scripts)
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


def _failure_detail(exc: Exception) -> str | list[dict[str, Any]]:
    """Return the client-facing detail for a failed batch item.

    :param exc: The exception that ended the item.
    :return: The exception's HTTP detail, or its message for a transport error.
    """
    return cast(
        "str | list[dict[str, Any]]",
        exc.detail if isinstance(exc, HTTPException) else str(exc),
    )


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

    The row-write guard rolls the shared session back before the loop continues,
    or one failed write would leave the transaction aborted and doom every later
    item on PostgreSQL; the dispatch guard rolls back defensively, having written
    nothing itself. ``incident.id`` is read once up front because both a commit and
    a rollback expire the instance, and re-reading it would trigger a lazy load.

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
            dispatched = await dispatch_batch_item(body, item, tasks_api)
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
            fetch_task_history(tasks_api, execution.task_history_id)
            for execution in page.items
        )
    )
    items = [
        _build_execution_response(execution, history)
        for execution, history in zip(page.items, histories, strict=True)
    ]
    return PaginatedResponse.from_pagination(items, page.total, pagination)
