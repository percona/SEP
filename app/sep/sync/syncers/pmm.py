# Copyright (C) 2025 Percona LLC
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

"""Implement models and utilities for the PMM Inventory Sync."""

import logging
from collections import defaultdict
from typing import ClassVar, Self

from async_lru import _LRUCacheWrapper, alru_cache
from pydantic import AliasChoices, ConfigDict, Field

from app.core.config import settings
from app.core.requests import RemoteAPI
from app.core.utils.dict import remove_falsy_values_from_dict
from app.core.utils.fields import RequiredStr
from app.inventory.models import SourceEnum
from app.sep.inventory import CreatedNode, CreatedService, Node, Service
from app.sep.models import SyncInventoryEntityTypeEnum
from app.sep.sync.models import BaseSyncer

logger = logging.getLogger(__name__)


class PMMService(Service):
    """Represent a PMM-specific inventory service.

    This class extends the base `Service` model to include PMM-specific attributes
    such as the node string identifier (external_id).

    :param environment: The environment in which the service is running (e.g.,
        "production", "staging"). Defaults to None.
    :type environment: str | None
    :param external_id: The external identifier for the service, aliased as
        "service_id". Defaults to None.
    :type external_id: RequiredStr | EmptyStrToNone
    :param name: The name of the service, aliased as "service_name".
    :type name: RequiredStr
    :param port: The port number on which the service is running, aliased as
        "service_port". Defaults to None.
    :type port: int | EmptyStrToNone
    :param type: The type of the service (e.g., "service_type"), aliased as
        "service_type". Defaults to "generic".
    :type type: RequiredStr
    :param node_id: The identifier of the node to which the service is associated.
    :type node_id: str
    """

    node_id: str


class PMMRemoteAPI(RemoteAPI):
    """Handle remote API interactions specific to PMM.

    Provides methods to interact with the PMM inventory system, including fetching nodes
    and services, and managing service associations.

    :param endpoint: The base URL for the external API endpoint.
    :type endpoint: HttpUrl
    :param verify_ssl: Whether to verify SSL certificates. Defaults to True.
    :type verify_ssl: bool
    :param ssl_cafile: Path to the SSL certificate authority file. Defaults to None.
    :type ssl_cafile: RelativeFilePath | None
    :param ssl_keyfile: Path to the SSL key file. Defaults to None.
    :type ssl_keyfile: RelativeFilePath | None
    :param ssl_certfile: Path to the SSL certificate file. Defaults to None.
    :type ssl_certfile: RelativeFilePath | None
    :param logger_name: Name to use for the logger. Defaults to `__name__`.
    :type logger_name: str
    :param api_key: The API key for authentication. Defaults to None.
    :type api_key: str | None
    :param auth_scheme: The authentication scheme to use (e.g., "Bearer", "Basic").
        Defaults to "Bearer".
    :type auth_scheme: RequiredStr
    :param error_detail_key: The key to expect errors details to be. Defaults to
        "message".
    :type error_detail_key: RequiredStr
    :param error_code_key: The key to expect error codes to be, or None if no error
        code is expected. Defaults to "code".
    :type error_code_key: RequiredStr | None
    :param default_to_v3: Whether to default to PMM v3 API endpoints if the API version
        cannot be determined. Defaults to True.
    :type default_to_v3: bool
    """

    model_config = ConfigDict(ignored_types=(_LRUCacheWrapper,))
    error_detail_key: RequiredStr = "message"
    error_code_key: RequiredStr | None = "code"
    default_to_v3: bool = True

    @alru_cache(ttl=600)
    async def is_older_than_v3(self) -> bool:
        """Check if the PMM version is older than 3.

        This method retrieves the PMM version and checks if it is older than 3.0.0.

        :return: True if the PMM version is older than 3, False otherwise.
        :rtype: bool
        """
        v3_major = 3
        try:
            version = await self.get_version()
        except (TypeError, KeyError):
            self.logger.exception(
                "Failed to retrieve PMM version, defaulting to %s",
                "v3" if self.default_to_v3 else "v2",
            )
            return not self.default_to_v3

        try:
            is_older = int(version.split(".")[0]) < v3_major
        except (AttributeError, ValueError):
            self.logger.exception(
                "Failed to parse PMM version, defaulting to %s: %s",
                "v3" if self.default_to_v3 else "v2",
                version,
            )
            return not self.default_to_v3

        if is_older:
            self.logger.warning(
                "Deprecation Warning: Support for PMM version < 3.0.0 is deprecated and will be removed in a future version (version found is %s).",
                version,
            )
        return is_older

    async def get_version(self) -> str:
        """Retrieve the PMM version.

        :return: The version of the PMM instance.
        :rtype: str
        """
        version_data = await self.get("/v1/version")
        return version_data["version"]

    async def get_node(self, node_id: str) -> Node:
        """Retrieve a PMM node by its external ID.

        Send a request to the PMM API to fetch a node's details by its external ID.

        :param node_id: The external identifier of the node to retrieve.
        :type node_id: str
        :return: The retrieved node instance.
        :rtype: Node
        """
        if await self.is_older_than_v3():
            node_data = await self.post(
                "/v1/inventory/Nodes/Get",
                json={"node_id": node_id},
            )
        else:
            node_data = await self.get(
                f"/v1/inventory/nodes/{node_id}",
            )
        node_type, node = next(iter(node_data.items()))
        node |= {
            "source": SourceEnum.PMM,
            "type": node_type,
            "services": await self.get_services(node_id=node_id),
        }
        return Node.model_validate(node)

    async def get_service(self, service_id: str) -> PMMService:
        """Retrieve a PMM service by its ID.

        Send a request to the PMM API to fetch a service's details by its ID.

        :param service_id: The identifier of the service to retrieve.
        :type service_id: str
        :return: The retrieved service instance.
        :rtype: PMMService
        """
        if await self.is_older_than_v3():
            service_data = await self.post(
                "/v1/inventory/Services/Get",
                json={"service_id": service_id},
            )
        else:
            service_data = await self.get(
                f"/v1/inventory/services/{service_id}",
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

        :param node_id: The ID of the node to filter services by. Defaults to an empty
            string, meaning the field won't be used as a filter.
        :type node_id: str
        :param service_type: The type of services to filter by. Defaults to an empty
            string, meaning the field won't be used as a filter.
        :type service_type: str
        :param external_group: The external group to filter services by. Defaults to an
            empty string, meaning the field won't be used as a filter.
        :type external_group: str
        :return: A list of PMMService instances retrieved from the API.
        :rtype: list[PMMService]
        """
        params = {
            "node_id": node_id,
            "service_type": service_type,
            "external_group": external_group,
        }
        params = remove_falsy_values_from_dict(params)
        if await self.is_older_than_v3():
            services_data = await self.post("/v1/inventory/Services/List", json=params)
        else:
            services_data = await self.get("/v1/inventory/services", params=params)
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

        :return: A defaultdict mapping node IDs to lists of PMMService instances.
        :rtype: defaultdict[RequiredStr, list[PMMService]]
        """
        services_by_node_id = defaultdict(list)
        for service in await self.get_services():
            services_by_node_id[service.node_id].append(service)
        return services_by_node_id

    async def get_nodes(self, node_type: str = "") -> list[Node]:
        """Fetch nodes from the PMM API.

        Retrieve a list of nodes filtered by node type and associate them with their
        services.

        :param node_type: The type of nodes to retrieve (e.g., "generic"). Defaults to
            an empty string, meaning the field won't be used as a filter.
        :type node_type: str
        :return: A list of Node instances retrieved from the API.
        :rtype: list[Node]
        """
        services_by_node_id = await self.get_services_by_node_external_id()
        params = remove_falsy_values_from_dict({"node_type": node_type})
        if await self.is_older_than_v3():
            nodes_data = await self.post(
                "/v1/inventory/Nodes/List",
                json=params,
            )
        else:
            nodes_data = await self.get("/v1/inventory/nodes", params=params)
        return [
            Node(
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

    :cvar SYNC_TO_LIMIT: The highest entity type that can be synchronized.
        Set to `SyncInventoryEntityTypeEnum.SERVICE`.
    :vartype SYNC_TO_LIMIT: ClassVar[SyncInventoryEntityTypeEnum]
    :param pmm_api: The PMM remote API interface for interacting with the PMM inventory
        system.
    :type pmm_api: PMMRemoteAPI
    """

    SYNC_TO_LIMIT: ClassVar[SyncInventoryEntityTypeEnum] = (
        SyncInventoryEntityTypeEnum.SERVICE
    )
    pmm_api: PMMRemoteAPI = Field(validation_alias=AliasChoices("pmm", "PMM"))

    async def __aenter__(self) -> Self:
        """Enter the asynchronous context manager.

        Overrides from BaseSyncer to also initialize the pmm_api's ClientSession.

        :return: The `BaseRemoteAPI` instance.
        :rtype: BaseRemoteAPI
        """
        self.pmm_api.session = await settings.get_extra_client_session(
            self.pmm_api.endpoint, self.pmm_api.api_key
        )
        return await super().__aenter__()

    @alru_cache
    async def get_inventory_nodes(
        self,
        external_id: str | None = None,
        node_type: str | None = None,
    ) -> list[CreatedNode]:
        """Retrieve PMM inventory nodes.

        Override the base method to fetch nodes from the PMM inventory system by
        always specifying the source to be PMM.

        :param external_id: The external identifier of the node. Defaults to None,
            meaning it won't be used as a filter.
        :type external_id: str | None
        :param node_type: The type of the node (e.g., "generic"). Defaults to None,
            meaning it won't be used as a filter.
        :type node_type: str | None
        :return: A list of retrieved CreatedNode instances.
        :rtype: list[CreatedNode]
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

    async def fetch_node(self, created_node: CreatedNode) -> Node:
        """Fetch updated data for a specific node.

        Retrieve the latest information for the specified node from the PMM API.

        :param created_node: The node instance to fetch updated data for.
        :type created_node: CreatedNode
        :return: The updated node data.
        :rtype: Node
        """
        logger.debug(
            "Fetching node from PMM with external id %s",
            created_node.external_id,
        )
        return await self.pmm_api.get_node(created_node.external_id)

    async def perform_node_sync(
        self,
        created_node: CreatedNode,
        updated_node: Node,
    ) -> None:
        """Synchronize data for a specific node.

        Update the local inventory node with data from the PMM API and handle associated
        services.

        :param created_node: The local node instance to synchronize.
        :type created_node: CreatedNode
        :param updated_node: The updated node data fetched from the PMM API.
        :type updated_node: Node
        """
        await self.update_node(created_node, updated_node)
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
                created_service.node = created_node.model_copy(update={"services": []})
            await self.sync_service(created_service, service)
        for service in syncable_services.values():
            await self.delete_service(service)

    async def fetch_service(self, created_service: CreatedService) -> PMMService:
        """Fetch updated data for a specific service.

        Retrieve the latest information for the specified service from the PMM API.

        :param created_service: The service instance for which to fetch updated data.
        :type created_service: CreatedService
        :return: The updated service data.
        :rtype: PMMService
        """
        logger.debug(
            "Fetching service from PMM with external id %s",
            created_service.external_id,
        )
        return await self.pmm_api.get_service(created_service.external_id)

    async def perform_service_sync(
        self,
        created_service: CreatedService,
        updated_service: PMMService,
    ) -> None:
        """Synchronize data for a specific service.

        Update the local inventory service with data from the PMM API.

        :param created_service: The local service instance to synchronize.
        :type created_service: CreatedService
        :param updated_service: The updated service data fetched from the PMM API.
        :type updated_service: PMMService
        """
        if created_service.node.external_id != updated_service.node_id:
            nodes = await self.get_inventory_nodes(
                external_id=created_service.node.external_id,
            )
            created_service.node_id = nodes[0].id
        await self.update_service(created_service, updated_service)

    @classmethod
    def can_sync_node(cls, node: CreatedNode) -> bool:
        """Determine if a specific node can be synchronized.

        Override the base method to check if the node's source is PMM.

        :param node: The node instance to check.
        :type node: CreatedNode
        :return: `True` if the node can be synchronized, `False` otherwise.
        :rtype: bool
        """
        return super().can_sync_node(node) and node.source == SourceEnum.PMM

    @classmethod
    def can_sync_service(cls, service: CreatedService) -> bool:
        """Determine if a specific service can be synchronized.

        Override the base method to check if the service's node's source is PMM.

        :param service: The service instance to check.
        :type service: CreatedService
        :return: `True` if the service can be synchronized, `False` otherwise.
        :rtype: bool
        """
        return (
            super().can_sync_service(service)
            and service.node.source == SourceEnum.PMM
            and service.external_id
        )
