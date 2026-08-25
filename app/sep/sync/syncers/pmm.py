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

"""Implement models and utilities for the PMM Inventory Sync."""

import logging
from collections.abc import Awaitable, Callable, Iterable
from types import TracebackType
from typing import Annotated, Any, ClassVar, Self

from annotated_types import Ge
from async_lru import alru_cache

from app.core.config import settings
from app.inventory.models import SourceEnum
from app.sep.clients.pmm import (
    PMMInventorySnapshot,
    PMMRemoteAPI,
    PMMService,
)
from app.sep.crud import SyncEntityAbsenceManager, SyncInstanceManager
from app.sep.inventory import CreatedEntity, CreatedNode, CreatedService, Node
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
    :param keepalive_api: Whether to keep the PMMRemoteAPI instance alive after
        synchronization. Defaults to True.
    :type keepalive_api: bool
    """

    SYNC_TO_LIMIT: ClassVar[SyncInventoryEntityTypeEnum] = (
        SyncInventoryEntityTypeEnum.SERVICE
    )
    keepalive_api: bool = True
    # The floor is 2, not 1: at 1 the grace counter collapses back to deleting on a
    # single reported absence, which is the destructive behaviour it exists to end.
    # Expressed as an annotation constraint for the reason ``stale_run_after`` is.
    missing_grace_generations: Annotated[int, Ge(2)] = 2
    _pmm_api: PMMRemoteAPI | None = None
    _generation: PMMInventorySnapshot | None = None

    async def __aenter__(self) -> Self:
        """Enter the asynchronous context manager.

        Overrides from BaseSyncer to also get the PMMRemoteAPI instance from the global
        client registry.

        :return: The `BaseRemoteAPI` instance.
        :rtype: BaseRemoteAPI
        """
        if getattr(self, "_pmm_api", None) is None:
            self._pmm_api = await settings.get_remote_api(
                PMMRemoteAPI, **settings.PMM.model_dump()
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

    async def _fetch_snapshot(self) -> PMMInventorySnapshot:
        """Fetch an inventory snapshot, retrying once on cross-list disagreement.

        Orphaned services mean the node list and the service list were read at
        moments PMM did not agree about. A single re-read settles a transient
        disagreement; a persistent one leaves the generation incomplete.

        :return: The snapshot to reconcile this generation against.
        :raises ValidationError: If an entity fails validation and ``break_on_error``
            is set.
        """
        snapshot = await self.pmm_api.get_inventory_snapshot(
            skip_failed=not self.break_on_error,
            filter_=self._filter_sep_sync_disabled,
        )
        if snapshot.diagnostics.orphan_service_node_ids:
            logger.warning(
                "PMM node and service lists disagree (orphan node ids: %s); refetching",
                snapshot.diagnostics.orphan_service_node_ids,
            )
            snapshot = await self.pmm_api.get_inventory_snapshot(
                skip_failed=not self.break_on_error,
                filter_=self._filter_sep_sync_disabled,
            )
        return snapshot

    async def _generation_permits_retirement(self) -> bool:
        """Check whether this generation may retire anything at all.

        :return: `True` only for a complete generation belonging to a run that still
            owns its ``SyncInstance``.
        """
        if self._generation is None or not self._generation.diagnostics.is_complete:
            return False
        return await SyncInstanceManager.is_still_owned(
            self._session,
            self.sync_instance.id,
        )

    async def _retire_absent(
        self,
        entity_type: SyncInventoryEntityTypeEnum,
        absent_entities: Iterable[CreatedEntity],
        delete: Callable[[Any], Awaitable[None]],
        *,
        permitted: bool,
        filtered_external_ids: set[str],
    ) -> None:
        """Advance the missing-grace counter for absent entities and retire the spent.

        An entity excluded by the caller's filter is held without its counter moving:
        an operator exclusion is evidence in neither direction, exactly like an
        incomplete generation.

        :param entity_type: The type of the absent entities.
        :param absent_entities: The local entities this generation did not report.
        :param delete: The retirement call to make once grace is spent.
        :param permitted: Whether this generation may retire anything.
        :param filtered_external_ids: External IDs excluded by the fetch filter.
        :raises SyncFailError: If holding or retiring an entity fails and
            ``break_on_error`` is set.
        :raises HTTPBadRequestException: If a ledger write hits a database error.
        """
        for created_entity in absent_entities:
            excluded = created_entity.external_id in filtered_external_ids
            if not permitted or excluded:
                await self.hold_entity(entity_type, created_entity)
                continue
            missing = await SyncEntityAbsenceManager.record_missing(
                self._session,
                self.get_name(),
                entity_type,
                created_entity.id,
            )
            if missing < self.missing_grace_generations:
                await self.hold_entity(entity_type, created_entity)
                continue
            await delete(created_entity)
            await SyncEntityAbsenceManager.clear(
                self._session,
                self.get_name(),
                entity_type,
                created_entity.id,
            )

    async def perform_inventory_sync(self) -> None:
        """Perform the inventory synchronization process.

        Synchronize the entire inventory by fetching nodes from the PMM API and
        creating or updating corresponding nodes in the local inventory. A node that
        the fetch did not report is retired only once a complete generation has
        reported it absent ``missing_grace_generations`` times in a row. A partial
        read is not evidence that anything disappeared from PMM.

        :raises ValidationError: If an entity fails validation and ``break_on_error``
            is set.
        :raises SyncFailError: If synchronizing an entity fails and ``break_on_error``
            is set.
        :raises HTTPBadRequestException: If a ledger write hits a database error.
        """
        syncable_nodes: dict[str | None, CreatedNode] = {}
        for node in await self.get_inventory_nodes():
            syncable_nodes[node.external_id] = node
        logger.debug("Syncable nodes: %s", syncable_nodes)
        snapshot = await self._fetch_snapshot()
        self._generation = snapshot
        self._snapshot_complete = snapshot.diagnostics.is_complete
        try:
            present_ids: list[int | None] = []
            for node in snapshot.nodes:
                if (created_node := syncable_nodes.pop(node.external_id, None)) is None:
                    logger.debug("Creating new node: %r", node)
                    created_node = CreatedNode.model_validate(
                        await self.inventory_api.post(
                            "/nodes/",
                            json=node.model_dump(exclude={"services"}),
                        ),
                    )
                present_ids.append(created_node.id)
                await self.sync_node(created_node, node)
            logger.debug("Nodes absent from PMM: %s", syncable_nodes)
            permitted = await self._generation_permits_retirement()
            if permitted:
                await SyncEntityAbsenceManager.clear(
                    self._session,
                    self.get_name(),
                    SyncInventoryEntityTypeEnum.NODE,
                    *present_ids,
                )
            await self._retire_absent(
                SyncInventoryEntityTypeEnum.NODE,
                syncable_nodes.values(),
                self.delete_node,
                permitted=permitted,
                filtered_external_ids=snapshot.diagnostics.filtered_node_ids,
            )
        finally:
            self._generation = None

    async def fetch_node(self, created_node: CreatedNode) -> Node | None:
        """Fetch updated data for a specific node.

        Retrieve the latest information for the specified node from the PMM API.
        Returns None if the node is filtered out (e.g., has sep_sync: disabled).

        :param created_node: The node instance to fetch updated data for.
        :return: The updated node data, or None if filtered out.
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

        Services are retired under the same generation gate as nodes. A call that did
        not arrive from a full inventory generation, such as an operator-triggered
        single-node refresh, has no generation to judge absence against, so it is
        upsert-only.

        :param created_node: The local node instance to synchronize.
        :param updated_node: The updated node data fetched from the PMM API.
        :raises SyncFailError: If synchronizing, holding or retiring a service fails
            and ``break_on_error`` is set.
        :raises HTTPBadRequestException: If a ledger write hits a database error.
        """
        await self.update_node(created_node, updated_node)
        external_id_to_id: dict[str, int] = {}
        port_to_id: dict[int, int] = {}
        syncable_services: dict[int | None, CreatedService] = {}
        for service in created_node.services:
            syncable_services[service.id] = service
            if service.external_id is not None:
                external_id_to_id[service.external_id] = service.id
            if service.port is not None:
                port_to_id[service.port] = service.id
        present_ids: list[int | None] = []
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
                        f"/nodes/{created_node.id}/services/",
                        json=service.model_dump(exclude={"node_id"}),
                    ),
                )
                created_service.node = created_node.model_copy(update={"services": []})
            present_ids.append(created_service.id)
            await self.sync_service(created_service, service)
        permitted = await self._generation_permits_retirement()
        filtered_service_ids = (
            self._generation.diagnostics.filtered_service_ids
            if self._generation is not None
            else set()
        )
        if permitted:
            await SyncEntityAbsenceManager.clear(
                self._session,
                self.get_name(),
                SyncInventoryEntityTypeEnum.SERVICE,
                *present_ids,
            )
        await self._retire_absent(
            SyncInventoryEntityTypeEnum.SERVICE,
            syncable_services.values(),
            self.delete_service,
            permitted=permitted,
            filtered_external_ids=filtered_service_ids,
        )

    async def fetch_service(self, created_service: CreatedService) -> PMMService | None:
        """Fetch updated data for a specific service.

        Retrieve the latest information for the specified service from the PMM API.
        Returns None if the service is filtered out (e.g., has sep_sync: disabled).

        :param created_service: The service instance for which to fetch updated data.
        :return: The updated service data, or None if filtered out.
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
