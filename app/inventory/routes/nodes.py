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

"""Define the routes for the Nodes resource."""

import logging

from fastapi import APIRouter, status

from app.api.deps import IsAuthenticatedDep
from app.core.exceptions import HTTPBadRequestException
from app.core.pagination import PaginatedResponse
from app.core.pagination.deps import PaginationDep
from app.core.utils.fields import NonEmptyStr
from app.inventory.crud import HostSystemObservationManager, NodeManager, ServiceManager
from app.inventory.deps import (
    HostSystemObservationDep,
    NodeDep,
    NodeListQueryDep,
    ServiceListQueryDep,
    SessionDep,
)
from app.inventory.models import (
    HostSystemObservationResponse,
    HostSystemObservationWrite,
    Node,
    NodeResponse,
    NodeWrite,
    Service,
    ServiceResponse,
    ServiceTypeEnum,
    ServiceWrite,
    SourceEnum,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/nodes", tags=["nodes"])


@router.get("/", dependencies=[IsAuthenticatedDep])
async def list_nodes(
    session: SessionDep,
    pagination: PaginationDep,
    list_query: NodeListQueryDep,
    external_id: NonEmptyStr | None = None,
    source: SourceEnum | None = None,
    node_type: NonEmptyStr | None = None,
) -> PaginatedResponse[NodeResponse]:
    """List Nodes from Inventory."""
    logger.debug(
        "Listing nodes for source '%s' and type '%s'",
        source or "all",
        node_type or "all",
    )
    return await NodeManager.list_query_paginated(
        session,
        list_query=list_query,
        select_related=[Node.services],
        pagination=pagination,
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


@router.post(
    "/", dependencies=[IsAuthenticatedDep], status_code=status.HTTP_201_CREATED
)
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


@router.delete(
    "/{node_id}",
    dependencies=[IsAuthenticatedDep],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_node(session: SessionDep, node: NodeDep) -> None:
    """Delete Node."""
    logger.debug("Deleting node %s", node.id)
    await NodeManager.delete(session, node)


@router.get("/{node_id}/system-observation", dependencies=[IsAuthenticatedDep])
async def retrieve_host_system_observation(
    observation: HostSystemObservationDep,
) -> HostSystemObservationResponse:
    """Retrieve host system observation for a node."""
    return observation


@router.put("/{node_id}/system-observation", dependencies=[IsAuthenticatedDep])
async def upsert_host_system_observation(
    session: SessionDep,
    node: NodeDep,
    data: HostSystemObservationWrite,
) -> HostSystemObservationResponse:
    """Upsert host system observation for a node."""
    data.node_id = node.id
    obs, created = await HostSystemObservationManager.get_or_create(
        session, data, filter_include={"node_id"}
    )
    if not created:
        obs = await HostSystemObservationManager.update(session, obs, data)
    return obs


@router.get("/{node_id}/services/", dependencies=[IsAuthenticatedDep])
async def list_services_by_node(
    session: SessionDep,
    node: NodeDep,
    pagination: PaginationDep,
    list_query: ServiceListQueryDep,
    service_type: ServiceTypeEnum | None = None,
) -> PaginatedResponse[ServiceResponse]:
    """List Services by Node."""
    logger.debug(
        "Listing services for node '%s' and type '%s'",
        node.id,
        service_type or "all",
    )
    return await ServiceManager.list_query_paginated(
        session,
        list_query=list_query,
        select_related=[Service.schemas],
        pagination=pagination,
        node_id=node.id,
        type=service_type,
    )


@router.post(
    "/{node_id}/services/",
    dependencies=[IsAuthenticatedDep],
    status_code=status.HTTP_201_CREATED,
)
async def create_service_for_node(
    session: SessionDep,
    node: NodeDep,
    service: ServiceWrite,
) -> Service:
    """Create Service for Node."""
    if service.external_id and not node.source:
        raise HTTPBadRequestException(
            "Cannot set external_id if the service's node has no source",
        )
    logger.debug("Creating service for node %s: %s", node.id, service)
    return await ServiceManager.create(session, service, node_id=node.id)
