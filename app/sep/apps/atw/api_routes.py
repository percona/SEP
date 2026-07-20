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

from fastapi import APIRouter, status
from pydantic import BaseModel, UUID4

from app.core.pagination import PaginatedResponse
from app.core.pagination.deps import PaginationDep
from app.sep.apps.atw.categories import (
    ATWCategory,
    CATEGORY_ROOT_LABELS,
    derive_category_root,
)
from app.sep.apps.atw.crud import AtwIncidentManager
from app.sep.apps.atw.models import (
    AtwIncident,
    AtwIncidentResponse,
    AtwIncidentUpdate,
    AtwIncidentWrite,
)
from app.sep.apps.atw.schema import atw_schema
from app.sep.apps.framework.api import schema_endpoint
from app.sep.deps import ApiCurrentUser, SessionDep
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models import Snippet

logger = logging.getLogger(__name__)

ATW_META_KEY = "atw"
ATW_META_WARNING = (
    f"Ignoring meta[{ATW_META_KEY!r}] for snippet %s: expected list, got %s"
)


class ATWSnippetSummary(BaseModel):
    """Represent one snippet entry under an ATW category.

    :param name: The snippet filename, used as its API identifier.
    :type name: str
    :param title: The snippet display title.
    :type title: str
    :param description: The snippet free-text description.
    :type description: str
    """

    name: str
    title: str
    description: str


class ATWCategoryListing(BaseModel):
    """Represent one ATW category row and its snippet members.

    :param category_root: The top-level product/category root.
    :type category_root: str
    :param parent_category: The parent category enum name.
    :type parent_category: str
    :param parent_category_label: The parent category display label.
    :type parent_category_label: str
    :param category: The ATW leaf category enum name.
    :type category: str
    :param category_label: The ATW leaf category display label.
    :type category_label: str
    :param snippet_count: Number of snippets in this category.
    :type snippet_count: int
    :param snippets: Snippet summaries belonging to this category.
    :type snippets: list[ATWSnippetSummary]
    """

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


@router.get("/")
async def atw_api_list(session: SessionDep) -> list[ATWCategoryListing]:
    """List ATW-tagged snippets grouped by category.

    Categories with no matching snippets are omitted to keep the payload small;
    the ATW enum still defines the full taxonomy for validation (plugin schema).
    """
    snippets = await SnippetManager.list(session)
    snippets_by_cell: defaultdict[tuple[str, str], list[Snippet]] = defaultdict(list)
    for snippet in snippets:
        root = derive_category_root(snippet.meta.get("service_type"))
        tags: list[str] = []
        if ATW_META_KEY in snippet.meta:
            raw_atw = snippet.meta[ATW_META_KEY]
            if isinstance(raw_atw, list):
                tags = raw_atw
            else:
                logger.warning(
                    ATW_META_WARNING,
                    snippet.filename,
                    type(raw_atw).__name__,
                )
        for tag in dict.fromkeys(tags):
            snippets_by_cell[(root, tag)].append(snippet)

    grouped: list[ATWCategoryListing] = []
    for root_label in CATEGORY_ROOT_LABELS.values():
        for category in ATWCategory:
            cell_snippets = snippets_by_cell.get((root_label, category.name), [])
            if not cell_snippets:
                continue
            category_snippets = [_build_summary(snippet) for snippet in cell_snippets]
            grouped.append(
                ATWCategoryListing(
                    category_root=root_label,
                    parent_category=category.parent.name,
                    parent_category_label=category.parent.value,
                    category=category.name,
                    category_label=category.value,
                    snippet_count=len(category_snippets),
                    snippets=category_snippets,
                )
            )

    return grouped


@router.post("/incidents/", status_code=status.HTTP_201_CREATED)
async def atw_create_incident(
    session: SessionDep,
    current_user: ApiCurrentUser,
    body: AtwIncidentWrite,
) -> AtwIncidentResponse:
    """Create a diagnostic incident owned by the current user.

    :param session: The database session.
    :param current_user: The authenticated user, stamped as ``created_by``.
    :param body: The incident create payload.
    :return: The created incident.
    """
    incident = AtwIncident(**body.model_dump(), created_by=current_user.username)
    saved = await AtwIncidentManager.save(session, incident)
    return AtwIncidentResponse.model_validate(saved)


@router.get("/incidents/")
async def atw_list_incidents(
    session: SessionDep, pagination: PaginationDep
) -> PaginatedResponse[AtwIncidentResponse]:
    """List diagnostic incidents, newest first.

    :param session: The database session.
    :param pagination: The offset/limit window for the page.
    :return: A paginated page of incidents, newest first.
    """
    page = await AtwIncidentManager.list_paginated(session, pagination=pagination)
    items = [AtwIncidentResponse.model_validate(incident) for incident in page.items]
    return PaginatedResponse.from_pagination(items, page.total, pagination)


@router.get("/incidents/{incident_id}")
async def atw_get_incident(
    session: SessionDep, incident_id: UUID4
) -> AtwIncidentResponse:
    """Retrieve a single diagnostic incident by id.

    :param session: The database session.
    :param incident_id: The incident's UUID.
    :return: The matching incident.
    :raises HTTPNotFoundException: If no incident has that id.
    """
    incident = await AtwIncidentManager.get_or_404(session, id=incident_id)
    return AtwIncidentResponse.model_validate(incident)


@router.patch("/incidents/{incident_id}")
async def atw_update_incident(
    session: SessionDep, incident_id: UUID4, body: AtwIncidentUpdate
) -> AtwIncidentResponse:
    """Update a diagnostic incident's name or ServiceNow case reference.

    :param session: The database session.
    :param incident_id: The incident's UUID.
    :param body: The partial update payload; unset fields are untouched.
    :return: The updated incident.
    :raises HTTPNotFoundException: If no incident has that id.
    """
    incident = await AtwIncidentManager.get_or_404(session, id=incident_id)
    updated = await AtwIncidentManager.update(session, incident, body)
    return AtwIncidentResponse.model_validate(updated)


@router.delete(
    "/incidents/{incident_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def atw_delete_incident(session: SessionDep, incident_id: UUID4) -> None:
    """Delete a diagnostic incident and cascade its execution rows.

    :param session: The database session.
    :param incident_id: The incident's UUID.
    :raises HTTPNotFoundException: If no incident has that id.
    """
    incident = await AtwIncidentManager.get_or_404(session, id=incident_id)
    await AtwIncidentManager.delete(session, incident)
