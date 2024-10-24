"""Manage remote API interactions."""

import logging
from functools import cached_property
from ssl import create_default_context, SSLContext
from typing import Any
from urllib.parse import urljoin

from aiohttp import ClientResponse, ClientSession
from pydantic import computed_field, HttpUrl

from app.core.config import BaseCaseInsensitiveModel
from app.core.fields import RelativeFilePath, RequiredStr

logger = logging.getLogger(__name__)


class RemoteAPI(BaseCaseInsensitiveModel):
    """Interact with external services via HTTP requests.

    The `RemoteAPI` class provides methods to perform HTTP requests to external
    APIs, handling authentication, SSL verification, and request formatting. It
    supports standard HTTP methods and manages session headers and SSL contexts
    based on configuration.

    :param endpoint: The base URL for the external API endpoint.
    :type endpoint: HttpUrl
    :param api_key: The API key for authentication. Defaults to None.
    :type api_key: str | None
    :param auth_scheme: The authentication scheme to use (e.g., "Bearer", "Basic").
        Defaults to "Bearer".
    :type auth_scheme: RequiredStr
    :param verify_ssl: Whether to verify SSL certificates. Defaults to True.
    :type verify_ssl: bool
    :param ssl_cafile: Path to the SSL certificate authority file. Defaults to None.
    :type ssl_cafile: RelativeFilePath | None
    :param ssl_keyfile: Path to the SSL key file. Defaults to None.
    :type ssl_keyfile: RelativeFilePath | None
    :param ssl_certfile: Path to the SSL certificate file. Defaults to None.
    :type ssl_certfile: RelativeFilePath | None
    """

    endpoint: HttpUrl
    api_key: str | None = None
    auth_scheme: RequiredStr = "Bearer"
    verify_ssl: bool = True
    ssl_cafile: RelativeFilePath | None = None
    ssl_keyfile: RelativeFilePath | None = (
        None  # TODO: make this single tuple like with nomad  # noqa: TD002, TD003
    )
    ssl_certfile: RelativeFilePath | None = None

    @cached_property
    def ssl_context(self) -> SSLContext:
        """Initialize and return the SSL context for secure connections.

        Configures the SSL context based on the provided SSL certificate files
        and verification settings.

        :return: The configured SSL context for HTTPS connections.
        :rtype: SSLContext
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

        :return: The base path of the API endpoint.
        :rtype: str
        """
        return "/" + self.endpoint.path.strip("/")

    @computed_field
    @property
    def base_url(self) -> str:
        """Compute and return the base URL without the base path.

        Removes the base path from the endpoint URL if present.

        :return: The base URL of the API endpoint.
        :rtype: str
        """
        url = str(self.endpoint)
        if self.base_path.strip("/"):
            url = url.replace(self.base_path, "")
        return url.rstrip("/")

    @property
    def headers(self) -> dict[str, str]:
        """Return the headers to be used in API requests.

        Includes content type, accept headers, and authorization with the API key.

        :return: A dictionary containing the headers for API requests.
        :rtype: dict[str, str]
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
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Perform an HTTP request and return the JSON response.

        :param method: The HTTP method to use for the request.
        :type method: str
        :param path: The API endpoint path to request.
        :type path: str
        :param kwargs: Additional keyword arguments to pass to the request.
        :type kwargs: Any
        :return: The JSON response as a Python object.
        :rtype: dict[str, Any] | list[dict[str, Any]]
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

    async def get(
        self, path: str, **kwargs: Any
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Perform a GET request and return the JSON response.

        :param path: The API endpoint path to request.
        :type path: str
        :param kwargs: Additional keyword arguments to pass to the request.
        :type kwargs: Any
        :return: The JSON response as a Python object.
        :rtype: dict[str, Any] | list[dict[str, Any]]
        """
        return await self.request("GET", path, **kwargs)

    async def post(
        self, path: str, **kwargs: Any
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Perform a POST request and return the JSON response.

        :param path: The API endpoint path to request.
        :type path: str
        :param kwargs: Additional keyword arguments to pass to the request.
        :type kwargs: Any
        :return: The JSON response as a Python object.
        :rtype: dict[str, Any] | list[dict[str, Any]]
        """
        return await self.request("POST", path, **kwargs)

    async def put(
        self, path: str, **kwargs: Any
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Perform a PUT request and return the JSON response.

        :param path: The API endpoint path to request.
        :type path: str
        :param kwargs: Additional keyword arguments to pass to the request.
        :type kwargs: Any
        :return: The JSON response as a Python object.
        :rtype: dict[str, Any] | list[dict[str, Any]]
        """
        return await self.request("PUT", path, **kwargs)

    async def patch(
        self, path: str, **kwargs: Any
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Perform a PATCH request and return the JSON response.

        :param path: The API endpoint path to request.
        :type path: str
        :param kwargs: Additional keyword arguments to pass to the request.
        :type kwargs: Any
        :return: The JSON response as a Python object.
        :rtype: dict[str, Any] | list[dict[str, Any]]
        """
        return await self.request("PATCH", path, **kwargs)

    async def delete(
        self, path: str, **kwargs: Any
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Perform a DELETE request and return the JSON response.

        :param path: The API endpoint path to request.
        :type path: str
        :param kwargs: Additional keyword arguments to pass to the request.
        :type kwargs: Any
        :return: The JSON response as a Python object.
        :rtype: dict[str, Any] | list[dict[str, Any]]
        """
        return await self.request("DELETE", path, **kwargs)
