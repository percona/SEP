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
from types import TracebackType
from typing import Any, ClassVar, Self

from async_lru import alru_cache
from pydantic import field_validator

from app.core.config import settings
from app.inventory.models import SourceEnum
from app.sep.clients.pmm import PMMRemoteAPI, PMMService
from app.sep.config import PMMSettings, sep_settings
from app.sep.inventory import CreatedNode, CreatedService, Node
from app.sep.models import SyncInventoryEntityTypeEnum
from app.sep.sync.models import BaseSyncer

logger = logging.getLogger(__name__)


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
