"""Implement models and utilities for the PMM Inventory Sync."""

import logging
from collections import defaultdict
from typing import ClassVar

from async_lru import alru_cache
from pydantic import Field

from app.core.fields import RequiredStr
from app.core.requests import RemoteAPI
from app.inventory.models import SourceEnum
from app.sep.inventory import CreatedNode
from app.sep.inventory import CreatedService
from app.sep.inventory import CreatedServiceNode
from app.sep.inventory import Node
from app.sep.inventory import Service
from app.sep.models import SyncInventoryEntityTypeEnum
from app.sep.sync.models import BaseSyncer

logger = logging.getLogger(__name__)


class PMMNode(Node):
    """Represent a PMM-specific inventory node.

    This class extends the base `Node` model to include PMM-specific attributes
    such as associated services.

    Attributes
    ----------
    address : RequiredStr
        The network address of the node.
    external_id : RequiredStr or EmptyStrToNone, optional
        The external identifier for the node, aliased as "node_id". Defaults to None.
    name : RequiredStr
        The name of the node, aliased as "node_name".
    type : RequiredStr, optional
        The type of the node (e.g., "generic"), aliased as "node_type".
        Defaults to "generic".
    source : SourceEnum or EmptyStrToNone, optional
        The source of the node information. Defaults to None.
    services : list of PMMService
        A list of services associated with the node.

    """

    services: list["PMMService"]


class PMMService(Service):
    """Represent a PMM-specific inventory service.

    This class extends the base `Service` model to include PMM-specific attributes
    such as the node string identifier (external_id).

    Attributes
    ----------
    node_id : str
        The identifier of the node to which the service is associated.

    """

    node_id: str


class PMMRemoteAPI(RemoteAPI):
    """Handle remote API interactions specific to PMM.

    Provides methods to interact with the PMM inventory system, including fetching nodes
    and services, and managing service associations.

    """

    async def get_node(self, node_id: str) -> PMMNode:
        """Retrieve a PMM node by its external ID.

        Send a request to the PMM API to fetch a node's details by its external ID.

        Parameters
        ----------
        node_id : str
            The external identifier of the node to retrieve.

        Returns
        -------
        PMMNode
            The retrieved node instance.

        """
        node_data = await self.post(
            "/v1/inventory/Nodes/Get",
            json={"node_id": node_id},
        )
        node_type, node = next(iter(node_data.items()))
        node |= {
            "source": SourceEnum.PMM,
            "type": node_type,
            "services": await self.get_services(node_id=node_id),
        }
        return PMMNode.model_validate(node)

    async def get_service(self, service_id: str) -> PMMService:
        """Retrieve a PMM service by its ID.

        Send a request to the PMM API to fetch a service's details by its ID.

        Parameters
        ----------
        service_id : str
            The identifier of the service to retrieve.

        Returns
        -------
        PMMService
            The retrieved service instance.

        """
        service_data = await self.post(
            "/v1/inventory/Services/Get",
            json={"service_id": service_id},
        )
        service_type, service = next(iter(service_data.items()))
        service["type"] = service_type
        return PMMService.model_validate(service)

    async def get_services(
        self,
        node_id: str = "",
        service_type: str = "",
        external_group: str = "",
    ) -> list[PMMService]:
        """Fetch services from the PMM API.

        Retrieve a list of services filtered by node ID, service type, and external
        group.

        Parameters
        ----------
        node_id : str, optional
            The ID of the node to filter services by. Defaults to an empty string,
            meaning the field won't be used as a filter.
        service_type : str, optional
            The type of services to filter by. Defaults to an empty string,
            meaning the field won't be used as a filter.
        external_group : str, optional
            The external group to filter services by. Defaults to an empty string,
            meaning the field won't be used as a filter.

        Returns
        -------
        list of PMMService
            A list of PMMService instances retrieved from the API.

        """
        data = {
            "node_id": node_id,
            "service_type": service_type,
            "external_group": external_group,
        }
        services_data = await self.post("/v1/inventory/Services/List", json=data)
        return [
            PMMService.model_validate({"type": service_type, **service})
            for service_type, services in services_data.items()
            for service in services
        ]

    async def get_services_by_node_external_id(
        self,
    ) -> defaultdict[RequiredStr, list[PMMService]]:
        """Fetch and group services by node ID from the PMM API.

        Retrieve all services and organize them into a defaultdict where each key is a
        node ID and each value is a list of associated services.

        Returns
        -------
        defaultdict[RequiredStr, list[PMMService]]
            A defaultdict mapping node IDs to lists of PMMService instances.

        """
        services_by_node_id = defaultdict(list)
        for service in await self.get_services():
            services_by_node_id[service.node_id].append(service)
        return services_by_node_id

    async def get_nodes(self, node_type: str = "") -> list[PMMNode]:
        """Fetch nodes from the PMM API.

        Retrieve a list of nodes filtered by node type and associate them with their
        services.

        Parameters
        ----------
        node_type : str, optional
            The type of nodes to retrieve (e.g., "generic"). Defaults to an empty
            string, meaning the field won't be used as a filter.

        Returns
        -------
        list of PMMNode
            A list of PMMNode instances retrieved from the API.

        """
        services_by_node_id = await self.get_services_by_node_external_id()
        nodes_data = await self.post(
            "/v1/inventory/Nodes/List",
            json={"node_type": node_type},
        )
        return [
            PMMNode(
                **node,
                source=SourceEnum.PMM,
                type=node_type,
                services=services_by_node_id[node["node_id"]],
            )
            for node_type, nodes in nodes_data.items()
            for node in nodes
        ]


class PMMSyncer(BaseSyncer):
    """Manage synchronization of PMM inventory entities.

    This class extends `BaseSyncer` to handle synchronization operations specific to PMM
    entities such as nodes and services. It interacts with the PMM remote API to
    retrieve, update, and delete inventory data, ensuring that the local inventory is
    consistent with the remote source.

    Attributes
    ----------
    SYNC_TO_LIMIT : SyncInventoryEntityTypeEnum
        The upper limit of entity types that can be synchronized. Set to
        `SyncInventoryEntityTypeEnum.SERVICE`.
    pmm_api : PMMRemoteAPI
        The PMM remote API interface for interacting with the PMM inventory system.

    """

    SYNC_TO_LIMIT: ClassVar[SyncInventoryEntityTypeEnum] = (
        SyncInventoryEntityTypeEnum.SERVICE
    )
    pmm_api: PMMRemoteAPI = Field(validation_alias="pmm")

    @alru_cache
    async def get_inventory_nodes(
        self,
        external_id: str | None = None,
        node_type: str | None = None,
    ) -> list[CreatedNode]:
        """Retrieve PMM inventory nodes.

        Override the base method to fetch nodes from the PMM inventory system by
        always specifying the source to be PMM.

        Parameters
        ----------
        external_id : str or None, optional
            The external identifier of the node. Defaults to None.
        node_type : str or None, optional
            The type of the node (e.g., "generic"). Defaults to None.

        Returns
        -------
        list of CreatedNode
            A list of retrieved CreatedNode instances.

        """
        return await super().get_inventory_nodes(external_id, SourceEnum.PMM, node_type)

    async def perform_inventory_sync(self) -> None:
        """Perform the inventory synchronization process.

        Synchronize the entire inventory by fetching nodes from the PMM API, creating or
        updating corresponding nodes in the local inventory, and deleting any nodes that
        no longer exist in the PMM system.
        """
        syncable_nodes = {}
        for node in await self.get_inventory_nodes():
            syncable_nodes[node.external_id] = node
        for node in await self.pmm_api.get_nodes():
            if (created_node := syncable_nodes.pop(node.external_id, None)) is None:
                logger.debug("Creating new node: %s", node)
                created_node = CreatedNode.model_validate(
                    await self.inventory_api.post(
                        "/",
                        json=node.model_dump(exclude={"services"}),
                    ),
                )
            await self.sync_node(created_node, node)
        for node in syncable_nodes.values():
            await self.delete_node(node)

    async def fetch_node(self, created_node: CreatedNode) -> PMMNode:
        """Fetch updated data for a specific node.

        Retrieve the latest information for the specified node from the PMM API.

        Parameters
        ----------
        created_node : CreatedNode
            The node instance to fetch updated data for.

        Returns
        -------
        PMMNode
            The updated node data.

        """
        logger.debug(
            "Fetching node from PMM with external id %s",
            created_node.external_id,
        )
        return await self.pmm_api.get_node(created_node.external_id)

    async def perform_node_sync(
        self,
        created_node: CreatedNode,
        updated_node: PMMNode,
    ) -> None:
        """Synchronize data for a specific node.

        Update the local inventory node with data from the PMM API and handle associated
        services.

        Parameters
        ----------
        created_node : CreatedNode
            The local node instance to synchronize.
        updated_node : PMMNode
            The updated node data fetched from the PMM API.

        """
        logger.info("Updating node %s: %s", created_node.id, updated_node)
        CreatedNode.model_validate(
            await self.inventory_api.put(
                f"/{created_node.id}",
                json=updated_node.model_dump(),
            ),
        )
        external_id_to_id = {}
        syncable_services = {}
        for service in created_node.services:
            syncable_services[service.id] = service
            if service.external_id is not None:
                external_id_to_id[service.external_id] = service.id
        for service in updated_node.services:
            if (
                created_service := syncable_services.pop(
                    external_id_to_id.get(service.external_id),
                    None,
                )
            ) is None:
                logger.info("Creating new service: %s", service)
                created_service = CreatedService.model_validate(
                    await self.inventory_api.post(
                        f"/{created_node.id}/services/",
                        json=service.model_dump(exclude={"node_id"}),
                    ),
                )
                created_service.node = CreatedServiceNode.model_validate(created_node)
            await self.sync_service(created_service, service)
        for service in syncable_services.values():
            await self.delete_service(service)

    async def perform_service_sync(
        self,
        created_service: CreatedService,
        updated_service: PMMService,
    ) -> None:
        """Synchronize data for a specific service.

        Update the local inventory service with data from the PMM API.

        Parameters
        ----------
        created_service : CreatedService
            The local service instance to synchronize.
        updated_service : PMMService
            The updated service data fetched from the PMM API.

        """
        updated_service_data = updated_service.model_dump()
        if created_service.node.external_id == updated_service.node_id:
            updated_service_data["node_id"] = created_service.node.id
        else:
            nodes = await self.get_inventory_nodes(
                external_id=created_service.node.external_id,
            )
            updated_service_data["node_id"] = nodes[0].id
        logger.info("Updating service %s: %s", created_service.id, updated_service_data)
        CreatedService.model_validate(
            await self.inventory_api.put(
                f"/services/{created_service.id}",
                json=updated_service_data,
            ),
        )

    @classmethod
    def can_sync_node(cls, node: CreatedNode) -> bool:
        """Determine if a specific node can be synchronized.

        Override the base method to check if the node's source is PMM.

        Parameters
        ----------
        node : CreatedNode
            The node instance to check.

        Returns
        -------
        bool
            `True` if the node can be synchronized, `False` otherwise.

        """
        return super().can_sync_node(node) and node.source == SourceEnum.PMM

    @classmethod
    def can_sync_service(cls, service: CreatedService) -> bool:
        """Determine if a specific service can be synchronized.

        Override the base method to check if the service's node's source is PMM.

        Parameters
        ----------
        service : CreatedService
            The service instance to check.

        Returns
        -------
        bool
            `True` if the service can be synchronized, `False` otherwise.

        """
        return (
            super().can_sync_service(service) and service.node.source == SourceEnum.PMM
        )
