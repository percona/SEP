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

from urllib.parse import quote

from fastapi import APIRouter
from pydantic import BaseModel

from app.sep.deps import SessionDep
from app.sep.plugins.atw.models import ATWCategory
from app.sep.plugins.atw.schema import atw_schema
from app.sep.plugins.framework.api import schema_endpoint
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models import Snippet


class ATWSnippetSummary(BaseModel):
    """Represent one snippet entry under an ATW category."""

    name: str
    title: str
    description: str
    snippet_schema_url: str
    snippet_execute_url: str
    snippet_preview_url: str


class ATWCategoryListing(BaseModel):
    """Represent one ATW category row and its snippet members."""

    name: str
    parent_category: str
    parent_category_label: str
    category: str
    category_label: str
    snippet_count: int
    snippets: list[ATWSnippetSummary]


router = APIRouter()
schema_endpoint(router=router, plugin_schema=atw_schema)


def _build_summary(snippet: Snippet) -> ATWSnippetSummary:
    encoded_filename = quote(snippet.filename, safe="")
    return ATWSnippetSummary(
        name=snippet.filename,
        title=snippet.title,
        description=snippet.description,
        snippet_schema_url=f"/api/plugins/snippets/{encoded_filename}/schema",
        snippet_execute_url=f"/api/plugins/snippets/{encoded_filename}/execute",
        snippet_preview_url=f"/api/plugins/snippets/{encoded_filename}/script-preview",
    )


@router.get("/", response_model=list[ATWCategoryListing])
async def atw_api_list(session: SessionDep) -> list[ATWCategoryListing]:
    """List ATW-tagged snippets grouped by category."""
    snippets = await SnippetManager.list(session)
    grouped: list[ATWCategoryListing] = []

    for category in ATWCategory:
        category_snippets = [
            _build_summary(snippet)
            for snippet in snippets
            if category.name in snippet.meta.get("atw", [])
        ]
        grouped.append(
            ATWCategoryListing(
                name=category.name,
                parent_category=category.parent.name,
                parent_category_label=category.parent.value,
                category=category.name,
                category_label=category.value,
                snippet_count=len(category_snippets),
                snippets=category_snippets,
            )
        )

    return grouped
