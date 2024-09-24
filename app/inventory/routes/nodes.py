"""Define the routes for the Nodes resource."""

import logging

from fastapi import APIRouter

from app.api.deps import IsAuthenticatedDep
from app.core.fields import RequiredStr
from app.inventory.crud import NodeManager
from app.inventory.crud import ServiceManager
from app.inventory.deps import NodeDep
from app.inventory.deps import SessionDep
from app.inventory.models import Node
from app.inventory.models import NodeResponse
from app.inventory.models import NodeWrite
from app.inventory.models import Service
from app.inventory.models import ServiceResponse
from app.inventory.models import ServiceTypeEnum
from app.inventory.models import ServiceWrite
from app.inventory.models import SourceEnum

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", dependencies=[IsAuthenticatedDep])
async def list_nodes(
    session: SessionDep,
    external_id: RequiredStr | None = None,
    source: SourceEnum | None = None,
    node_type: RequiredStr | None = None,
) -> list[NodeResponse]:
    """List Nodes from Inventory."""
    logger.debug(
        "Listing nodes for source '%s' and type '%s'",
        source or "all",
        node_type or "all",
    )
    return await NodeManager.list(
        session,
        select_related=[Node.services],
        external_id=external_id,
        source=source,
        type=node_type,
    )


@router.get("/{node_id}", dependencies=[IsAuthenticatedDep])
async def retrieve_node(session: SessionDep, node_id: int) -> NodeResponse:
    """Retrieve Node from inventory."""
    logger.debug("Retrieving node %s", node_id)
    return await NodeManager.get_or_404(
        session,
        select_related=[Node.services],
        id=node_id,
    )


@router.post("/", dependencies=[IsAuthenticatedDep])
async def create_node(session: SessionDep, node: NodeWrite) -> Node:
    """Create Node."""
    logger.debug("Creating node %s", node)
    return await NodeManager.create(session, node)


@router.put("/{node_id}", dependencies=[IsAuthenticatedDep])
async def update_node(
    session: SessionDep,
    existing_node: NodeDep,
    updated_node: NodeWrite,
) -> Node:
    """Update Node."""
    logger.debug("Updating node %s", existing_node.id)
    return await NodeManager.update(session, existing_node, updated_node)


@router.delete("/{node_id}", dependencies=[IsAuthenticatedDep])
async def delete_node(session: SessionDep, node: NodeDep) -> NodeResponse:
    """Delete Node."""
    logger.debug("Deleting node %s", node.id)
    return await NodeManager.delete(session, node)


@router.get("/{node_id}/services/", dependencies=[IsAuthenticatedDep])
async def list_services_by_node(
    session: SessionDep,
    node: NodeDep,
    service_type: ServiceTypeEnum | None = None,
) -> list[ServiceResponse]:
    """List Services by Node."""
    logger.debug(
        "Listing services for node '%s' and type '%s'",
        node.id,
        service_type or "all",
    )
    return await ServiceManager.list(
        session,
        select_related=[Service.schemas],
        node_id=node.id,
        type=service_type,
    )


@router.post("/{node_id}/services/", dependencies=[IsAuthenticatedDep])
async def create_service_for_node(
    session: SessionDep,
    node: NodeDep,
    service: ServiceWrite,
) -> Service:
    """Create Service for Node."""
    logger.debug("Creating service for node %s: %s", node.id, service)
    return await ServiceManager.create(session, service, node_id=node.id)
