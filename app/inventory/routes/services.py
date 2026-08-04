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

"""Define the routes for the Services resource."""

import logging

from fastapi import APIRouter, status
from sqlmodel import col

from app.api.deps import IsAuthenticatedDep
from app.core.exceptions import HTTPNotFoundException
from app.core.pagination import PaginatedResponse
from app.core.pagination.deps import PaginationDep
from app.inventory.crud import (
    SchemaManager,
    ServiceManager,
    ServiceSystemObservationManager,
)
from app.inventory.deps import ServiceDep, SessionDep
from app.inventory.models import (
    Schema,
    SchemaCompactResponse,
    SchemaResponse,
    SchemaWrite,
    Service,
    ServiceDetailResponse,
    ServiceResponse,
    ServiceSystemObservationResponse,
    ServiceSystemObservationWrite,
    ServiceTypeEnum,
    ServiceWrite,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/services", tags=["services"])


@router.get("/", dependencies=[IsAuthenticatedDep])
async def list_services(
    session: SessionDep,
    pagination: PaginationDep,
    service_type: ServiceTypeEnum | None = None,
) -> PaginatedResponse[ServiceResponse]:
    """List Services."""
    logger.debug("Listing services for type '%s'", service_type or "all")
    return await ServiceManager.list_paginated(
        session,
        select_related=[Service.schemas, Service.node],
        pagination=pagination,
        type=service_type,
    )


@router.get("/{service_id}", dependencies=[IsAuthenticatedDep])
async def retrieve_service(
    session: SessionDep,
    service_id: int,
) -> ServiceDetailResponse:
    """Retrieve Service."""
    logger.debug("Retrieving service %s", service_id)
    return await ServiceManager.get_or_404(
        session,
        select_related=[Service.schemas, Service.node],
        id=service_id,
    )


@router.put("/{service_id}", dependencies=[IsAuthenticatedDep])
async def update_service(
    session: SessionDep,
    existing_service: ServiceDep,
    updated_service: ServiceWrite,
) -> Service:
    """Update Service."""
    logger.debug("Updating service %s", existing_service.id)
    return await ServiceManager.update(session, existing_service, updated_service)


@router.delete(
    "/{service_id}",
    dependencies=[IsAuthenticatedDep],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_service(session: SessionDep, service: ServiceDep) -> None:
    """Delete Service."""
    logger.debug("Deleting service %s", service.id)
    await ServiceManager.delete(session, service)


@router.get("/{service_id}/system-observation", dependencies=[IsAuthenticatedDep])
async def retrieve_service_system_observation(
    session: SessionDep,
    service: ServiceDep,
) -> ServiceSystemObservationResponse:
    """Retrieve service system observation for a service."""
    # A service that exists but was never visited by the system-facts syncer is a
    # normal state, so raise with a distinct detail rather than through get_or_404(),
    # whose default detail is indistinguishable from the missing-service 404 that
    # ServiceDep raises.
    observation = await ServiceSystemObservationManager.first(
        session, service_id=service.id
    )
    if observation is None:
        raise HTTPNotFoundException(
            detail="System observation not collected yet for this service"
        )
    return observation


@router.put("/{service_id}/system-observation", dependencies=[IsAuthenticatedDep])
async def upsert_service_system_observation(
    session: SessionDep,
    service: ServiceDep,
    data: ServiceSystemObservationWrite,
) -> ServiceSystemObservationResponse:
    """Upsert service system observation for a service."""
    data.service_id = service.id
    obs, created = await ServiceSystemObservationManager.get_or_create(
        session, data, filter_include={"service_id"}
    )
    if not created:
        obs = await ServiceSystemObservationManager.update(session, obs, data)
    return obs


@router.get("/{service_id}/schemas/", dependencies=[IsAuthenticatedDep])
async def list_schemas_by_service(
    session: SessionDep,
    service: ServiceDep,
    pagination: PaginationDep,
    search: str | None = None,
    include_tables: str | None = None,
) -> PaginatedResponse[SchemaResponse | SchemaCompactResponse]:
    """List Schemas by Service.

    Return ``SchemaResponse`` (with nested tables) when ``include_tables``
    is set, otherwise return ``SchemaCompactResponse`` (without tables).

    :param session: The async database session.
    :type session: AsyncSession
    :param service: The resolved service dependency.
    :type service: Service
    :param search: Filter schemas by name using ILIKE matching.
    :type search: str | None
    :param include_tables: Include nested tables in the response when set to
        any non-empty value. Defaults to compact mode (no tables).
    :type include_tables: str | None
    :param pagination: Validated offset/limit query parameters.
    :type pagination: Pagination
    :return: A paginated response of schema responses.
    :rtype: PaginatedResponse[SchemaResponse | SchemaCompactResponse]
    """
    logger.debug("Listing schemas for service '%s'", service.id)
    whereclause = []
    if search:
        whereclause.append(col(Schema.name).ilike(f"%{search}%"))
    select_related = [Schema.tables] if include_tables else []
    result = await SchemaManager.list_paginated(
        session,
        *whereclause,
        select_related=select_related,
        pagination=pagination,
        service_id=service.id,
    )
    if include_tables:
        return result.map_items(
            lambda schema: SchemaResponse.model_validate(schema, from_attributes=True)
        )
    return result.map_items(
        lambda schema: SchemaCompactResponse.model_validate(
            schema, from_attributes=True
        )
    )


@router.post(
    "/{service_id}/schemas/",
    dependencies=[IsAuthenticatedDep],
    status_code=status.HTTP_201_CREATED,
)
async def create_schema_for_service(
    session: SessionDep,
    service: ServiceDep,
    schema: SchemaWrite,
) -> Schema:
    """Create Schema for Service."""
    logger.debug("Creating schema for service %s: %s", service.id, schema)
    return await SchemaManager.create(session, schema, service_id=service.id)
