"""Define routes for the Support Snippets plugin."""

import logging
from os import SEEK_END

import aiofiles
from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.sep.config import sep_settings
from app.sep.crud import SnippetManager
from app.sep.deps import (
    AdminUser,
    DefaultContext,
    IsAuthenticated,
    SessionDep,
)
from app.sep.middleware import messages
from app.sep.models import Snippet
from app.sep.plugins.snippets.deps import ApprovedSnippet, SnippetDep, UnapprovedSnippet

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
    return templates.TemplateResponse(
        request=request,
        name="snippets/index.html",
        context=context,
    )


@router.get(
    "/{snippet_filename}", dependencies=[IsAuthenticated], response_class=HTMLResponse
)
async def snippets_detail(
    request: Request,
    context: DefaultContext,
    snippet: SnippetDep,
) -> HTMLResponse:
    """Retrieve and display information about a snippet."""
    context["snippet"] = snippet
    context["snippet_size"] = await snippet.get_size()
    max_lines = 500
    max_chars = 10000
    try:
        async with aiofiles.open(snippet) as f:
            code = await f.readline()
            line_number = 1
            while len(code) < max_chars and line_number < max_lines:
                code += await f.readline()
                line_number += 1
            context["snippet_code"] = code[:max_chars]
            context["snippet_code_is_sliced"] = code != context[
                "snippet_code"
            ] or await f.tell() < await f.seek(0, SEEK_END)
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
    snippet.approve(f"Approved by {user.username}")
    await SnippetManager.save(session, snippet)
    return _get_snippet_approval_redirect(request, user, snippet, "Snippet approved")


@router.post("/{snippet_filename}/remove-approval")
async def snippets_remove_approval(
    request: Request, user: AdminUser, snippet: ApprovedSnippet, session: SessionDep
) -> RedirectResponse:
    """Remove the approval of a snippet."""
    snippet.remove_approval(f"Approval removed by {user.username}")
    await SnippetManager.save(session, snippet)
    return _get_snippet_approval_redirect(
        request, user, snippet, "Snippet's approval removed"
    )
