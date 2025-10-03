"""Define routes for the plugin."""

import logging
from collections import defaultdict

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.sep.config import sep_settings
from app.sep.deps import (
    DefaultContext,
    ExecutorHosts,
    IsAuthenticated,
    SessionDep,
)
from app.sep.plugins.atw.models import ATWCategory
from app.sep.snippets.crud import SnippetManager
from app.sep.utils.jinja import syntax_highlight

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def app_index(
    request: Request,
    session: SessionDep,
    context: DefaultContext,
    executor_hosts: ExecutorHosts,
) -> HTMLResponse:
    """Homepage of plugin."""
    snippets = await SnippetManager.list(session)
    context["snippets"] = {
        snippet.filename: snippet.to_form(
            list(executor_hosts), f"/snippets/{snippet.filename}"
        )
        for snippet in snippets
    }
    # arrumar linenos
    context["previews"] = {
        snippet.filename: syntax_highlight(
            (await snippet.get_preview()).content,
            style="monokai",
            linenos=False,
            wrapcode=True,
        )
        for snippet in snippets
    }
    context["executor_hosts"] = list(executor_hosts)
    context["atw_categories"] = defaultdict(dict)
    for category in ATWCategory:
        context["atw_categories"][category.parent][category] = [
            snippet.filename
            for snippet in snippets
            if category.name in snippet.meta.get("atw", [])
        ]
    return templates.TemplateResponse(
        request=request,
        name="atw/index.html",
        context=context,
    )
