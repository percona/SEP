"""Define routes for the Support Snippets plugin."""

import logging

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.auth.exceptions import HTTPForbiddenException
from app.sep.celery import update_snippets
from app.sep.config import sep_settings
from app.sep.deps import (
    AdminUser,
    DefaultContext,
    ExecutorHosts,
    IsAuthenticated,
    SessionDep,
    TaskAPI,
)
from app.sep.middleware import messages
from app.sep.plugins.snippets.deps import (
    ApprovedSnippet,
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
        name="snippets/index.html",
        context=context,
    )


@router.get(
    "/{snippet_filename}", dependencies=[IsAuthenticated], response_class=HTMLResponse
)
async def snippets_detail(
    snippet: ValidatedSnippet,
    request: Request,
    context: DefaultContext,
    executor_hosts: ExecutorHosts,
    tasks_api: TaskAPI,
) -> HTMLResponse:
    """Retrieve and display information about a snippet."""
    context |= {
        "snippet": snippet,
        "executor_hosts": list(executor_hosts.values()),
        "history_tasks": await tasks_api.get(
            "/exec-artifact/history/", params={"snippet_filename": snippet.filename}
        ),
        "running_tasks": await tasks_api.get(
            "/exec-artifact/history/",
            params={
                "snippet_filename": snippet.filename,
                "status": TaskHistoryStatusEnum.RUNNING,
            },
        ),
    }
    context["snippet"] = snippet
    try:
        context["snippet_preview"] = await snippet.get_preview()
    except UnicodeDecodeError:
        logger.debug("Could not decode snippet code", exc_info=True)
    return templates.TemplateResponse(
        request=request,
        name="snippets/details.html",
        context=context,
    )


def _get_snippet_approval_redirect(
    request: Request, user: AdminUser, snippet: Snippet, msg: str
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
    return _get_snippet_approval_redirect(request, user, snippet, "Snippet approved")


@router.post("/{snippet_filename}/remove-approval")
async def snippets_remove_approval(
    request: Request, user: AdminUser, snippet: ApprovedSnippet, session: SessionDep
) -> RedirectResponse:
    """Remove the approval of a snippet."""
    snippet.remove_approval(f"Approval removed by {user.username}", str(user.id))
    await SnippetManager.save(session, snippet)
    return _get_snippet_approval_redirect(
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
