"""Manage remote API interactions."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import cached_property
from ssl import create_default_context, SSLContext
from types import TracebackType
from typing import Any, Self
from urllib.parse import urljoin

from aiohttp import ClientResponse, ClientResponseError, ClientSession
from fastapi import HTTPException, status
from pydantic import computed_field, HttpUrl

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils import json_serializer
from app.core.utils.fields import RelativeFilePath, RequiredStr


class BaseRemoteAPI(BaseCaseInsensitiveModel):
    """Base class for interacting with external APIs.

    Provides foundational functionality for making HTTP requests, handling SSL
    configurations, and managing request paths and headers.

    :param endpoint: The base URL for the external API endpoint.
    :type endpoint: HttpUrl
    :param verify_ssl: Whether to verify SSL certificates. Defaults to True.
    :type verify_ssl: bool
    :param ssl_cafile: Path to the SSL certificate authority file. Defaults to None.
    :type ssl_cafile: RelativeFilePath | None
    :param ssl_keyfile: Path to the SSL key file. Defaults to None.
    :type ssl_keyfile: RelativeFilePath | None
    :param ssl_certfile: Path to the SSL certificate file. Defaults to None.
    :type ssl_certfile: RelativeFilePath | None
    :param logger_name: Name to use for the logger. Defaults to `__name__`.
    :type logger_name: str
    """

    endpoint: HttpUrl
    verify_ssl: bool = True
    ssl_cafile: RelativeFilePath | None = None
    ssl_keyfile: RelativeFilePath | None = None
    ssl_certfile: RelativeFilePath | None = None
    logger_name: str = __name__
    _session: ClientSession

    async def __aenter__(self) -> Self:
        """Enter the asynchronous context manager.

        Initializes the aiohttp `ClientSession` if not already present.

        :return: The `BaseRemoteAPI` instance.
        :rtype: BaseRemoteAPI
        """
        if getattr(self, "_session", None) is None:
            self.logger.debug("Opening ClientSession for %s", self.base_url)
            headers = self.headers or None
            self._session = ClientSession(
                base_url=self.base_url, headers=headers, json_serialize=json_serializer
            )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException],
        exc_val: BaseException,
        exc_tb: TracebackType,
    ) -> None:
        """Exit the asynchronous context manager.

        Closes the aiohttp `ClientSession` if it was initialized.

        :param exc_type: The exception type, if any.
        :type exc_type: type[BaseException]
        :param exc_val: The exception value, if any.
        :type exc_val: BaseException
        :param exc_tb: The traceback, if any.
        :type exc_tb: Any
        """
        self.logger.debug("Closing ClientSession for %s", self.base_url)
        await self._session.close()

    @cached_property
    def logger(self) -> logging.Logger:
        """Return logger object to use.

        :return: The logger object to use, created with the name set in
            `self.logger_name`.
        :rtype: logging.Logger
        """
        return logging.getLogger(self.logger_name)

    @property
    def session(self) -> ClientSession:
        """Get the ClientSession used in requests.

        :return: The ClientSession used in requests.
        :rtype: ClientSession
        """
        return self._session

    @session.setter
    def session(self, session: ClientSession) -> None:
        """Set the ClientSession used in requests."""
        self._session = session

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

        By default, an empty dict is returned.

        :return: A dictionary containing the headers for API requests.
        :rtype: dict[str, str]
        """
        return {}

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

    @asynccontextmanager
    async def _request(self, method: str, path: str, **kwargs: Any) -> ClientResponse:
        """Define internal method to perform an HTTP request.

        Yields the aiohttp `ClientResponse` object for further processing.

        :param method: The HTTP method to use for the request.
        :type method: str
        :param path: The API endpoint path to request.
        :type path: str
        :param kwargs: Additional keyword arguments to pass to the request.
        :type kwargs: Any
        :yield: The aiohttp `ClientResponse` object.
        :rtype: AsyncGenerator[ClientResponse, None]
        """
        path = self.prepare_path(path)
        kwargs["ssl"] = self.ssl_context if self.verify_ssl else False
        self.logger.debug(
            "RemoteAPI (%s): Sending %s request to %s with kwargs %s",
            self.base_url,
            method,
            path,
            kwargs,
        )
        async with self._session.request(method, path, **kwargs) as response:
            yield response

    async def stream(
        self, path: str, method: str = "GET", **kwargs: Any
    ) -> AsyncGenerator[bytes, None]:
        """Perform a streaming HTTP request and yield response content.

        :param path: The API endpoint path to request.
        :type path: str
        :param method: The HTTP method to use for the request. Defaults to "GET".
        :type method: str
        :param kwargs: Additional keyword arguments to pass to the request.
        :type kwargs: Any
        :yield: Lines of response content as bytes.
        :rtype: AsyncGenerator[bytes, None]
        """
        async with self._request(method, path, **kwargs) as response:
            async for line in response.content:
                yield line

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


class RemoteAPI(BaseRemoteAPI):
    """Interact with external services via HTTP requests.

    Extends `BaseRemoteAPI` to include authentication mechanisms and provides
    methods for standard HTTP operations (GET, POST, PUT, PATCH, DELETE) returning JSON.

    :param endpoint: The base URL for the external API endpoint.
    :type endpoint: HttpUrl
    :param verify_ssl: Whether to verify SSL certificates. Defaults to True.
    :type verify_ssl: bool
    :param ssl_cafile: Path to the SSL certificate authority file. Defaults to None.
    :type ssl_cafile: RelativeFilePath | None
    :param ssl_keyfile: Path to the SSL key file. Defaults to None.
    :type ssl_keyfile: RelativeFilePath | None
    :param ssl_certfile: Path to the SSL certificate file. Defaults to None.
    :type ssl_certfile: RelativeFilePath | None
    :param logger_name: Name to use for the logger. Defaults to `__name__`.
    :type logger_name: str
    :param api_key: The API key for authentication. Defaults to None.
    :type api_key: str | None
    :param auth_scheme: The authentication scheme to use (e.g., "Bearer", "Basic").
        Defaults to "Bearer".
    :type auth_scheme: RequiredStr
    """

    api_key: str | None = None
    auth_scheme: RequiredStr = "Bearer"

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
        }
        if self.api_key:
            headers["Authorization"] = f"{self.auth_scheme} {self.api_key}"
        return headers

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
        :raises HTTPException: If the request fails due to a server error.
        :raises ClientResponseError: If the response contains invalid JSON or
            another low-level error occurs while processing the response.
        """
        async with self._request(method, path, **kwargs) as response:
            try:
                response_data = await response.json()
                self.logger.debug(
                    "%s request to %s%s response: %s, status: %s",
                    method,
                    self.base_url,
                    path,
                    response_data,
                    response.status,
                )
                response.raise_for_status()
            except ClientResponseError as e:
                error_response = {
                    "error": "ClientResponseError",
                    "status_code": e.status,
                    "message": e.message,
                }

                if e.status == status.HTTP_500_INTERNAL_SERVER_ERROR:
                    error_response.update(
                        {"details": "An unexpected error occurred on the server."}
                    )
                else:
                    error_detail = response_data.get(
                        "detail", "No additional details available."
                    )
                    error_response.update({"details": error_detail})

                raise HTTPException(
                    status_code=e.status, detail=error_response
                ) from None

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
