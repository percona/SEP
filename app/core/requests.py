"""Manage remote API interactions."""

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
from app.core.fields import RequiredStr

logger = logging.getLogger(__name__)


class RemoteAPI(BaseCaseInsensitiveModel):
    """Interact with external services via HTTP requests.

    The `RemoteAPI` class provides methods to perform HTTP requests to external APIs,
    handling authentication, SSL verification, and request formatting. It supports
    standard HTTP methods and manages session headers and SSL contexts based on
    configuration.

    Attributes
    ----------
    endpoint : HttpUrl
        The base URL for the external API endpoint.
    api_key : str or None, optional
        The API key for authentication. Defaults to `None`.
    auth_scheme : RequiredStr, optional
        The authentication scheme to use (e.g., "Bearer"). Defaults to `"Bearer"`.
    verify_ssl : bool, optional
        Whether to verify SSL certificates. Defaults to `True`.
    ssl_cafile : RelativeFilePath or None, optional
        Path to the SSL certificate authority file. Defaults to `None`.
    ssl_keyfile : RelativeFilePath or None, optional
        Path to the SSL key file. Defaults to `None`.
    ssl_certfile : RelativeFilePath or None, optional
        Path to the SSL certificate file. Defaults to `None`.
    ssl_context

    """

    endpoint: HttpUrl
    api_key: str | None = None
    auth_scheme: RequiredStr = "Bearer"
    verify_ssl: bool = True
    ssl_cafile: RelativeFilePath | None = None
    ssl_keyfile: RelativeFilePath | None = (
        None  # TODO: make this single tuple like with nomad
    )
    ssl_certfile: RelativeFilePath | None = None

    @cached_property
    def ssl_context(self) -> SSLContext:
        """Initialize and return the SSL context for secure connections.

        Configures the SSL context based on the provided SSL certificate files and
        verification settings.

        Returns
        -------
        SSLContext
            The configured SSL context for HTTPS connections.

        """
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
        """Compute and return the base path of the API endpoint.

        Strips leading and trailing slashes from the endpoint path.

        Returns
        -------
        str
            The base path of the API endpoint.

        """
        return "/" + self.endpoint.path.strip("/")

    @computed_field
    @property
    def base_url(self) -> str:
        """Compute and return the base URL without the base path.

        Removes the base path from the endpoint URL if present.

        Returns
        -------
        str
            The base URL of the API endpoint.

        """
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
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"{self.auth_scheme} {self.api_key}",
        }
        if self.api_key:
            headers["Authorization"] = f"{self.auth_scheme} {self.api_key}"
        return headers

    async def _request(self, method: str, path: str, **kwargs: Any) -> ClientResponse:
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
        headers = self.headers | kwargs.pop("headers", {})
        logger.debug(
            "Sending %s request to %s%s with kwargs %s and headers %s",
            method,
            self.base_url,
            path,
            kwargs,
            headers,
        )
        async with ClientSession(
            base_url=self.base_url,
            headers=headers,
        ) as session:
            return await session.request(method, path, **kwargs)

    async def request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
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
            The JSON response.

        """
        response = await self._request(method, path, **kwargs)
        response_data = await response.json()
        logger.debug(
            "%s request to %s%s response: %s",
            method,
            self.base_url,
            path,
            response_data,
        )
        return response_data

    async def get(self, path: str, **kwargs: Any) -> dict[str, Any]:
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

    async def post(self, path: str, **kwargs: Any) -> dict[str, Any]:
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

    async def put(self, path: str, **kwargs: Any) -> dict[str, Any]:
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

    async def patch(self, path: str, **kwargs: Any) -> dict[str, Any]:
        """Perform a PATCH request and return the JSON response.

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
        return await self.request("PATCH", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> dict[str, Any]:
        """Perform a DELETE request and return the JSON response.

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
        return await self.request("DELETE", path, **kwargs)
