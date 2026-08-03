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

"""Define routes for the Support Snippets plugin.

These Jinja2 routes are deprecated. The JSON API equivalents live under
``/api/apps/snippets/`` and the React UI consumes them via
``frontend/packages/apps/snippets``. Every response from this router
carries the RFC 8594 ``Deprecation: true`` header and emits a WARNING on
hit; the routes remain mounted only until the Jinja layer is removed. The
React UI is at parity: chaining, scheduling and alerting are absent from
both surfaces, and the app declares them unsupported in its schema.

Per-snippet HTML actions use fixed paths (``/detail``, ``/execute``,
``/approve``, ``/remove-approval``) and pass ``snippet_filename`` as a
query parameter so nested keys (e.g. ``diag/slow-query.sh``) never appear
as a path segment: Starlette rejects slashes in ``url_for`` path params.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import col

from app.core.auth.exceptions import HTTPForbiddenException
from app.core.utils import utc_now
from app.sep.app_drain import track_app_task
from app.sep.apps.framework.deprecation import DeprecatedJinja2Route
from app.sep.config import sep_settings
from app.sep.deps import (
    AdminUser,
    DefaultContext,
    ExecutorHostsCtx,
    IsAuthenticated,
    IsCsrfValidated,
    SessionDep,
    TaskAPI,
)
from app.sep.middleware import messages
from app.sep.snippets.celery import update_snippets
from app.sep.snippets.config import snippets_settings
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.deps import (
    ApprovedSnippet,
    check_snippet_batch_existence,
    ExecutableSnippet,
    SnippetBatchApproveForm,
    SnippetExecutionRequestMeta,
    UnapprovedSnippet,
    ValidatedSnippet,
)
from app.sep.snippets.models import Snippet
from app.tasks.models import TaskHistoryStatusEnum

logger = logging.getLogger(__name__)
router = APIRouter(route_class=DeprecatedJinja2Route)
templates = sep_settings.TEMPLATES


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def snippets_index(
    request: Request,
    session: SessionDep,
    context: DefaultContext,
) -> HTMLResponse:
    """Homepage of snippets plugin."""
    context["snippets"] = await SnippetManager.list(session)
    context["enable_snippets_refresh"] = snippets_settings.ENABLE_MANUAL_SYNC
    return templates.TemplateResponse(
        request=request,
        name="snippets/index.html.j2",
        context=context,
    )


def _get_snippet_success_redirect(
    request: Request, user: AdminUser, snippet: Snippet, msg: str | None = None
) -> RedirectResponse:
    messages.success(request, msg)
    logger.info("%s by %s: %r", msg, user.username, snippet)
    return RedirectResponse(
        str(
            request.url_for("snippets_detail").include_query_params(
                snippet_filename=snippet.filename
            )
        ),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/approve", dependencies=[IsCsrfValidated])
async def snippets_approve(
    request: Request, user: AdminUser, snippet: UnapprovedSnippet, session: SessionDep
) -> RedirectResponse:
    """Approve a snippet."""
    snippet.approve(f"Approved by {user.username}", str(user.id))
    await SnippetManager.save(session, snippet)
    return _get_snippet_success_redirect(request, user, snippet, "Snippet approved")


@router.post("/remove-approval", dependencies=[IsCsrfValidated])
async def snippets_remove_approval(
    request: Request, user: AdminUser, snippet: ApprovedSnippet, session: SessionDep
) -> RedirectResponse:
    """Remove the approval of a snippet."""
    snippet.remove_approval(f"Approval removed by {user.username}", str(user.id))
    await SnippetManager.save(session, snippet)
    return _get_snippet_success_redirect(
        request, user, snippet, "Snippet's approval removed"
    )


@router.post("/refresh", dependencies=[IsCsrfValidated])
async def snippets_refresh(
    request: Request, user: AdminUser, session: SessionDep
) -> RedirectResponse:
    """Refresh the snippets."""
    if not snippets_settings.ENABLE_MANUAL_SYNC:
        raise HTTPForbiddenException
    async with track_app_task(session, "snippets"):
        await update_snippets()
    messages.success(request, "Snippets refreshed")
    logger.info("Snippets refreshed by %s", user.username)
    return RedirectResponse(
        request.url_for("snippets_index"), status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/approve-batch", dependencies=[IsCsrfValidated])
async def snippets_approve_batch(
    request: Request,
    user: AdminUser,
    session: SessionDep,
    body: Annotated[SnippetBatchApproveForm, Form()],
) -> RedirectResponse:
    """Approve multiple snippets in a single atomic bulk operation.

    Reject the whole batch if any requested filename is unknown, its file is
    missing on disk, or it is already approved. On success, flash a summary and
    redirect back to the snippets index.

    :param request: The HTTP request object.
    :type request: Request
    :param user: The admin performing the action.
    :type user: User
    :param session: The active database session.
    :type session: AsyncSession
    :param body: The validated request body containing the filenames to approve.
    :type body: SnippetBatchApproveForm
    :return: A 303 redirect back to the snippets index.
    :rtype: RedirectResponse
    """
    index_redirect = RedirectResponse(
        request.url_for("snippets_index"), status_code=status.HTTP_303_SEE_OTHER
    )
    filenames = body.filenames
    existence = await check_snippet_batch_existence(session, filenames)
    if existence.missing_in_db:
        messages.error(
            request, f"Unknown snippet(s): {', '.join(existence.missing_in_db)}"
        )
        return index_redirect
    if existence.missing_on_disk:
        messages.error(
            request,
            f"Snippet file(s) missing on disk: {', '.join(existence.missing_on_disk)}",
        )
        return index_redirect
    already_approved = sorted(
        snippet.filename for snippet in existence.snippets if snippet.is_approved
    )
    if already_approved:
        messages.error(request, f"Already approved: {', '.join(already_approved)}")
        return index_redirect
    result = await SnippetManager.update_where(
        session,
        {
            "approved_at": utc_now(),
            "updated_by": str(user.id),
            "reason": f"Batch approved by {user.username}",
        },
        col(Snippet.filename).in_(filenames),
        col(Snippet.approved_at).is_(None),
    )
    updated_count = result.rowcount
    logger.info(
        "Batch-approved %d snippet(s) by %s: %s",
        updated_count,
        user.username,
        filenames,
    )
    if updated_count == 0:
        messages.error(
            request,
            "No snippets were approved — their state changed before the batch "
            "was processed. Please reload and retry.",
        )
        return index_redirect
    skipped = len(filenames) - updated_count
    if skipped:
        messages.success(
            request,
            f"{updated_count} snippet(s) approved "
            f"({skipped} skipped — already approved by another admin)",
        )
        return index_redirect
    messages.success(request, f"{updated_count} snippet(s) approved")
    return index_redirect


@router.post("/execute", dependencies=[IsAuthenticated])
async def snippets_execute(
    request: Request,
    tasks_api: TaskAPI,
    snippet: ExecutableSnippet,
    execution_request_meta: SnippetExecutionRequestMeta,
) -> RedirectResponse:
    """Execute a snippet."""
    logger.info(
        "Executing [%s] snippet %r with args: %r",
        execution_request_meta.interpreter,
        snippet.filename,
        execution_request_meta.args,
    )
    logger.debug(
        "Execution meta for snippet %r: %s", snippet.filename, execution_request_meta
    )
    await tasks_api.post(
        f"/execute/{snippet.execution_task_name}",
        json={
            "meta": execution_request_meta.model_dump(by_alias=True, exclude_none=True)
        },
    )
    return RedirectResponse(
        str(
            request.url_for("snippets_detail").include_query_params(
                snippet_filename=snippet.filename
            )
        ),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/detail", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def snippets_detail(
    snippet: ValidatedSnippet,
    request: Request,
    context: DefaultContext,
    executor_hosts_ctx: ExecutorHostsCtx,
    tasks_api: TaskAPI,
) -> HTMLResponse:
    """Retrieve and display information about a snippet."""
    response = await tasks_api.get(
        f"/{snippet.execution_task_name}/history/",
        params={"snippet_filename": snippet.filename},
    )
    history_tasks = response["items"]
    for history in history_tasks:
        try:
            history["available_files"] = await tasks_api.get(
                f"/history/{history['id']}/files/"
            )
        except HTTPException:
            logger.debug(
                "Could not fetch available files for task history %s",
                history["id"],
                exc_info=True,
            )
            history["available_files"] = []
    response = await tasks_api.get(
        f"/{snippet.execution_task_name}/history/",
        params={
            "snippet_filename": snippet.filename,
            "status": TaskHistoryStatusEnum.RUNNING,
        },
    )
    context |= {
        "snippet": snippet,
        "executor_hosts": executor_hosts_ctx.as_form_hosts(),
        "history_tasks": history_tasks,
        "running_tasks": response["items"],
        "snippet_execute_action": str(
            request.url_for("snippets_execute").include_query_params(
                snippet_filename=snippet.filename
            )
        ),
    }
    context["snippet"] = snippet
    try:
        context["snippet_preview"] = await snippet.get_preview()
    except UnicodeDecodeError:
        logger.debug("Could not decode snippet code", exc_info=True)
    return templates.TemplateResponse(
        request=request,
        name="snippets/details.html.j2",
        context=context,
    )
