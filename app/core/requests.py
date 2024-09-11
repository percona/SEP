import logging
from functools import cached_property
from ssl import create_default_context
from ssl import SSLContext
from typing import Any
from urllib.parse import urljoin

from aiohttp import ClientResponse
from aiohttp import ClientSession
from pydantic import computed_field
from pydantic import HttpUrl

from app.core.config import BaseCaseInsensitiveModel
from app.core.fields import RelativeFilePath

logger = logging.getLogger(__name__)


class RemoteAPI(BaseCaseInsensitiveModel):
    endpoint: HttpUrl
    api_key: str
    verify_ssl: bool = True
    ssl_cafile: RelativeFilePath | None = None
    ssl_keyfile: RelativeFilePath | None = (
        None  # TODO: make this single tuple like with nomad
    )
    ssl_certfile: RelativeFilePath | None = None

    @cached_property
    def ssl_context(self) -> SSLContext:
        context = create_default_context(cafile=self.ssl_cafile)
        if self.ssl_certfile:
            context.load_cert_chain(
                certfile=self.ssl_certfile,
                keyfile=self.ssl_keyfile,
            )
        return context

    @computed_field
    @property
    def base_path(self) -> str:
        return "/" + self.endpoint.path.strip("/")

    @computed_field
    @property
    def base_url(self) -> str:
        url = str(self.endpoint)
        if self.base_path.strip("/"):
            url = url.replace(self.base_path, "")
        return url.rstrip("/")

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
            "Authorization": f"Bearer {self.api_key}",
        }

    async def _request(self, method: str, path: str, **kwargs) -> ClientResponse:
        if self.base_path == "/":
            path = urljoin(self.base_path, path)
        else:
            trailing_slash = path.endswith("/")
            path = path.strip("/")
            base_path = (
                self.base_path + "/" if path and self.base_path else self.base_path
            )
            path = urljoin(base_path, path)
            path = path + "/" if trailing_slash else path
        if self.verify_ssl:
            kwargs["ssl"] = self.ssl_context
        else:
            kwargs["ssl"] = False
        logger.debug(
            "Sending %s request to %s%s with kwargs %s and headers %s",
            method,
            self.base_url,
            path,
            kwargs,
            self.headers,
        )
        async with ClientSession(
            base_url=self.base_url,
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
