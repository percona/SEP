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

"""Define the JSON API router for the Snippets plugin.

Mounted at ``/api/plugins/snippets/`` via ``plugins_router`` in
``app/sep/api/router.py``. Authentication is enforced at the ``api_router``
level and redeclared per route for safety. Route layout is snippet-centric:

* ``GET /schema``                              — static plugin schema
* ``GET /``                                    — list snippets
* ``GET /{snippet_filename}/schema``           — per-snippet form schema
* ``GET /{snippet_filename}/script-preview``   — script preview
* ``GET /{snippet_filename}/history``          — execution history
* ``POST /{snippet_filename}/execute``         — execute the snippet

All dynamic segments live under two-segment ``/{snippet_filename}/...``
paths; there is no single-segment dynamic catch-all, so the static
``/schema`` and ``/`` routes are unambiguous.
"""

import logging

from fastapi import APIRouter, HTTPException
from fastapi import status as http_status
from pydantic import ValidationError

from app.core.exceptions import HTTPUnprocessableEntityException
from app.sep.deps import IsApiAuthenticated, SessionDep, TaskAPI
from app.sep.plugins.framework.api import schema_endpoint
from app.sep.plugins.framework.schema import PluginSchema
from app.sep.plugins.snippets.deps import (
    build_snippet_execution_meta,
    ExecutableSnippetForApi,
    SnippetDep,
    SnippetSource,
)
from app.sep.plugins.snippets.models import (
    ScriptPreviewResponse,
    SnippetExecutionHistoryItem,
    SnippetExecutionRequest,
    SnippetExecutionResponse,
    SnippetResponse,
)
from app.sep.plugins.snippets.schema import (
    build_snippet_schema,
    SNIPPETS_PLUGIN_SCHEMA,
)
from app.sep.snippets.config import SnippetSudoOption
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models.snippet import EXECUTOR_HOSTS_INPUT_NAME, Snippet
from app.sep.snippets.utils import guess_mime_type, mime_type_to_highlighter_language

logger = logging.getLogger(__name__)

router = APIRouter()
schema_endpoint(router=router, plugin_schema=SNIPPETS_PLUGIN_SCHEMA)


def _build_snippet_response(snippet: Snippet) -> SnippetResponse:
    """Project a :class:`Snippet` into its API response shape."""
    return SnippetResponse(
        filename=snippet.filename,
        title=snippet.title,
        description=snippet.description,
        size=snippet.size,
        md5_digest=snippet.md5_digest,
        is_approved=snippet.is_approved,
        approved_at=snippet.approved_at,
        reason=snippet.reason,
        requires_sudo=(
            snippet.sudo == SnippetSudoOption.ALWAYS or snippet.sudo.is_optional
        ),
        sudo_optional=snippet.sudo.is_optional,
        sudo_default=snippet.sudo.sudo_default,
        interpreter=snippet.execution_interpreter,
        created_at=snippet.created_at,
        updated_at=snippet.updated_at,
    )


@router.get("/", dependencies=[IsApiAuthenticated])
async def snippets_api_list(session: SessionDep) -> list[SnippetResponse]:
    """List every currently-discovered snippet entity.

    :return: One :class:`SnippetResponse` per snippet row in the database.
    :rtype: list[SnippetResponse]
    """
    snippets = await SnippetManager.list(session)
    return [_build_snippet_response(snippet) for snippet in snippets]


@router.get(
    "/{snippet_filename}/schema",
    response_model_by_alias=True,
    dependencies=[IsApiAuthenticated],
)
async def snippets_api_per_snippet_schema(snippet: SnippetDep) -> PluginSchema:
    """Return the per-snippet form schema synthesised from snippet metadata.

    :param snippet: The snippet whose schema is requested.
    :type snippet: Snippet
    :return: The validated per-snippet plugin schema.
    :rtype: PluginSchema
    """
    return build_snippet_schema(snippet)


@router.get(
    "/{snippet_filename}/script-preview",
    dependencies=[IsApiAuthenticated],
)
async def snippets_api_script_preview(snippet: SnippetDep) -> ScriptPreviewResponse:
    """Return the snippet's preview content with a highlighter language hint.

    :param snippet: The snippet whose preview is requested.
    :type snippet: Snippet
    :return: The preview content alongside metadata about it.
    :rtype: ScriptPreviewResponse
    :raises HTTPUnprocessableEntityException: When the snippet contains
        bytes that cannot be decoded as UTF-8.
    """
    try:
        preview = await snippet.get_preview()
    except UnicodeDecodeError as exc:
        raise HTTPUnprocessableEntityException(
            detail=(
                f"Snippet {snippet.filename!r} contains non-UTF-8 bytes; "
                "preview is unavailable."
            ),
        ) from exc
    return ScriptPreviewResponse(
        content=preview.full_content,
        language=mime_type_to_highlighter_language(guess_mime_type(snippet.path)),
        is_truncated=preview.is_truncated,
    )


@router.get(
    "/{snippet_filename}/history",
    dependencies=[IsApiAuthenticated],
)
async def snippets_api_history(
    snippet: SnippetDep, tasks_api: TaskAPI
) -> list[SnippetExecutionHistoryItem]:
    """Return the execution history rows for a single snippet.

    Mirrors the legacy Jinja2 detail page's history fetch.

    :param snippet: The snippet whose history is requested.
    :type snippet: Snippet
    :param tasks_api: Async client for the tasks sub-app.
    :type tasks_api: RemoteAPI
    :return: One :class:`SnippetExecutionHistoryItem` per matching task
        history row.
    :rtype: list[SnippetExecutionHistoryItem]
    """
    response = await tasks_api.get(
        f"/{snippet.execution_task_name}/history/",
        params={"snippet_filename": snippet.filename},
    )
    items = []
    for entry in response["items"]:
        try:
            files = await tasks_api.get(f"/history/{entry['id']}/files/")
        except HTTPException:
            logger.debug(
                "Could not fetch available files for task history %s",
                entry["id"],
                exc_info=True,
            )
            files = []
        items.append(
            SnippetExecutionHistoryItem(
                task_id=entry["id"],
                status=entry["status"],
                created_at=entry["created_at"],
                created_by=entry.get("created_by"),
                available_files=files,
            ),
        )
    return items


@router.post(
    "/{snippet_filename}/execute",
    status_code=http_status.HTTP_201_CREATED,
    dependencies=[IsApiAuthenticated],
)
async def snippets_api_execute(
    snippet: ExecutableSnippetForApi,
    body: SnippetExecutionRequest,
    tasks_api: TaskAPI,
    snippet_source: SnippetSource,
) -> SnippetExecutionResponse:
    """Execute a snippet against the tasks API.

    Mirrors the legacy ``POST /{snippet_filename}`` Jinja2 route, but
    accepts a JSON body and returns a structured response pointing at
    the created task.

    :param snippet: The snippet being executed.
    :type snippet: Snippet
    :param body: The validated JSON request body.
    :type body: SnippetExecutionRequest
    :param tasks_api: Async client for the tasks sub-app.
    :type tasks_api: RemoteAPI
    :param snippet_source: Signed URL the executor uses to download the
        snippet artifact.
    :type snippet_source: str
    :return: The structured response describing the created task.
    :rtype: SnippetExecutionResponse
    :raises HTTPUnprocessableEntityException: When the per-snippet args
        fail dynamic validation.
    """
    execution_model = snippet.get_execution_model()
    raw_args = {
        **body.args,
        EXECUTOR_HOSTS_INPUT_NAME: body.executor_host,
    }
    if snippet.sudo.is_optional:
        raw_args.setdefault("sudo", body.sudo)
    try:
        execution_args = execution_model.model_validate(raw_args)
    except ValidationError as exc:
        raise HTTPUnprocessableEntityException(detail=exc.errors()) from exc

    execution_meta = build_snippet_execution_meta(
        snippet,
        execution_args,
        snippet_source,
    )
    logger.info(
        "Executing [%s] snippet %r with args: %r",
        execution_meta.interpreter,
        snippet.filename,
        execution_meta.args,
    )
    created = await tasks_api.post(
        f"/execute/{snippet.execution_task_name}",
        json={
            "meta": execution_meta.model_dump(by_alias=True, exclude_none=True),
        },
    )
    return SnippetExecutionResponse(
        task_name=snippet.execution_task_name,
        task_id=created.get("id") if isinstance(created, dict) else None,
        snippet_filename=snippet.filename,
    )
