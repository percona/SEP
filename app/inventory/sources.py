from collections import defaultdict
from typing import Any

from aiohttp import ClientResponse
from aiohttp import ClientSession
from pydantic import BaseModel

from app.core.fields import RequiredStr
from app.core.fields import StrHttpUrl
from app.inventory.models import InventoryItem
from app.inventory.models import Node
from app.inventory.models import Service


# TODO: Make base models abstract
class BaseSource(BaseModel):
    """Base class for inventory data sources.

    This class serves as a template for data sources that need to implement the
    `get_inventory` method to retrieve inventory items.
    """

    async def get_inventory(self) -> list[InventoryItem]:
        raise NotImplementedError(".get_inventory() must be overridden.")


# TODO: Select source in settings
class PMMSource(BaseSource):
    """PMM data source implementation.

    This class interacts with the PMM API to fetch nodes, services, and construct
    inventory items.

    Attributes
    ----------
    ENDPOINT : StrHttpUrl
        The base URL for the PMM API.
    API_KEY : str
        The API key for authenticating requests to the PMM API.
    VERIFY_SSL : bool, optional
        Whether to verify SSL certificates for requests. Defaults to `True`.

    """

    ENDPOINT: StrHttpUrl
    API_KEY: str
    VERIFY_SSL: bool = True

    @property
    def headers(self) -> dict[str, str]:
        """Return the headers to be used in API requests.

        Includes content type, accept headers, and authorization with the API key.

        Returns
        -------
        dict[str, str]
            A dictionary containing the headers for API requests.

        """
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.API_KEY}",
        }

    async def _request(self, method: str, path: str, **kwargs) -> ClientResponse:
        if not self.VERIFY_SSL:
            kwargs["ssl"] = False
        async with ClientSession(
            base_url=self.ENDPOINT,
            headers=self.headers,
        ) as session:
            return await session.request(method, path, **kwargs)

    async def request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        """Perform an HTTP request and return the JSON response.

        Parameters
        ----------
        method : str
            The HTTP method (e.g., "GET", "POST") to use for the request.
        path : str
            The API endpoint path to request.
        **kwargs : dict, optional
            Additional keyword arguments to pass to the request.

        Returns
        -------
        dict[str, Any]
            The JSON response as a dictionary.

        """
        response = await self._request(method, path, **kwargs)
        return await response.json()

    async def get(self, path: str, **kwargs) -> dict[str, Any]:
        """Perform a GET request and return the JSON response.

        Parameters
        ----------
        path : str
            The API endpoint path to request.
        **kwargs : dict, optional
            Additional keyword arguments to pass to the request.

        Returns
        -------
        dict[str, Any]
            The JSON response as a dictionary.

        """
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs) -> dict[str, Any]:
        """Perform a POST request and return the JSON response.

        Parameters
        ----------
        path : str
            The API endpoint path to request.
        **kwargs : dict, optional
            Additional keyword arguments to pass to the request.

        Returns
        -------
        dict[str, Any]
            The JSON response as a dictionary.

        """
        return await self.request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs) -> dict[str, Any]:
        """Perform a PUT request and return the JSON response.

        Parameters
        ----------
        path : str
            The API endpoint path to request.
        **kwargs : dict, optional
            Additional keyword arguments to pass to the request.

        Returns
        -------
        dict[str, Any]
            The JSON response as a dictionary.

        """
        return await self.request("PUT", path, **kwargs)

    async def get_nodes(self, node_type: str = "") -> dict[str, Any]:
        """Fetch and return a dictionary of nodes by type from the PMM API.

        Parameters
        ----------
        node_type : str, optional
            The type of nodes to filter by.
            Defaults to an empty string, meaning no filter.

        Returns
        -------
        dict[str, Any]
            A dictionary containing nodes grouped by type.

        """
        return await self.post(
            "/v1/inventory/Nodes/List",
            json={"node_type": node_type},
        )

    async def get_services(
        self,
        node_id: str = "",
        service_type: str = "",
        external_group: str = "",
    ) -> dict[str, Any]:
        """Fetch and return a dictionary of services from the PMM API.

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
        dict[str, Any]
            A dictionary containing services grouped by type.

        """
        data = {
            "node_id": node_id,
            "service_type": service_type,
            "external_group": external_group,
        }
        return await self.post("/v1/inventory/Services/List", json=data)

    async def get_services_by_node_id(self) -> defaultdict[RequiredStr, list[Service]]:
        """Fetch and group services by node ID from the PMM API.

        Returns
        -------
        defaultdict[RequiredStr, list[Service]]
            A defaultdict where the keys are node IDs and the values are lists of
            services.

        """
        services_by_node_id = defaultdict(list)
        services_data = await self.get_services()
        for service_type, services in services_data.items():
            for service_data in services:
                service = Service(type=service_type, **service_data)
                services_by_node_id[service.node_id].append(service)
        return services_by_node_id

    async def get_inventory(self) -> list[InventoryItem]:
        """Fetch and construct a list of InventoryItem objects from the PMM API.

        Returns
        -------
        list[InventoryItem]
            A list of `InventoryItem` objects representing the nodes and their
            associated services.

        """
        # TODO: Implement caching
        services_by_node_id = await self.get_services_by_node_id()
        inventory = []
        nodes_data = await self.get_nodes()
        for node_type, nodes in nodes_data.items():
            for node_data in nodes:
                node = Node(type=node_type, **node_data)
                inventory.append(
                    InventoryItem(
                        **node.model_dump(),
                        services=services_by_node_id[node.node_id],
                    ),
                )
        return inventory
