"""Define base sync models for SEP."""

from pydantic import BaseModel
from pydantic import computed_field

from app.core.requests import RemoteAPI


class BaseSyncer(BaseModel):
    """Define a base class for syncers in the SEP app.

    This class serves as a blueprint for all syncer implementations within
    the SEP application. It provides the foundational structure, including required
    APIs and abstract methods that can be overridden by subclasses.

    Attributes
    ----------
    inventory_api : RemoteAPI
        The remote API interface for interacting with the inventory system.
    tasks_api : RemoteAPI
        The remote API interface for managing synchronization tasks.
    name

    """

    inventory_api: RemoteAPI
    tasks_api: RemoteAPI

    @computed_field
    @property
    def name(self) -> str:
        """Compute the fully qualified name of the synchronizer.

        Returns
        -------
        str
            The synchronizer's name in the format "module.ClassName".

        """
        return f"{self.__module__}.{self.__name__}"

    async def sync(self) -> None:
        """Perform a full synchronization process.

        Execute the complete synchronization workflow, handling all relevant
        data retrieval, processing, and storage operations.

        Raises
        ------
        NotImplementedError
            Indicates that the method must be overridden by a subclass.

        """
        raise NotImplementedError(".sync() must be overridden.")

    async def sync_node(self, node_id: int) -> None:
        """Synchronize data for a specific node.

        Retrieve and update information related to the node identified by `node_id`.

        Parameters
        ----------
        node_id : int
            The unique identifier of the node to synchronize.

        Raises
        ------
        NotImplementedError
            Indicates that the method must be overridden by a subclass.

        """
        raise NotImplementedError(".sync_node() must be overridden.")

    async def sync_service(self, service_id: int) -> None:
        """Synchronize data for a specific service.

        Retrieve and update information related to the service identified by
        `service_id`.

        Parameters
        ----------
        service_id : int
            The unique identifier of the service to synchronize.

        Raises
        ------
        NotImplementedError
            Indicates that the method must be overridden by a subclass.

        """
        raise NotImplementedError(".sync_service() must be overridden.")

    async def sync_schema(self, schema_id: int) -> None:
        """Synchronize data for a specific schema.

        Retrieve and update information related to the schema identified by `schema_id`.

        Parameters
        ----------
        schema_id : int
            The unique identifier of the schema to synchronize.

        Raises
        ------
        NotImplementedError
            Indicates that the method must be overridden by a subclass.

        """
        raise NotImplementedError(".sync_schema() must be overridden.")

    async def sync_table(self, table_id: int) -> None:
        """Synchronize data for a specific table.

        Retrieve and update information related to the table identified by `table_id`.

        Parameters
        ----------
        table_id : int
            The unique identifier of the table to synchronize.

        Raises
        ------
        NotImplementedError
            Indicates that the method must be overridden by a subclass.

        """
        raise NotImplementedError(".sync_table() must be overridden.")
