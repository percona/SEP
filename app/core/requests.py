"""Manage remote API interactions."""

import logging
from collections.abc import AsyncGenerator
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
        return self.create_ssl_context(
            self.ssl_cafile, self.ssl_certfile, self.ssl_keyfile
        )

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

    def prepare_path(self, path: str) -> str:
        """Prepare and return the full endpoint path.

        Constructs the full URL path by combining the base path with the provided path.

        :param path: The API endpoint path to request.
        :type path: str
        :return: The full API path.
        :rtype: str
        """
        if self.base_path == "/":
            return urljoin(self.base_path, path)
        trailing_slash = path.endswith("/")
        path = path.strip("/")
        base_path = self.base_path + "/" if path and self.base_path else self.base_path
        path = urljoin(base_path, path)
        return path + "/" if trailing_slash else path

    def prepare_headers(self, headers: dict[str, str] | None = None) -> dict[str, str]:
        """Prepare and merge headers for the API request.

        Combines default headers with any additional (optional) headers provided.

        :param headers: Additional headers to include in the request.
        :type headers: Optional[Dict[str, str]]
        :return: The merged headers dictionary.
        :rtype: dict[str, str]
        """
        headers = headers or {}
        return self.headers | headers

    def prepare_ssl(self) -> SSLContext | bool:
        """Prepare the SSL configuration for the API request.

        Returns the SSL context if SSL verification is enabled, otherwise returns False.

        :return: The SSL context or False.
        :rtype: Union[SSLContext, bool]
        """
        if self.verify_ssl:
            return self.ssl_context
        return False

    async def stream(
        self, path: str, method: str = "get", **kwargs: Any
    ) -> AsyncGenerator[bytes, None]:
        """Perform a streaming HTTP request and yield response content.

        :param path: The API endpoint path to request.
        :type path: str
        :param method: The HTTP method to use for the request. Defaults to "GET".
        :type method: str
        :param kwargs: Additional keyword arguments to pass to the request.
        :type kwargs: Any
        :yield: Lines of response content as bytes.
        :rtype: bytes
        """
        path = self.prepare_path(path)
        kwargs["ssl"] = self.prepare_ssl()
        headers = self.prepare_headers(kwargs.get("headers"))
        logger.debug(
            "Sending %s streaming request to %s%s with kwargs %s and headers %s",
            method,
            self.base_url,
            path,
            kwargs,
            headers,
        )
        async with (
            ClientSession(
                base_url=self.base_url,
                headers=headers,
            ) as session,
            session.request(method, path, **kwargs) as response,
        ):
            async for line in response.content:
                yield line

    async def _request(self, method: str, path: str, **kwargs: Any) -> ClientResponse:
        """Define internal method to perform an HTTP request.

        :param method: The HTTP method to use for the request.
        :type method: str
        :param path: The API endpoint path to request.
        :type path: str
        :param kwargs: Additional keyword arguments to pass to the request.
        :type kwargs: Any
        :return: The aiohttp ClientResponse object.
        :rtype: ClientResponse
        """
        path = self.prepare_path(path)
        kwargs["ssl"] = self.prepare_ssl()
        headers = self.prepare_headers(kwargs.get("headers"))
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

    @staticmethod
    def create_ssl_context(
        cafile: RelativeFilePath | None = None,
        certfile: RelativeFilePath | None = None,
        keyfile: RelativeFilePath | None = None,
    ) -> SSLContext:
        """Initialize and return the SSL context for secure connections.

        Configures the SSL context based on the provided SSL certificate files
        parameters.

        :param cafile: The path to the CA certificate file.
        :type cafile: RelativeFilePath | None
        :param certfile: The path to the certificate file.
        :type certfile: RelativeFilePath | None
        :param keyfile: The path to the certificate key file.
        :type keyfile: RelativeFilePath | None
        :return: The configured SSL context for HTTPS connections.
        :rtype: SSLContext
        """
        context = create_default_context(cafile=cafile)
        if certfile:
            context.load_cert_chain(
                certfile=certfile,
                keyfile=keyfile,
            )
        return context
