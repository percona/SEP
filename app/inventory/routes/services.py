"""Define the routes for the Services resource."""

import logging

from fastapi import APIRouter

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
        select_related=[Service.schemas],
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


@router.delete("/{service_id}", dependencies=[IsAuthenticatedDep])
async def delete_service(session: SessionDep, service: ServiceDep) -> ServiceResponse:
    """Delete Service."""
    logger.debug("Deleting service %s", service.id)
    return await ServiceManager.delete(session, service)


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


@router.post("/{service_id}/schemas/", dependencies=[IsAuthenticatedDep])
async def create_schema_for_service(
    session: SessionDep,
    service: ServiceDep,
    schema: SchemaWrite,
) -> Schema:
    """Create Schema for Service."""
    logger.debug("Creating schema for service %s: %s", service.id, schema)
    return await SchemaManager.create(session, schema, service_id=service.id)
