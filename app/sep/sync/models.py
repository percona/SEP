"""Define base sync models for SEP."""

import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from functools import cached_property
from types import TracebackType
from typing import ClassVar
from typing import Self
from uuid import uuid4

from async_lru import _LRUCacheWrapper
from async_lru import alru_cache
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator
from pydantic import UUID4
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import BaseCaseInsensitiveModel
from app.core.requests import RemoteAPI
from app.sep.crud import SyncInstanceManager
from app.sep.crud import SyncItemManager
from app.sep.db import get_async_session_maker
from app.sep.inventory import CreatedEntity
from app.sep.inventory import CreatedNode
from app.sep.inventory import CreatedSchema
from app.sep.inventory import CreatedService
from app.sep.inventory import CreatedTable
from app.sep.inventory import Node
from app.sep.inventory import Schema
from app.sep.inventory import Service
from app.sep.inventory import SourceEnum
from app.sep.inventory import Table
from app.sep.models import SyncInstance
from app.sep.models import SyncInstanceWrite
from app.sep.models import SyncInventoryEntityTypeEnum
from app.sep.models import SyncItem
from app.sep.models import SyncItemWrite
from app.sep.sync.exceptions import SyncFailError
from app.sep.sync.exceptions import SyncItemAlreadyInProgressError

logger = logging.getLogger(__name__)


class BaseSyncer(BaseCaseInsensitiveModel):
    """Define a base class for syncers in the SEP app.

    This class serves as a blueprint for all syncer implementations within
    the SEP application. It provides the foundational structure, including required
    APIs and abstract methods that can be overridden by subclasses.

    Attributes
    ----------
    SYNC_TO_LIMIT : ClassVar[SyncInventoryEntityTypeEnum]
        The upper limit for entity types that can be synchronized.
    inventory_api : RemoteAPI
        The remote API interface for interacting with the inventory system.
    tasks_api : RemoteAPI
        The remote API interface for managing synchronization tasks.
    sync_instance : SyncInstance, optional
        The synchronization instance used to track sync processes.
    sync_items : dict
        A dictionary mapping tuples of entity type and ID to SyncItem objects.
    sync_id : UUID4
        The unique identifier for this synchronization.
    can_sync_mapping

    Notes
    -----
    The `SYNC_TO_LIMIT` class attribute defines the maximum entity type that can be
    synchronized by an instance of this class. This is used by the
    `.can_sync_entity_type()` method to determine which entities can be synced.

    """

    model_config = ConfigDict(ignored_types=(_LRUCacheWrapper,))
    SYNC_TO_LIMIT: ClassVar[SyncInventoryEntityTypeEnum]
    inventory_api: RemoteAPI
    tasks_api: RemoteAPI
    sync_instance: SyncInstance | None = None
    sync_items: dict[tuple[SyncInventoryEntityTypeEnum, int | None], SyncItem] = {}
    sync_id: UUID4 = Field(default_factory=uuid4)
    _session: AsyncSession

    def __hash__(self) -> int:
        """Compute the hash based on the synchronization ID.

        Returns
        -------
        int
            The hash value of the syncer instance.

        """
        return hash(self.sync_id)

    async def __aenter__(self) -> Self:
        """Enter the asynchronous context manager.

        Initializes the database session and creates a new SyncInstance if one does not
        exist.

        Returns
        -------
        Self
            The syncer instance with an active session and SyncInstance.

        """
        session_maker = get_async_session_maker()
        self._session = session_maker()
        self._session = await self._session.__aenter__()
        if self.sync_instance is None:
            self.sync_instance = await SyncInstanceManager.create(
                self._session,
                SyncInstanceWrite(syncer=self.get_name()),
                id=self.sync_id,
            )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException],
        exc_val: BaseException,
        exc_tb: TracebackType,
    ) -> None:
        """Exit the asynchronous context manager.

        Marks any hanging SyncItems as failed and closes the database session.

        Parameters
        ----------
        exc_type : type[BaseException]
            The exception type, if any.
        exc_val : BaseException
            The exception value, if any.
        exc_tb : TracebackType
            The traceback, if any.

        """
        await SyncInstanceManager.finish_hanging_items(
            self._session,
            self.sync_instance.id,
        )
        await self._session.__aexit__(exc_type, exc_val, exc_tb)

    @model_validator(mode="after")
    def set_sync_id_from_sync_instance(self) -> Self:
        """Assign the synchronization ID from the SyncInstance.

        If a SyncInstance exists, its ID is assigned to the sync_id attribute.

        Returns
        -------
        Self
            The syncer instance with the updated sync_id.

        """
        if self.sync_instance is not None:
            self.sync_id = self.sync_instance.id
        return self

    @cached_property
    def can_sync_mapping(
        self,
    ) -> dict[SyncInventoryEntityTypeEnum, Callable[[CreatedEntity], bool]]:
        """Map entity types to their corresponding sync permission check methods.

        Returns
        -------
        dict[SyncInventoryEntityTypeEnum, Callable[[CreatedEntity], bool]]
            A dictionary mapping each SyncInventoryEntityTypeEnum to a method that
            determines if that entity can be synchronized.

        """
        return {
            SyncInventoryEntityTypeEnum.NODE: self.can_sync_node,
            SyncInventoryEntityTypeEnum.SERVICE: self.can_sync_service,
            SyncInventoryEntityTypeEnum.SCHEMA: self.can_sync_schema,
            SyncInventoryEntityTypeEnum.TABLE: self.can_sync_table,
        }

    async def prepare_sync(
        self,
        entity_type: SyncInventoryEntityTypeEnum,
        created_entity: CreatedEntity | None,
    ) -> None:
        """Prepare synchronization for a given entity and its children.

        This method sets up SyncItems for the specified entity and recursively prepares
        synchronization for any child entities if applicable.

        Parameters
        ----------
        entity_type : SyncInventoryEntityTypeEnum
            The type of the entity to synchronize.
        created_entity : CreatedEntity or None
            The entity instance to synchronize, or None for top-level (inventory)
            synchronization.

        """
        entity_id = None if created_entity is None else created_entity.id
        logger.debug("Preparing sync for %s with ID %s", entity_type.name, entity_id)
        self.sync_items[(entity_type, entity_id)] = await self.get_sync_item(
            entity_type,
            entity_id,
        )
        next_entity_type = entity_type + 1
        if self.can_sync_entity_type(next_entity_type):
            for child in await self.get_children_entities(entity_type, created_entity):
                can_sync = self.can_sync_mapping.get(next_entity_type)
                if can_sync is not None and can_sync(child):
                    await self.prepare_sync(next_entity_type, child)
        logger.debug(
            "Finished preparing sync for %s with ID %s",
            entity_type.name,
            entity_id,
        )

    async def get_children_entities(
        self,
        entity_type: SyncInventoryEntityTypeEnum,
        created_entity: CreatedEntity | None,
    ) -> list[CreatedEntity]:
        """Retrieve child entities for a given entity type and entity.

        Depending on the entity type, this method fetches related child entities that
        need to be synchronized.

        Parameters
        ----------
        entity_type : SyncInventoryEntityTypeEnum
            The type of the current entity.
        created_entity : CreatedEntity or None
            The current entity instance, or None for top-level synchronization.

        Returns
        -------
        list of CreatedEntity
            A list of child entities to be synchronized.

        Notes
        -----
        - If the entity type does not have associated child entities or the
        `created_entity` is None, an empty list is returned.

        """
        if entity_type == SyncInventoryEntityTypeEnum.INVENTORY:
            return await self.get_inventory_nodes()
        if entity_type == SyncInventoryEntityTypeEnum.SERVICE:
            return await self.get_inventory_service_schemas(created_entity.id)
        if created_entity is not None:
            return created_entity.children
        logger.warning(
            "Unknown entity type %s or missing created_entity: %s",
            entity_type,
            created_entity,
        )
        return []

    async def get_sync_item(
        self,
        entity_type: SyncInventoryEntityTypeEnum,
        entity_id: int | None,
    ) -> SyncItem:
        """Retrieve or create a SyncItem for a given entity.

        This method attempts to retrieve an existing SyncItem for the specified entity.
        If none exists, it creates a new SyncItem.

        Parameters
        ----------
        entity_type : SyncInventoryEntityTypeEnum
            The type of the entity.
        entity_id : int or None
            The unique identifier of the entity, or None for top-level (inventory)
            synchronization.

        Returns
        -------
        SyncItem
            The existing or newly created SyncItem.

        """
        sync_item, created = await SyncItemManager.get_or_create(
            self._session,
            SyncItemWrite(
                entity_type=entity_type,
                entity_id=entity_id,
                sync_instance_id=self.sync_instance.id,
            ),
        )
        verb = "Created" if created else "Retrieved"
        logger.debug("%s SyncItem: %s", verb, sync_item)
        return sync_item

    async def get_sync_items(
        self,
        entity_type: SyncInventoryEntityTypeEnum,
        *entity_ids: int | None,
    ) -> list[SyncItem]:
        """Retrieve multiple SyncItems for specified entities.

        This method attempts to retrieve or create SyncItems for each provided entity
        ID. If a SyncItem is already in progress for an entity, it logs the exception.

        Parameters
        ----------
        entity_type : SyncInventoryEntityTypeEnum
            The type of the entities.
        *entity_ids : int or None
            The unique identifiers of the entities, or None for top-level (inventory)
            synchronization.

        Returns
        -------
        list of SyncItem
            A list of SyncItems corresponding to the provided entity IDs.

        """
        sync_items = []
        for entity_id in entity_ids:
            try:
                sync_items.append(await self.get_sync_item(entity_type, entity_id))
            except SyncItemAlreadyInProgressError:
                logger.exception(
                    "Failed to create SyncItem (entity_id: %s, entity_type: %s): "
                    "already in progress",
                    entity_id,
                    entity_type,
                )
        return sync_items

    @asynccontextmanager
    async def manage_sync_item(
        self,
        entity_type: SyncInventoryEntityTypeEnum,
        created_entity: CreatedEntity | None,
    ) -> SyncItem:
        """Manage the synchronization lifecycle of a SyncItem.

        This asynchronous context manager handles the synchronization lifecycle of a
        `SyncItem`, including initiating the synchronization process, handling
        exceptions by marking the `SyncItem` as failed, and finalizing the
        synchronization status upon successful completion.

        Parameters
        ----------
        entity_type : SyncInventoryEntityTypeEnum
            The type of the entity to synchronize.
        created_entity : CreatedEntity or None
            The entity instance to synchronize, or `None` for top-level synchronization.

        Yields
        ------
        SyncItem
            The `SyncItem` instance being managed during the synchronization process.

        Raises
        ------
        SyncFailError
            If an exception occurs during synchronization, indicating that the
            `SyncItem` has failed.

        """
        entity_id = None if created_entity is None else created_entity.id
        sync_item_entity = (entity_type, entity_id)
        if sync_item_entity not in self.sync_items:
            await self.prepare_sync(entity_type, created_entity)
        sync_item = self.sync_items[sync_item_entity]
        sync_item = await SyncItemManager.start_sync(self._session, sync_item)
        try:
            yield sync_item
        except Exception as exc:
            logger.exception(
                "Failed to sync %s (%s)",
                entity_type,
                sync_item,
            )
            self.sync_items[sync_item_entity] = await SyncItemManager.fail_sync(
                self._session,
                sync_item,
            )
            raise SyncFailError from exc
        else:
            await self.finish_sync(entity_type, created_entity)

    async def finish_sync(
        self,
        entity_type: SyncInventoryEntityTypeEnum,
        created_entity: CreatedEntity | None,
    ) -> None:
        """Finalize synchronization for a given entity and its children.

        This method marks the SyncItem as finished and recursively finalizes
        synchronization for any child entities.

        Parameters
        ----------
        entity_type : SyncInventoryEntityTypeEnum
            The type of the entity that was synchronized.
        created_entity : CreatedEntity or None
            The entity instance that was synchronized, or None for top-level (inventory)
            synchronization.

        """
        entity_id = None
        if created_entity is not None:
            entity_id = created_entity.id
            for child in created_entity.children:
                await self.finish_sync(entity_type + 1, child)
        if sync_item := self.sync_items.get((entity_type, entity_id)):
            self.sync_items[
                (entity_type, entity_id)
            ] = await SyncItemManager.finish_sync(
                self._session,
                sync_item,
            )

    @alru_cache
    async def get_inventory_nodes(
        self,
        external_id: str | None = None,
        source: SourceEnum | None = None,
        node_type: str | None = None,
    ) -> list[CreatedNode]:
        """Retrieve inventory nodes from the remote API.

        This method fetches nodes from the inventory API based on the provided
        filters. Results are cached to optimize performance.

        Parameters
        ----------
        external_id : str or None, optional
            The external identifier of the node. Defaults to None, meaning it won't be
            used as a filter.
        source : SourceEnum or None, optional
            The source of the node information. Defaults to None, meaning it won't be
            used as a filter.
        node_type : str or None, optional
            The type of the node (e.g., "generic"). Defaults to None, meaning it won't
            be used as a filter.

        Returns
        -------
        list of CreatedNode
            A list of retrieved CreatedNode instances.

        """
        params = {
            "external_id": external_id,
            "source": source,
            "node_type": node_type,
        }
        params = {key: value for key, value in params.items() if value is not None}
        # TODO(yan): Results will be paginated
        # SEP-134
        return [
            CreatedNode.model_validate(node_data)
            for node_data in await self.inventory_api.get("/", params=params)
        ]

    @alru_cache
    async def get_inventory_node(self, node_id: int) -> CreatedNode:
        """Retrieve a specific inventory node by its ID.

        This method fetches a single node from the inventory system using its unique ID.
        The result is cached to optimize performance.

        Parameters
        ----------
        node_id : int
            The unique identifier of the node to retrieve.

        Returns
        -------
        CreatedNode
            The retrieved CreatedNode instance.

        """
        return CreatedNode.model_validate(await self.inventory_api.get(f"/{node_id}"))

    @alru_cache
    async def get_inventory_service(self, service_id: int) -> CreatedService:
        """Retrieve a specific inventory service by its ID.

        This method fetches a single service from the inventory system using its unique
        ID. The result is cached to optimize performance.

        Parameters
        ----------
        service_id : int
            The unique identifier of the service to retrieve.

        Returns
        -------
        CreatedService
            The retrieved CreatedService instance.

        """
        return CreatedService.model_validate(
            await self.services_api.get(f"/services/{service_id}"),
        )

    @alru_cache
    async def get_inventory_service_schemas(
        self,
        service_id: int,
    ) -> list[CreatedSchema]:
        """Retrieve schemas associated with a specific inventory service.

        This method fetches all schemas related to a given service from the inventory
        system. The results are cached to optimize performance.

        Parameters
        ----------
        service_id : int
            The unique identifier of the service whose schemas are to be retrieved.

        Returns
        -------
        list of CreatedSchema
            A list of retrieved CreatedSchema instances.

        """
        return [
            CreatedSchema.model_validate(schema_data)
            for schema_data in await self.services_api.get(
                f"/services/{service_id}/schemas/",
            )
        ]

    async def delete_node(self, created_node: CreatedNode) -> None:
        """Delete a node from the inventory system.

        This method synchronizes the deletion of a node by marking the corresponding
        SyncItem and performing the deletion via the inventory API.

        Parameters
        ----------
        created_node : CreatedNode
            The node instance to be deleted.

        """
        logger.debug("Deleting node %s from inventory", created_node.id)
        async with self.manage_sync_item(
            SyncInventoryEntityTypeEnum.NODE,
            created_node,
        ):
            CreatedNode.model_validate(
                await self.inventory_api.delete(f"/{created_node.id}"),
            )

    async def delete_service(self, created_service: CreatedService) -> None:
        """Delete a service from the inventory system.

        This method synchronizes the deletion of a service by marking the corresponding
        SyncItem and performing the deletion via the inventory API.

        Parameters
        ----------
        created_service : CreatedService
            The service instance to be deleted.

        """
        logger.debug("Deleting service %s from inventory", created_service.id)
        async with self.manage_sync_item(
            SyncInventoryEntityTypeEnum.SERVICE,
            created_service,
        ):
            CreatedService.model_validate(
                await self.inventory_api.delete(f"/services/{created_service.id}"),
            )

    async def sync_inventory(self) -> None:
        """Synchronize the entire inventory.

        This method initiates the synchronization process for the entire inventory if
        permitted by the synchronization rules. It manages the SyncItem lifecycle and
        delegates the actual synchronization logic to the `perform_inventory_sync`
        method.

        """
        if self.can_sync_inventory():
            logger.info("Starting inventory synchronization (%s)", self.get_name())
            async with self.manage_sync_item(
                SyncInventoryEntityTypeEnum.INVENTORY,
                None,
            ):
                await self.perform_inventory_sync()
            logger.info("Finished inventory synchronization (%s)", self.get_name())

    async def perform_inventory_sync(self) -> None:
        """Perform a full synchronization process.

        Execute the complete synchronization workflow, handling all relevant
        data retrieval, processing, and storage operations. It should be overridden by
        subclasses to implement specific synchronization behavior.

        Raises
        ------
        NotImplementedError
            Indicates that the method must be overridden by a subclass.

        Notes
        -----
        This method is expected to be overriden by a subclass.

        """
        raise NotImplementedError(".perform_inventory_sync() must be overridden.")

    async def fetch_node(self, created_node: CreatedNode) -> Node:
        """Fetch updated data for a specific node.

        Retrieve the latest information for the specified node from the remote inventory
        API.

        Parameters
        ----------
        created_node : CreatedNode
            The node instance for which to fetch updated data.

        Returns
        -------
        Node
            The updated node data.

        Raises
        ------
        NotImplementedError
            Indicates that the method must be overridden by a subclass.

        Notes
        -----
        This method is expected to be overriden by a subclass.

        """
        raise NotImplementedError(".fetch_node() must be overridden.")

    async def sync_node(
        self,
        created_node: CreatedNode,
        updated_node: Node | None = None,
    ) -> None:
        """Synchronize data for a specific node.

        Retrieve and update information related to the node identified by
        `created_node`.

        Parameters
        ----------
        created_node : CreatedNode
            The node instance to synchronize.
        updated_node : Node or None, optional
            The updated node data. If None, it will be fetched using `.fetch_node()`.
            Defaults to None.

        """
        if self.can_sync_node(created_node):
            logger.info(
                "Starting node synchronization (%s) for node %s",
                self.get_name(),
                created_node.id,
            )
            async with self.manage_sync_item(
                SyncInventoryEntityTypeEnum.NODE,
                created_node,
            ):
                updated_node = (
                    self.fetch_node(created_node)
                    if updated_node is None
                    else updated_node
                )
                await self.perform_node_sync(created_node, updated_node)
            logger.info(
                "Finished node synchronization (%s) for node %s",
                self.get_name(),
                created_node.id,
            )

    async def perform_node_sync(
        self,
        created_node: CreatedNode,
        updated_node: Node,
    ) -> None:
        """Perform synchronization for a specific node.

        This method contains the logic to synchronize data for the specified node. It
        should be overridden by subclasses to implement specific synchronization
        behavior.

        Parameters
        ----------
        created_node : CreatedNode
            The node instance to synchronize.
        updated_node : Node
            The updated node data.

        Raises
        ------
        NotImplementedError
            Indicates that the method must be overridden by a subclass.

        Notes
        -----
        This method is expected to be overriden by a subclass.

        """
        raise NotImplementedError(".perform_node_sync() must be overridden.")

    async def fetch_service(self, created_service: CreatedService) -> Service:
        """Fetch updated data for a specific service.

        Retrieve the latest information for the specified service from the remote
        inventory API.

        Parameters
        ----------
        created_service : CreatedService
            The service instance for which to fetch updated data.

        Returns
        -------
        Service
            The updated service data.

        Raises
        ------
        NotImplementedError
            Indicates that the method must be overridden by a subclass.

        Notes
        -----
        This method is expected to be overriden by a subclass.

        """
        raise NotImplementedError(".fetch_service() must be overridden.")

    async def sync_service(
        self,
        created_service: CreatedService,
        updated_service: Service | None = None,
    ) -> None:
        """Synchronize data for a specific service.

        Retrieve and update information related to the service identified by
        `created_service`.

        Parameters
        ----------
        created_service : CreatedService
            The service instance to synchronize.
        updated_service : Service or None, optional
            The updated service data. If None, it will be fetched using
            `.fetch_service()`. Defaults to None.

        """
        if self.can_sync_service(created_service):
            logger.info(
                "Starting service synchronization (%s) for service %s",
                self.get_name(),
                created_service.id,
            )
            async with self.manage_sync_item(
                SyncInventoryEntityTypeEnum.SERVICE,
                created_service,
            ):
                updated_service = (
                    self.fetch_service(created_service)
                    if updated_service is None
                    else updated_service
                )
                await self.perform_service_sync(created_service, updated_service)
            logger.info(
                "Finished service synchronization (%s) for service %s",
                self.get_name(),
                created_service.id,
            )

    async def perform_service_sync(
        self,
        created_service: CreatedService,
        updated_service: Service,
    ) -> None:
        """Perform synchronization for a specific service.

        This method contains the logic to synchronize data for the specified service.
        It should be overridden by subclasses to implement specific synchronization
        behavior.

        Parameters
        ----------
        created_service : CreatedService
            The service instance to synchronize.
        updated_service : Service
            The updated service data.

        Raises
        ------
        NotImplementedError
            Indicates that the method must be overridden by a subclass.

        Notes
        -----
        This method is expected to be overriden by a subclass.

        """
        raise NotImplementedError(".perform_service_sync() must be overridden.")

    async def fetch_schema(self, created_schema: CreatedSchema) -> Schema:
        """Fetch updated data for a specific schema.

        Retrieve the latest information for the specified schema from the remote
        inventory API.

        Parameters
        ----------
        created_schema : CreatedSchema
            The schema instance for which to fetch updated data.

        Returns
        -------
        Schema
            The updated schema data.

        Raises
        ------
        NotImplementedError
            Indicates that the method must be overridden by a subclass.

        Notes
        -----
        This method is expected to be overriden by a subclass.

        """
        raise NotImplementedError(".fetch_schema() must be overridden.")

    async def sync_schema(
        self,
        created_schema: CreatedSchema,
        updated_schema: Schema,
    ) -> None:
        """Synchronize data for a specific schema.

        Retrieve and update information related to the schema identified by
        `created_schema`.

        Parameters
        ----------
        created_schema : CreatedSchema
            The schema instance to synchronize.
        updated_schema : Schema or None, optional
            The updated schema data. If None, it will be fetched using
            `.fetch_schema()`. Defaults to None.


        """
        if self.can_sync_schema(created_schema):
            logger.info(
                "Starting schema synchronization (%s) for schema %s",
                self.get_name(),
                created_schema.id,
            )
            async with self.manage_sync_item(
                SyncInventoryEntityTypeEnum.SCHEMA,
                created_schema,
            ):
                updated_schema = (
                    self.fetch_schema(created_schema)
                    if updated_schema is None
                    else updated_schema
                )
                await self.perform_schema_sync(created_schema, updated_schema)
            logger.info(
                "Finished schema synchronization (%s) for schema %s",
                self.get_name(),
                created_schema.id,
            )

    async def perform_schema_sync(
        self,
        created_schema: CreatedSchema,
        updated_schema: Schema,
    ) -> None:
        """Perform synchronization for a specific schema.

        This method contains the logic to synchronize data for the specified schema.
        It should be overridden by subclasses to implement specific synchronization
        behavior.

        Parameters
        ----------
        created_schema : CreatedSchema
            The schema instance to synchronize.
        updated_schema : Schema
            The updated schema data.

        Raises
        ------
        NotImplementedError
            Indicates that the method must be overridden by a subclass.

        Notes
        -----
        This method is expected to be overriden by a subclass.

        """
        raise NotImplementedError(".perform_schema_sync() must be overridden.")

    async def fetch_table(self, created_table: CreatedTable) -> Table:
        """Fetch updated data for a specific table.

        Retrieve the latest information for the specified table from the remote
        inventory API.

        Parameters
        ----------
        created_table : CreatedTable
            The table instance for which to fetch updated data.

        Returns
        -------
        Table
            The updated table data.

        Raises
        ------
        NotImplementedError
            Indicates that the method must be overridden by a subclass.

        Notes
        -----
        This method is expected to be overriden by a subclass.

        """
        raise NotImplementedError(".fetch_table() must be overridden.")

    async def sync_table(
        self,
        created_table: CreatedTable,
        updated_table: Table,
    ) -> None:
        """Synchronize data for a specific table.

        Retrieve and update information related to the table identified by
        `created_table`.

        Parameters
        ----------
        created_table : CreatedTable
            The table instance to synchronize.
        updated_table : Table or None, optional
            The updated table data. If None, it will be fetched using `.fetch_table()`.
            Defaults to None.

        """
        if self.can_sync_table(created_table):
            logger.info(
                "Starting table synchronization (%s) for table %s",
                self.get_name(),
                created_table.id,
            )
            async with self.manage_sync_item(
                SyncInventoryEntityTypeEnum.TABLE,
                created_table,
            ):
                updated_table = (
                    self.fetch_table(created_table)
                    if updated_table is None
                    else updated_table
                )
                await self.perform_table_sync(created_table, updated_table)
            logger.info(
                "Finished table synchronization (%s) for table %s",
                self.get_name(),
                created_table.id,
            )

    async def perform_table_sync(
        self,
        created_table: CreatedTable,
        updated_table: Table,
    ) -> None:
        """Perform synchronization for a specific table.

        This method contains the logic to synchronize data for the specified table.
        It should be overridden by subclasses to implement specific synchronization
        behavior.

        Parameters
        ----------
        created_table : CreatedTable
            The table instance to synchronize.
        updated_table : Table
            The updated table data.

        Raises
        ------
        NotImplementedError
            Indicates that the method must be overridden by a subclass.

        Notes
        -----
        This method is expected to be overriden by a subclass.

        """
        raise NotImplementedError(".perform_table_sync() must be overridden.")

    @classmethod
    def get_name(cls) -> str:
        """Compute the fully qualified name of the synchronizer.

        Returns
        -------
        str
            The synchronizer's name in the format "module.ClassName".

        """
        return f"{cls.__module__}.{cls.__name__}"

    @classmethod
    def can_sync_entity_type(cls, entity_type: SyncInventoryEntityTypeEnum) -> bool:
        """Determine if a given entity type can be synchronized.

        Checks if the provided entity type is within the permissible synchronization
        limit.

        Parameters
        ----------
        entity_type : SyncInventoryEntityTypeEnum
            The type of the entity to check.

        Returns
        -------
        bool
            `True` if the entity type can be synchronized, `False` otherwise.

        """
        return entity_type <= cls.SYNC_TO_LIMIT

    @classmethod
    def can_sync_inventory(cls, *check_nodes: CreatedNode) -> bool:
        """Determine if the inventory can be synchronized.

        Checks if inventory synchronization is permitted based on the synchronization
        rules and the provided nodes.

        Parameters
        ----------
        *check_nodes : CreatedNode, optional
            Nodes to check if synchronization is permissible. Defaults to an empty
            tuple.

        Returns
        -------
        bool
            `True` if inventory synchronization is allowed, `False` otherwise.

        """
        if cls.can_sync_entity_type(SyncInventoryEntityTypeEnum.INVENTORY):
            if not check_nodes:
                return True
            for node in check_nodes:
                if cls.can_sync_node(node):
                    return True
        return False

    @classmethod
    def can_sync_node(cls, node: CreatedNode) -> bool:  # noqa: ARG003
        """Determine if a specific node can be synchronized.

        Parameters
        ----------
        node : CreatedNode
            The node instance to check.

        Returns
        -------
        bool
            `True` if the node can be synchronized, `False` otherwise.


        """
        return cls.can_sync_entity_type(SyncInventoryEntityTypeEnum.NODE)

    @classmethod
    def can_sync_service(cls, service: CreatedService) -> bool:  # noqa: ARG003
        """Determine if a specific service can be synchronized.

        Parameters
        ----------
        service : CreatedService
            The service instance to check.

        Returns
        -------
        bool
            `True` if the service can be synchronized, `False` otherwise.


        """
        return cls.can_sync_entity_type(SyncInventoryEntityTypeEnum.SERVICE)

    @classmethod
    def can_sync_schema(cls, schema: CreatedSchema) -> bool:  # noqa: ARG003
        """Determine if a specific schema can be synchronized.

        Parameters
        ----------
        schema : CreatedSchema
            The schema instance to check.

        Returns
        -------
        bool
            `True` if the schema can be synchronized, `False` otherwise.


        """
        return cls.can_sync_entity_type(SyncInventoryEntityTypeEnum.SCHEMA)

    @classmethod
    def can_sync_table(cls, table: CreatedTable) -> bool:  # noqa: ARG003
        """Determine if a specific table can be synchronized.

        Parameters
        ----------
        table : CreatedTable
            The table instance to check.

        Returns
        -------
        bool
            `True` if the table can be synchronized, `False` otherwise.


        """
        return cls.can_sync_entity_type(SyncInventoryEntityTypeEnum.TABLE)
