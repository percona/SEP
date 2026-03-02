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
from collections.abc import Callable
from types import TracebackType
from typing import Any, ClassVar, Self

from async_lru import _LRUCacheWrapper, alru_cache
from pydantic import ConfigDict, field_validator, SecretStr, ValidationError

from app.core.config import settings
from app.core.requests import RemoteAPI
from app.core.utils.dict import remove_falsy_values_from_dict
from app.core.utils.fields import RequiredStr
from app.inventory.models import SourceEnum
from app.sep.config import PMMSettings, sep_settings
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
    :param cluster: The cluster in which the service is running. Defaults to None.
    :type cluster: str | None
    :param replication_set: The replication set in which the service is running. Defaults to None.
    :type replication_set: str | None
    :param custom_labels: Custom labels associated with the service. Defaults to None.
    :type custom_labels: dict[str, Any] | None
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
    :type api_key: SecretStr | None
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
    api_key: SecretStr
    error_detail_key: RequiredStr = "message"
    error_code_key: RequiredStr | None = "code"
    default_to_v3: bool = True

    @property
    def headers(self) -> dict[str, str]:
        """Return the headers to be used in PMM requests.

        Includes content type, accept headers, and authorization with the API key.

        :return: A dictionary containing the headers for PMM API requests.
        :rtype: dict[str, str]
        """
        return {
            **super().headers,
            "Authorization": f"Bearer {self.api_key.get_secret_value()}",
        }

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

    async def get_node(
        self,
        node_id: str,
        *,
        skip_failed_services: bool = True,
        filter_: Callable[[dict[str, Any]], bool] | None = None,
    ) -> Node | None:
        """Retrieve a PMM node by its external ID.

        Send a request to the PMM API to fetch a node's details by its external ID.

        :param node_id: The external identifier of the node to retrieve.
        :type node_id: str
        :param skip_failed_services: Whether to skip services that fail validation.
            Defaults to True.
        :type skip_failed_services: bool
        :param filter_: Optional callable that takes a node or service dict and returns
            True if the item should be included, False if it should be filtered out.
            Used to filter the node and, when loading services, each service.
            Defaults to None.
        :type filter_: Callable[[dict[str, Any]], bool] | None
        :return: The retrieved node instance, or None if filtered out.
        :rtype: Node | None
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
        if filter_ is not None and not filter_(node):
            self.logger.debug(
                "Skipping node %s due to filter",
                node_id,
            )
            return None
        node |= {
            "source": SourceEnum.PMM,
            "type": node_type,
            "services": await self.get_services(
                node_id=node_id,
                skip_failed=skip_failed_services,
                filter_=filter_,
            ),
        }
        return Node.model_validate(node)

    async def get_service(
        self,
        service_id: str,
        *,
        filter_: Callable[[dict[str, Any]], bool] | None = None,
    ) -> PMMService | None:
        """Retrieve a PMM service by its ID.

        Send a request to the PMM API to fetch a service's details by its ID.

        :param service_id: The identifier of the service to retrieve.
        :type service_id: str
        :param filter_: Optional callable that takes a service dict and returns True if
            the service should be included, False if it should be filtered out.
            Defaults to None.
        :type filter_: Callable[[dict[str, Any]], bool] | None
        :return: The retrieved service instance, or None if filtered out.
        :rtype: PMMService | None
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
        if filter_ is not None and not filter_(service):
            self.logger.debug(
                "Skipping service %s due to filter",
                service_id,
            )
            return None
        service["type"] = service_type
        return PMMService.model_validate(service)

    async def get_services(
        self,
        node_id: str = "",
        service_type: str = "",
        external_group: str = "",
        *,
        skip_failed: bool = True,
        filter_: Callable[[dict[str, Any]], bool] | None = None,
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
        :param skip_failed: Whether to skip services that fail validation. Defaults to
            True.
        :type skip_failed: bool
        :param filter_: Optional callable that takes a service dict and returns True if
            the service should be included, False if it should be filtered out.
            Defaults to None.
        :type filter_: Callable[[dict[str, Any]], bool] | None
        :return: A list of PMMService instances retrieved from the API.
        :rtype: list[PMMService]
        :raises ValidationError: If a service fails validation and `skip_failed` is
            False.
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

        services = []
        for services_type, service_list in services_data.items():
            for service in service_list:
                if filter_ is not None and not filter_(service):
                    self.logger.debug(
                        "Skipping service %s due to filter",
                        service.get("service_id"),
                    )
                    continue
                try:
                    services.append(
                        PMMService.model_validate({"type": services_type, **service})
                    )
                except ValidationError:
                    if skip_failed:
                        self.logger.exception(
                            "Validation Error: Skipping service of type %s with data %s",
                            services_type,
                            service,
                        )
                    else:
                        raise
        return services

    async def get_services_by_node_external_id(
        self,
        *,
        skip_failed: bool = True,
        filter_: Callable[[dict[str, Any]], bool] | None = None,
    ) -> defaultdict[RequiredStr, list[PMMService]]:
        """Fetch and group services by node ID from the PMM API.

        Retrieve all services and organize them into a defaultdict where each key is a
        node ID and each value is a list of associated services.

        :param skip_failed: Whether to skip services that fail validation. Defaults to
            True.
        :type skip_failed: bool
        :param filter_: Optional callable that takes a service dict and returns True if
            the service should be included, False if it should be filtered out.
            Defaults to None.
        :type filter_: Callable[[dict[str, Any]], bool] | None
        :return: A defaultdict mapping node IDs to lists of PMMService instances.
        :rtype: defaultdict[RequiredStr, list[PMMService]]
        """
        services_by_node_id = defaultdict(list)
        for service in await self.get_services(
            skip_failed=skip_failed, filter_=filter_
        ):
            services_by_node_id[service.node_id].append(service)
        return services_by_node_id

    async def get_nodes(
        self,
        node_type: str = "",
        *,
        skip_failed: bool = True,
        filter_: Callable[[dict[str, Any]], bool] | None = None,
    ) -> list[Node]:
        """Fetch nodes from the PMM API.

        Retrieve a list of nodes filtered by node type and associate them with their
        services.

        :param node_type: The type of nodes to retrieve (e.g., "generic"). Defaults to
            an empty string, meaning the field won't be used as a filter.
        :type node_type: str
        :param skip_failed: Whether to skip nodes that fail validation. Defaults to
            True.
        :type skip_failed: bool
        :param filter_: Optional callable that takes a node or service dict and returns
            True if the item should be included, False if it should be filtered out.
            Used to filter nodes and, when loading services, each service.
            Defaults to None.
        :type filter_: Callable[[dict[str, Any]], bool] | None
        :return: A list of Node instances retrieved from the API.
        :rtype: list[Node]
        :raises ValidationError: If a node fails validation and `skip_failed` is False.
        """
        services_by_node_id = await self.get_services_by_node_external_id(
            skip_failed=skip_failed, filter_=filter_
        )
        params = remove_falsy_values_from_dict({"node_type": node_type})
        if await self.is_older_than_v3():
            nodes_data = await self.post(
                "/v1/inventory/Nodes/List",
                json=params,
            )
        else:
            nodes_data = await self.get("/v1/inventory/nodes", params=params)

        nodes = []
        for nodes_type, node_list in nodes_data.items():
            for node in node_list:
                if filter_ is not None and not filter_(node):
                    self.logger.debug(
                        "Skipping node %s due to filter",
                        node.get("node_id"),
                    )
                    continue
                try:
                    nodes.append(
                        Node(
                            **node,
                            source=SourceEnum.PMM,
                            type=nodes_type,
                            services=services_by_node_id[node["node_id"]],
                        )
                    )
                except ValidationError:
                    if not skip_failed:
                        raise
                    self.logger.exception(
                        "Failed to validate node of type %s with data: %s",
                        nodes_type,
                        node,
                    )
        return nodes


class PMMSyncer(BaseSyncer):
    """Manage synchronization of PMM inventory entities.

    This class extends `BaseSyncer` to handle synchronization operations specific to PMM
    entities such as nodes and services. It interacts with the PMM remote API to
    retrieve, update, and delete inventory data, ensuring that the local inventory is
    consistent with the remote source.

    :cvar SYNC_TO_LIMIT: The highest entity type that can be synchronized.
        Set to `SyncInventoryEntityTypeEnum.SERVICE`.
    :vartype SYNC_TO_LIMIT: ClassVar[SyncInventoryEntityTypeEnum]
    :param inventory_api: The remote API interface for interacting with the inventory
        system.
    :type inventory_api: RemoteAPI
    :param access_token: The access token used for authenticating with the inventory
        API.
    :type access_token: str
    :param sync_instance: The synchronization instance used to track sync processes.
    :type sync_instance: SyncInstance | None
    :param sync_items: A dictionary mapping tuples of entity type and ID to SyncItem
        objects.
    :type sync_items: dict[tuple[SyncInventoryEntityTypeEnum, int | None], SyncItem]
    :param sync_id: The unique identifier for this synchronization.
    :type sync_id: UUID4
    :param pmm: The PMM remote API data for interacting with the PMM inventory
        system.
    :type pmm: dict[str, Any]
    :param keepalive_api: Whether to keep the PMMRemoteAPI instance alive after
        synchronization. Defaults to True.
    :type keepalive_api: bool
    """

    SYNC_TO_LIMIT: ClassVar[SyncInventoryEntityTypeEnum] = (
        SyncInventoryEntityTypeEnum.SERVICE
    )
    pmm: PMMSettings = sep_settings.PMM
    keepalive_api: bool = True
    _pmm_api: PMMRemoteAPI | None = None

    async def __aenter__(self) -> Self:
        """Enter the asynchronous context manager.

        Overrides from BaseSyncer to also get the PMMRemoteAPI instance from the global
        client registry.

        :return: The `BaseRemoteAPI` instance.
        :rtype: BaseRemoteAPI
        """
        if getattr(self, "_pmm_api", None) is None:
            self._pmm_api = await settings.get_remote_api(
                PMMRemoteAPI, **self.pmm.model_dump()
            )
        return await super().__aenter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException],
        exc_val: BaseException,
        exc_tb: TracebackType,
    ) -> None:
        """Exit the asynchronous context manager.

        Overrides from BaseSyncer to also close the PMMRemoteAPI instance if it was not
        set to be kept alive.

        :param exc_type: The type of exception raised, if any.
        :type exc_type: type[BaseException]
        :param exc_val: The exception instance raised, if any.
        :type exc_val: BaseException
        :param exc_tb: The traceback of the exception raised, if any.
        :type exc_tb: TracebackType
        """
        await super().__aexit__(exc_type, exc_val, exc_tb)
        if not self.keepalive_api and self._pmm_api is not None:
            await self._pmm_api.close()
            self._pmm_api = None

    @property
    def pmm_api(self) -> PMMRemoteAPI:
        """Get the PMMRemoteAPI instance, initializing it if necessary.

        :return: The PMMRemoteAPI instance.
        :rtype: PMMRemoteAPI
        :raises ValueError: If the PMM API client has not been initialized.
        """
        if getattr(self, "_pmm_api", None) is None:
            raise ValueError("PMM API client has not been initialized.")
        return self._pmm_api

    @staticmethod
    def _filter_sep_sync_disabled(item: dict[str, Any]) -> bool:
        """Filter to exclude items (nodes or services) with sep_sync: disabled label.

        Works for both node and service dicts: nodes use "labels" or "custom_labels",
        services use "custom_labels".

        :param item: The node or service dictionary to check.
        :type item: dict[str, Any]
        :return: True if the item should be included, False if it should be filtered out.
        :rtype: bool
        """
        labels = {**item.get("labels", {}), **item.get("custom_labels", {})}
        return labels.get("sep_sync") != "disabled"

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
        logger.debug("Syncable nodes: %s", syncable_nodes)
        for node in await self.pmm_api.get_nodes(
            skip_failed=not self.break_on_error,
            filter_=self._filter_sep_sync_disabled,
        ):
            if (created_node := syncable_nodes.pop(node.external_id, None)) is None:
                logger.debug("Creating new node: %r", node)
                created_node = CreatedNode.model_validate(
                    await self.inventory_api.post(
                        "/",
                        json=node.model_dump(exclude={"services"}),
                    ),
                )
            await self.sync_node(created_node, node)
        logger.debug("Nodes to delete: %s", syncable_nodes)
        for node in syncable_nodes.values():
            await self.delete_node(node)

    async def fetch_node(self, created_node: CreatedNode) -> Node | None:
        """Fetch updated data for a specific node.

        Retrieve the latest information for the specified node from the PMM API.
        Returns None if the node is filtered out (e.g., has sep_sync: disabled).

        :param created_node: The node instance to fetch updated data for.
        :type created_node: CreatedNode
        :return: The updated node data, or None if filtered out.
        :rtype: Node | None
        """
        logger.debug(
            "Fetching node from PMM with external id %s",
            created_node.external_id,
        )
        return await self.pmm_api.get_node(
            created_node.external_id,
            skip_failed_services=not self.break_on_error,
            filter_=self._filter_sep_sync_disabled,
        )

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
        port_to_id = {}
        syncable_services = {}
        for service in created_node.services:
            syncable_services[service.id] = service
            if service.external_id is not None:
                external_id_to_id[service.external_id] = service.id
            if service.port is not None:
                port_to_id[service.port] = service.id
        for service in updated_node.services:
            if (
                created_service := syncable_services.pop(
                    external_id_to_id.get(
                        service.external_id, port_to_id.get(service.port)
                    ),
                    None,
                )
            ) is None:
                logger.info("Creating new service: %r", service)
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

    async def fetch_service(self, created_service: CreatedService) -> PMMService | None:
        """Fetch updated data for a specific service.

        Retrieve the latest information for the specified service from the PMM API.
        Returns None if the service is filtered out (e.g., has sep_sync: disabled).

        :param created_service: The service instance for which to fetch updated data.
        :type created_service: CreatedService
        :return: The updated service data, or None if filtered out.
        :rtype: PMMService | None
        """
        logger.debug(
            "Fetching service from PMM with external id %s",
            created_service.external_id,
        )
        return await self.pmm_api.get_service(
            created_service.external_id,
            filter_=self._filter_sep_sync_disabled,
        )

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

    @field_validator("pmm", mode="before")
    @classmethod
    def merge_global_pmm_setting(cls, value: Any) -> Any:
        """Merge the global PMM settings with any provided PMM settings.

        This validator checks if the provided value is a dictionary and, if so, merges
        it with the global PMM settings defined in `sep_settings`. This allows for any
        PMMSyncer instance to override specific PMM settings while still inheriting
        defaults from the global configuration.

        :param value: The PMM settings value to validate and merge.
        :type value: Any
        :return: The merged PMM settings.
        :rtype: Any
        """
        if isinstance(value, dict):
            return sep_settings.PMM.model_dump() | value
        return value
