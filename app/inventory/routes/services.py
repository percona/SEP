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

from app.api.deps import IsAuthenticatedDep, IsServicePrincipalDep
from app.core.pagination import PaginatedResponse
from app.core.pagination.deps import PaginationDep
from app.inventory.crud import (
    SchemaManager,
    ServiceManager,
    ServiceSystemObservationManager,
)
from app.inventory.deps import (
    RetirableServiceDep,
    SchemaListQueryDep,
    SchemaScopeDep,
    ServiceDep,
    ServiceListQueryDep,
    ServiceScopeDep,
    ServiceSystemObservationDep,
    SessionDep,
)
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
    list_query: ServiceListQueryDep,
    manager: ServiceScopeDep,
    service_type: ServiceTypeEnum | None = None,
) -> PaginatedResponse[ServiceResponse]:
    """List Services.

    :param session: The async database session.
    :param pagination: Validated offset/limit query parameters.
    :param list_query: The resolved sort/search produced at the request boundary.
    :param manager: The service manager the request's retirement scope selected.
    :param service_type: Return only services of this type.
    :return: A paginated response of service responses.
    """
    logger.debug("Listing services for type '%s'", service_type or "all")
    return await manager.list_query_paginated(
        session,
        list_query=list_query,
        select_related=[Service.schemas, Service.node],
        pagination=pagination,
        type=service_type,
    )


@router.get("/{service_id}", dependencies=[IsAuthenticatedDep])
async def retrieve_service(
    session: SessionDep,
    service_id: int,
    manager: ServiceScopeDep,
) -> ServiceDetailResponse:
    """Retrieve Service."""
    logger.debug("Retrieving service %s", service_id)
    return await manager.get_or_404(
        session,
        select_related=[Service.schemas, Service.node],
        id=service_id,
    )


@router.put("/{service_id}", dependencies=[IsServicePrincipalDep])
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
    dependencies=[IsServicePrincipalDep],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def retire_service(session: SessionDep, service: RetirableServiceDep) -> None:
    """Retire Service and everything below it, keeping the rows resolvable.

    :param session: The asynchronous database session.
    :param service: The service to retire, retired or not.
    """
    logger.debug("Retiring service %s", service.id)
    await ServiceManager.retire(session, service)


@router.post(
    "/{service_id}/revive",
    dependencies=[IsServicePrincipalDep],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revive_service(session: SessionDep, service: RetirableServiceDep) -> None:
    """Revive a retired Service together with its retired ancestors.

    :param session: The asynchronous database session.
    :param service: The service to revive, retired or not.
    :raises HTTPConflictException: If an active entity already holds the unique
        key the revived service would reclaim.
    """
    logger.debug("Reviving service %s", service.id)
    await ServiceManager.revive(session, service)


@router.get("/{service_id}/system-observation", dependencies=[IsAuthenticatedDep])
async def retrieve_service_system_observation(
    observation: ServiceSystemObservationDep,
) -> ServiceSystemObservationResponse:
    """Retrieve service system observation for a service."""
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
    list_query: SchemaListQueryDep,
    manager: SchemaScopeDep,
    include_tables: str | None = None,
) -> PaginatedResponse[SchemaResponse | SchemaCompactResponse]:
    """List Schemas by Service.

    Return ``SchemaResponse`` (with nested tables) when ``include_tables``
    is set, otherwise return ``SchemaCompactResponse`` (without tables).

    :param session: The async database session.
    :param service: The resolved service dependency.
    :param pagination: Validated offset/limit query parameters.
    :param list_query: The resolved sort/search produced at the request
        boundary.
    :param manager: The schema manager the request's retirement scope selected.
    :param include_tables: Include nested tables in the response when set to
        any non-empty value. Defaults to compact mode (no tables).
    :return: A paginated response of schema responses.
    """
    logger.debug("Listing schemas for service '%s'", service.id)
    select_related = [Schema.tables] if include_tables else []
    result = await manager.list_query_paginated(
        session,
        list_query=list_query,
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
