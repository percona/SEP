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

import logging
from collections import defaultdict

from fastapi import APIRouter
from pydantic import BaseModel

from app.sep.deps import SessionDep
from app.sep.plugins.atw.models import ATWCategory
from app.sep.plugins.atw.schema import atw_schema
from app.sep.plugins.framework.api import schema_endpoint
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models import Snippet

logger = logging.getLogger(__name__)

# TODO(SEP-1127): Derive category_root from snippet/meta for multi-root ATW.
# https://percona.atlassian.net/browse/SEP-1127
ATW_CATEGORY_ROOT = "MySQL"


class ATWSnippetSummary(BaseModel):
    """Represent one snippet entry under an ATW category."""

    name: str
    title: str
    description: str


class ATWCategoryListing(BaseModel):
    """Represent one ATW category row and its snippet members."""

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


@router.get("/", response_model=list[ATWCategoryListing])
async def atw_api_list(session: SessionDep) -> list[ATWCategoryListing]:
    """List ATW-tagged snippets grouped by category.

    Categories with no matching snippets are omitted to keep the payload small;
    the ATW enum still defines the full taxonomy for validation (plugin schema).
    """
    snippets = await SnippetManager.list(session)
    snippets_by_atw_tag: defaultdict[str, list[Snippet]] = defaultdict(list)
    for snippet in snippets:
        if "atw" not in snippet.meta:
            tags = []
        else:
            raw_atw = snippet.meta["atw"]
            if isinstance(raw_atw, list):
                tags = raw_atw
            else:
                logger.warning(
                    "Ignoring meta['atw'] for snippet %s: expected list, got %s",
                    snippet.filename,
                    type(raw_atw).__name__,
                )
                tags = []
        for tag in dict.fromkeys(tags):
            snippets_by_atw_tag[tag].append(snippet)

    grouped: list[ATWCategoryListing] = []
    for category in ATWCategory:
        category_snippets = [
            _build_summary(snippet)
            for snippet in snippets_by_atw_tag.get(category.name, [])
        ]
        if not category_snippets:
            continue
        grouped.append(
            ATWCategoryListing(
                category_root=ATW_CATEGORY_ROOT,
                parent_category=category.parent.name,
                parent_category_label=category.parent.value,
                category=category.name,
                category_label=category.value,
                snippet_count=len(category_snippets),
                snippets=category_snippets,
            )
        )

    return grouped
