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

"""Define routes for the plugin."""

import logging
from collections import defaultdict

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.sep.config import sep_settings
from app.sep.deps import (
    DefaultContext,
    ExecutorHostsCtx,
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
    executor_hosts_ctx: ExecutorHostsCtx,
) -> HTMLResponse:
    """Homepage of plugin."""
    snippets = await SnippetManager.list(session)
    form_hosts = executor_hosts_ctx.as_form_hosts()
    context["snippets"] = {
        snippet.filename: snippet.to_form(form_hosts, f"/snippets/{snippet.filename}")
        for snippet in snippets
    }
    # arrumar linenos
    context["previews"] = {
        snippet.filename: syntax_highlight(
            (await snippet.get_preview()).full_content,
            style="monokai",
            linenos=False,
            wrapcode=True,
        )
        for snippet in snippets
    }
    context["executor_hosts"] = executor_hosts_ctx.as_template_list()
    context["atw_categories"] = defaultdict(dict)
    for category in ATWCategory:
        context["atw_categories"][category.parent][category] = [
            snippet.filename
            for snippet in snippets
            if category.name in snippet.meta.get("atw", [])
        ]
    return templates.TemplateResponse(
        request=request,
        name="atw/index.html.j2",
        context=context,
    )
