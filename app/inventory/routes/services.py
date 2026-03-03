# Copyright 2025 Percona LLC
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

from app.api.deps import IsAuthenticatedDep
from app.inventory.crud import SchemaManager, ServiceManager
from app.inventory.deps import ServiceDep, SessionDep
from app.inventory.models import (
    Schema,
    SchemaResponse,
    SchemaWrite,
    Service,
    ServiceDetailResponse,
    ServiceResponse,
    ServiceTypeEnum,
    ServiceWrite,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/services", tags=["services"])


@router.get("/", dependencies=[IsAuthenticatedDep])
async def list_services(
    session: SessionDep,
    service_type: ServiceTypeEnum | None = None,
) -> list[ServiceResponse]:
    """List Services."""
    logger.debug("Listing services for type '%s'", service_type or "all")
    return await ServiceManager.list(
        session,
        select_related=[Service.schemas, Service.node],
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


@router.get("/{service_id}/schemas/", dependencies=[IsAuthenticatedDep])
async def list_schemas_by_service(
    session: SessionDep,
    service: ServiceDep,
) -> list[SchemaResponse]:
    """List Schemas by Service."""
    logger.debug("Listing schemas for service '%s'", service.id)
    return await SchemaManager.list(
        session,
        select_related=[Schema.tables],
        service_id=service.id,
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
