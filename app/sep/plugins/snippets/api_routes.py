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
from typing import Any

from fastapi import APIRouter, Response
from fastapi import status as http_status
from pydantic import ValidationError
from sqlmodel import col

from app.core.exceptions import (
    HTTPBadRequestException,
    HTTPUnprocessableEntityException,
)
from app.core.utils import utc_now
from app.sep.deps import ApiAdminUser, IsApiAuthenticated, SessionDep, TaskAPI
from app.sep.plugins.framework.api import schema_endpoint
from app.sep.plugins.framework.schema import PluginSchema
from app.sep.plugins.snippets.deps import (
    build_snippet_execution_meta,
    check_snippet_batch_existence,
    ExecutableSnippetForApi,
    SnippetDep,
    SnippetSource,
)
from app.sep.plugins.snippets.models import (
    BatchApprovalErrorResponse,
    BatchApprovalResponse,
    ScriptPreviewResponse,
    SnippetApprovalResponse,
    SnippetBatchApproveRequest,
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
    response_model=PluginSchema,
    response_model_by_alias=True,
    response_model_exclude_none=True,
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
) -> dict[str, Any]:
    """Return the paginated execution history rows for a single snippet.

    Filters the canonical task-history endpoint by ``snippet_filename`` so
    the React detail page can pass the result straight into the shared
    ``TaskHistoryTable`` component without re-projecting fields.

    :param snippet: The snippet whose history is requested.
    :type snippet: Snippet
    :param tasks_api: Async client for the tasks sub-app.
    :type tasks_api: RemoteAPI
    :return: The upstream paginated task-history response (``items``,
        ``total``, ``offset``, ``limit``).
    :rtype: dict[str, Any]
    """
    return await tasks_api.get(
        f"/{snippet.execution_task_name}/history/",
        params={"snippet_filename": snippet.filename},
    )


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


def _build_approval_response(snippet: Snippet) -> SnippetApprovalResponse:
    """Project a :class:`Snippet` into its approval-state response shape."""
    return SnippetApprovalResponse(
        filename=snippet.filename,
        is_approved=snippet.is_approved,
        approved_at=snippet.approved_at,
        updated_by=snippet.updated_by,
        reason=snippet.reason,
    )


@router.put("/{snippet_filename}/approval")
async def snippets_api_approve(
    snippet: SnippetDep, user: ApiAdminUser, session: SessionDep
) -> SnippetApprovalResponse:
    """Approve a single snippet (idempotent).

    Re-approving an already-approved snippet returns ``200`` with the
    current state — ``approved_at`` is *not* overwritten so the audit
    trail is preserved.

    :param snippet: The snippet whose approval is being set.
    :type snippet: Snippet
    :param user: The authenticated admin performing the action.
    :type user: User
    :param session: The active database session.
    :type session: AsyncSession
    :return: The snippet's approval state after the call.
    :rtype: SnippetApprovalResponse
    """
    if not snippet.is_approved:
        snippet.approve(f"Approved by {user.username}", str(user.id))
        await SnippetManager.save(session, snippet)
        logger.info("Snippet %r approved by %s", snippet.filename, user.username)
    return _build_approval_response(snippet)


@router.delete(
    "/{snippet_filename}/approval",
    status_code=http_status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def snippets_api_remove_approval(
    snippet: SnippetDep, user: ApiAdminUser, session: SessionDep
) -> Response:
    """Remove approval from a single snippet (idempotent).

    Removing an approval that doesn't exist is a no-op ``204``. The
    snippet missing → ``404`` (handled by ``SnippetDep``); approval
    missing → ``204``.

    :param snippet: The snippet whose approval is being cleared.
    :type snippet: Snippet
    :param user: The authenticated admin performing the action.
    :type user: User
    :param session: The active database session.
    :type session: AsyncSession
    :return: An empty 204 response.
    :rtype: Response
    """
    if snippet.is_approved:
        snippet.remove_approval(f"Approval removed by {user.username}", str(user.id))
        await SnippetManager.save(session, snippet)
        logger.info(
            "Snippet %r approval removed by %s", snippet.filename, user.username
        )
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)


@router.patch("/approvals")
async def snippets_api_batch_approve(
    body: SnippetBatchApproveRequest,
    user: ApiAdminUser,
    session: SessionDep,
) -> BatchApprovalResponse:
    """Atomically approve a set of snippets (idempotent partial-update).

    Reject the whole batch with ``400`` and a
    :class:`BatchApprovalErrorResponse` payload when any filename has no
    DB row or its file is missing on disk. Filenames that are already
    approved when the call starts are reported in
    ``skipped_already_approved`` — not as errors. The atomic write uses
    ``approved_at IS NULL`` as a CAS filter so two concurrent admins
    cannot double-approve.

    :param body: The validated JSON body.
    :type body: SnippetBatchApproveRequest
    :param user: The authenticated admin performing the action.
    :type user: User
    :param session: The active database session.
    :type session: AsyncSession
    :return: The success payload listing approved + skipped filenames.
    :rtype: BatchApprovalResponse
    :raises HTTPBadRequestException: On hard-error precheck failures with
        a :class:`BatchApprovalErrorResponse` body.
    """
    filenames = body.filenames
    existence = await check_snippet_batch_existence(session, filenames)
    if existence.has_errors:
        error_body = BatchApprovalErrorResponse(
            missing_in_db=existence.missing_in_db,
            missing_on_disk=existence.missing_on_disk,
        )
        raise HTTPBadRequestException(detail=error_body.model_dump())

    pre_already_approved = sorted(
        snippet.filename for snippet in existence.snippets if snippet.is_approved
    )
    to_approve = sorted(
        snippet.filename for snippet in existence.snippets if not snippet.is_approved
    )
    approved: list[str] = []
    if to_approve:
        approved_rows = await SnippetManager.update_where(
            session,
            {
                "approved_at": utc_now(),
                "updated_by": str(user.id),
                "reason": f"Batch approved by {user.username}",
            },
            col(Snippet.filename).in_(to_approve),
            col(Snippet.approved_at).is_(None),
            returning=["filename"],
        )
        approved = sorted(approved_rows)

    raced_out = sorted(set(to_approve) - set(approved))
    skipped = sorted(pre_already_approved + raced_out)
    logger.info(
        "Batch-approve via JSON API by %s: approved=%s skipped=%s",
        user.username,
        approved,
        skipped,
    )
    return BatchApprovalResponse(
        approved=approved,
        skipped_already_approved=skipped,
        count=len(approved),
    )
