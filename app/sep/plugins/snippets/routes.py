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

"""Define routes for the Support Snippets plugin."""

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import col

from app.core.auth.exceptions import HTTPForbiddenException
from app.core.utils import utc_now
from app.sep.celery import update_snippets
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
from app.sep.plugins.snippets.deps import (
    ApprovedSnippet,
    ExecutableSnippet,
    SnippetBatchApproveForm,
    SnippetExecutionRequestMeta,
    UnapprovedSnippet,
    ValidatedSnippet,
)
from app.sep.snippets.config import snippets_settings
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models import Snippet
from app.tasks.models import TaskHistoryStatusEnum

logger = logging.getLogger(__name__)
router = APIRouter()
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


@router.get(
    "/{snippet_filename}", dependencies=[IsAuthenticated], response_class=HTMLResponse
)
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


def _get_snippet_success_redirect(
    request: Request, user: AdminUser, snippet: Snippet, msg: str | None = None
) -> RedirectResponse:
    messages.success(request, msg)
    logger.info("%s by %s: %r", msg, user.username, snippet)
    return RedirectResponse(
        request.url_for("snippets_detail", snippet_filename=snippet.filename),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{snippet_filename}/approve")
async def snippets_approve(
    request: Request, user: AdminUser, snippet: UnapprovedSnippet, session: SessionDep
) -> RedirectResponse:
    """Approve a snippet."""
    snippet.approve(f"Approved by {user.username}", str(user.id))
    await SnippetManager.save(session, snippet)
    return _get_snippet_success_redirect(request, user, snippet, "Snippet approved")


@router.post("/{snippet_filename}/remove-approval")
async def snippets_remove_approval(
    request: Request, user: AdminUser, snippet: ApprovedSnippet, session: SessionDep
) -> RedirectResponse:
    """Remove the approval of a snippet."""
    snippet.remove_approval(f"Approval removed by {user.username}", str(user.id))
    await SnippetManager.save(session, snippet)
    return _get_snippet_success_redirect(
        request, user, snippet, "Snippet's approval removed"
    )


@router.post("/refresh")
async def snippets_refresh(request: Request, user: AdminUser) -> RedirectResponse:
    """Refresh the snippets."""
    if not snippets_settings.ENABLE_MANUAL_SYNC:
        raise HTTPForbiddenException
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
    filenames = list(body.filenames)
    snippets = await SnippetManager.list(session, col(Snippet.filename).in_(filenames))
    found = {snippet.filename for snippet in snippets}
    missing_in_db = sorted(set(filenames) - found)
    if missing_in_db:
        messages.error(request, f"Unknown snippet(s): {', '.join(missing_in_db)}")
        return index_redirect
    missing_on_disk = sorted(
        snippet.filename for snippet in snippets if not Path(snippet).is_file()
    )
    if missing_on_disk:
        messages.error(
            request,
            f"Snippet file(s) missing on disk: {', '.join(missing_on_disk)}",
        )
        return index_redirect
    already_approved = sorted(
        snippet.filename for snippet in snippets if snippet.is_approved
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
    if result.rowcount != len(filenames):
        messages.error(
            request,
            "Batch approval aborted — snippet state changed concurrently. Please retry.",
        )
        return index_redirect
    logger.info(
        "Batch-approved %d snippet(s) by %s: %s",
        result.rowcount,
        user.username,
        filenames,
    )
    messages.success(request, f"{result.rowcount} snippet(s) approved")
    return index_redirect


@router.post("/{snippet_filename}", dependencies=[IsAuthenticated])
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
        request.url_for("snippets_detail", snippet_filename=snippet.filename),
        status_code=status.HTTP_303_SEE_OTHER,
    )
