import logging
from typing import Any
from urllib.parse import urljoin

from aiohttp import ClientResponse
from aiohttp import ClientSession
from pydantic import BaseModel
from pydantic import computed_field
from pydantic import HttpUrl

logger = logging.getLogger(__name__)


class RemoteAPI(BaseModel):
    # TODO: fix case
    ENDPOINT: HttpUrl
    API_KEY: str
    VERIFY_SSL: bool = True

    @computed_field
    @property
    def BASE_PATH(self) -> str:
        return "/" + self.ENDPOINT.path.strip("/")

    @computed_field
    @property
    def BASE_URL(self) -> str:
        url = str(self.ENDPOINT)
        if self.BASE_PATH.strip("/"):
            url = url.replace(self.BASE_PATH, "")
        return url

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
        trailing_slash = path.endswith("/")
        path = path.strip("/")
        base_path = self.BASE_PATH + "/" if path else self.BASE_PATH
        path = urljoin(base_path, path)
        path = path + "/" if trailing_slash else path
        if not self.VERIFY_SSL:
            kwargs["ssl"] = False
        logger.debug(
            "Sending %s request to %s%s with kwargs %s",
            method,
            self.BASE_URL,
            path,
            kwargs,
        )
        async with ClientSession(
            base_url=self.BASE_URL,
            headers=self.headers,
        ) as session:
            return await session.request(method, path, **kwargs)

    async def request(
        self,
        method: str,
        path: str,
        **kwargs,
    ) -> Any:  # TODO: improve type hint
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
        Any
            The JSON response.

        """
        response = await self._request(method, path, **kwargs)
        return await response.json()

    async def get(self, path: str, **kwargs) -> Any:
        """Perform a GET request and return the JSON response.

        Parameters
        ----------
        path : str
            The API endpoint path to request.
        **kwargs : dict, optional
            Additional keyword arguments to pass to the request.

        Returns
        -------
        Any
            The JSON response as a dictionary.

        """
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs) -> Any:
        """Perform a POST request and return the JSON response.

        Parameters
        ----------
        path : str
            The API endpoint path to request.
        **kwargs : dict, optional
            Additional keyword arguments to pass to the request.

        Returns
        -------
        Any
            The JSON response as a dictionary.

        """
        return await self.request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs) -> Any:
        """Perform a PUT request and return the JSON response.

        Parameters
        ----------
        path : str
            The API endpoint path to request.
        **kwargs : dict, optional
            Additional keyword arguments to pass to the request.

        Returns
        -------
        Any
            The JSON response as a dictionary.

        """
        return await self.request("PUT", path, **kwargs)

    async def patch(self, path: str, **kwargs) -> Any:
        """Perform a PATCH request and return the JSON response.

        Parameters
        ----------
        path : str
            The API endpoint path to request.
        **kwargs : dict, optional
            Additional keyword arguments to pass to the request.

        Returns
        -------
        Any
            The JSON response as a dictionary.

        """
        return await self.request("PATCH", path, **kwargs)

    async def delete(self, path: str, **kwargs) -> Any:
        """Perform a DELETE request and return the JSON response.

        Parameters
        ----------
        path : str
            The API endpoint path to request.
        **kwargs : dict, optional
            Additional keyword arguments to pass to the request.

        Returns
        -------
        Any
            The JSON response as a dictionary.

        """
        return await self.request("DELETE", path, **kwargs)
