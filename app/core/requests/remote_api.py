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

"""Manage remote API interactions."""

__all__ = ["BaseRemoteAPI", "RemoteAPI"]

import logging
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar, Token
from functools import cached_property, lru_cache
from ssl import create_default_context, SSLContext
from types import TracebackType
from typing import Any, Self
from urllib.parse import urljoin

from aiohttp import (
    ClientResponse,
    ClientResponseError,
    ClientSession,
    ClientTimeout,
    ContentTypeError,
    TCPConnector,
)
from fastapi import HTTPException, status
from pydantic import computed_field, Field, HttpUrl, PrivateAttr

from app.core.exceptions import HTTPGoneException
from app.core.models import BaseCaseInsensitiveModel
from app.core.utils import json_serializer
from app.core.utils.fields import NonEmptyStr, RelativeFilePathField


class BaseRemoteAPI(BaseCaseInsensitiveModel):
    """Base class for interacting with external APIs.

    Provides foundational functionality for making HTTP requests, handling SSL
    configurations, and managing request paths and headers.

    :param endpoint: The base URL for the external API endpoint.
    :type endpoint: HttpUrl
    :param verify_ssl: Whether to verify SSL certificates. Defaults to True.
    :type verify_ssl: bool
    :param ssl_cafile: Path to the SSL certificate authority file. Defaults to None.
    :type ssl_cafile: RelativeFilePathField | None
    :param ssl_keyfile: Path to the SSL key file. Defaults to None.
    :type ssl_keyfile: RelativeFilePathField | None
    :param ssl_certfile: Path to the SSL certificate file. Defaults to None.
    :type ssl_certfile: RelativeFilePathField | None
    :param logger_name: Name to use for the logger. Defaults to `__name__`.
    :type logger_name: str
    """

    endpoint: HttpUrl = Field(..., frozen=True)
    verify_ssl: bool = Field(default=True, frozen=True)
    ssl_cafile: RelativeFilePathField | None = Field(None, frozen=True)
    ssl_keyfile: RelativeFilePathField | None = Field(None, frozen=True)
    ssl_certfile: RelativeFilePathField | None = Field(None, frozen=True)
    logger_name: str = __name__
    _session: ClientSession | None = None
    _extra_headers: ContextVar[dict[str, str] | None] = PrivateAttr(
        default_factory=lambda: ContextVar("api_extra_headers", default=None)
    )

    def __hash__(self) -> int:
        """Compute the hash based on the endpoint and SSL configuration.

        :return: The hash value of the remote API instance.
        :rtype: int
        """
        return hash(
            (
                self.endpoint,
                self.verify_ssl,
                self.ssl_cafile,
                self.ssl_keyfile,
                self.ssl_certfile,
            )
        )

    async def __aenter__(self) -> Self:
        """Enter the asynchronous context manager.

        Initializes the aiohttp `ClientSession` if not already present.

        :return: The `BaseRemoteAPI` instance.
        :rtype: BaseRemoteAPI
        """
        if getattr(self, "_session", None) is None:
            self.logger.debug("Opening ClientSession for %s", self.base_url)
            connector = TCPConnector(
                ssl=self.ssl_context,
                enable_cleanup_closed=True,
                limit=25,
                limit_per_host=10,
                ttl_dns_cache=300,
                keepalive_timeout=15,
            )
            timeout = ClientTimeout(total=300, connect=5, sock_connect=5, sock_read=120)
            self._session = ClientSession(
                base_url=self.base_url,
                headers=self.headers or None,
                json_serialize=json_serializer,
                connector=connector,
                timeout=timeout,
            )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the asynchronous context manager.

        Closes the aiohttp `ClientSession` if it was initialized.

        :param exc_type: The exception type, if any.
        :type exc_type: type[BaseException] | None
        :param exc_val: The exception value, if any.
        :type exc_val: BaseException | None
        :param exc_tb: The traceback, if any.
        :type exc_tb: TracebackType | None
        """
        if self._session and not self._session.closed:
            self.logger.debug("Closing ClientSession for %s", self.base_url)
            await self._session.close()
        else:
            self.logger.debug("ClientSession already closed for %s", self.base_url)
        self._session = None

    async def open(self) -> Self:
        """Open the asynchronous context manager.

        Initializes the aiohttp `ClientSession` if not already present.

        :return: The `BaseRemoteAPI` instance.
        :rtype: BaseRemoteAPI
        """
        return await self.__aenter__()

    async def close(self) -> None:
        """Close the asynchronous context manager.

        Closes the aiohttp `ClientSession` if it was initialized.
        """
        await self.__aexit__(None, None, None)

    def set_extra_headers(self, extra_headers: dict[str, str] | None) -> Token:
        """Set extra headers to be included in API requests.

        :param extra_headers: A mapping of additional headers to include in requests.
        :type extra_headers: dict[str, str] | None
        :return: A token that can be used to reset the context variable.
        :rtype: Token
        """
        return self._extra_headers.set(extra_headers)

    def reset_extra_headers(self, token: Token) -> None:
        """Reset the extra headers context variable to a previous state.

        :param token: The token returned by `set_extra_headers`.
        :type token: Token
        """
        self._extra_headers.reset(token)

    @contextmanager
    def extra_headers(self, extra_headers: dict[str, str] | None) -> Generator[Self]:
        """Define context manager to temporarily set extra headers for API requests.

        :param extra_headers: A mapping of additional headers to include in requests.
        :type extra_headers: dict[str, str] | None
        :yield: The `BaseRemoteAPI` instance with the extra headers set.
        :rtype: Generator[Self]
        """
        token = self.set_extra_headers(extra_headers)
        try:
            yield self
        finally:
            self.reset_extra_headers(token)

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

    @property
    def ssl_context(self) -> SSLContext | bool:
        """Initialize and return the SSL context for secure connections.

        Configures the SSL context based on the provided SSL certificate files
        and verification settings. If `verify_ssl` is False, returns False to disable
        SSL verification.

        :return: The configured SSL context for HTTPS connections.
        :rtype: SSLContext | bool
        """
        return (
            self.create_ssl_context(
                self.ssl_cafile, self.ssl_certfile, self.ssl_keyfile
            )
            if self.verify_ssl
            else False
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
    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> AsyncGenerator[ClientResponse, None]:
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
        prepared_path = self.prepare_path(path)
        if extra_headers := self._extra_headers.get():
            kwargs["headers"] = kwargs.pop("headers", {}) | extra_headers
        self.logger.debug(
            "RemoteAPI (%s): Sending %s request to %s with kwargs %s",
            self.endpoint,
            method,
            path,
            kwargs,
        )
        async with self._session.request(method, prepared_path, **kwargs) as response:
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
        :raises HTTPGoneException: If the upstream API returns HTTP 410 (e.g. task data
            gone from the Nomad executor). Callers may use ``isinstance(..., HTTPGoneException)``
            or ``exc.status_code == 410`` without inspecting the status from a generic
            :class:`fastapi.HTTPException`.
        :raises HTTPException: For other error responses (same pattern as
            :meth:`RemoteAPI.request`). Without handling non-success statuses, error JSON
            bodies would be yielded as stream chunks; the caller would then continue (e.g.
            poll ``GET /history/{id}``), and later aiohttp requests could surface unrelated
            ``Connection timeout to host`` errors.
        """
        async with self._request(method, path, **kwargs) as response:
            if response.status >= status.HTTP_400_BAD_REQUEST:
                detail_key = getattr(self, "error_detail_key", "detail")
                code_key = getattr(self, "error_code_key", None)
                try:
                    response_data = await response.json()
                except (ContentTypeError, ValueError):
                    text = await response.text()
                    fallback = text or "An unexpected error occurred on the server."
                    if response.status == status.HTTP_410_GONE:
                        raise HTTPGoneException(fallback) from None
                    raise HTTPException(
                        status_code=response.status, detail=fallback
                    ) from None
                error_detail = response_data.get(
                    detail_key, "An unexpected error occurred on the server."
                )
                error_headers = None
                if code_key and (error_code := response_data.get(code_key)):
                    error_headers = {"X-Error-Code": error_code}
                if response.status == status.HTTP_410_GONE:
                    raise HTTPGoneException(error_detail, headers=error_headers)
                raise HTTPException(
                    status_code=response.status,
                    detail=error_detail,
                    headers=error_headers,
                )
            async for line in response.content:
                yield line

    @staticmethod
    @lru_cache(maxsize=8)
    def create_ssl_context(
        cafile: RelativeFilePathField | None = None,
        certfile: RelativeFilePathField | None = None,
        keyfile: RelativeFilePathField | None = None,
    ) -> SSLContext:
        """Initialize and return the SSL context for secure connections.

        Configures the SSL context based on the provided SSL certificate files
        parameters.

        :param cafile: The path to the CA certificate file.
        :type cafile: RelativeFilePathField | None
        :param certfile: The path to the certificate file.
        :type certfile: RelativeFilePathField | None
        :param keyfile: The path to the certificate key file.
        :type keyfile: RelativeFilePathField | None
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
    :type ssl_cafile: RelativeFilePathField | None
    :param ssl_keyfile: Path to the SSL key file. Defaults to None.
    :type ssl_keyfile: RelativeFilePathField | None
    :param ssl_certfile: Path to the SSL certificate file. Defaults to None.
    :type ssl_certfile: RelativeFilePathField | None
    :param logger_name: Name to use for the logger. Defaults to `__name__`.
    :type logger_name: str
    :param error_detail_key: The key to expect error details to be. Defaults to
        "detail".
    :type error_detail_key: NonEmptyStr
    :param error_code_key: The key to expect error codes to be, or None if no error
        code is expected. Defaults to None.
    :type error_code_key: NonEmptyStr | None
    """

    error_detail_key: NonEmptyStr = "detail"
    error_code_key: NonEmptyStr | None = None

    @property
    def headers(self) -> dict[str, str]:
        """Return the default headers to be used in API requests.

        Includes content type and accept headers.

        :return: A dictionary containing the headers for API requests.
        :rtype: dict[str, str]
        """
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @contextmanager
    def auth(self, api_key: str, auth_scheme: str = "Bearer") -> AsyncGenerator[Self]:
        """Define context manager to temporarily set authentication for API requests.

        :param api_key: The API key to use for authentication.
        :type api_key: str
        :param auth_scheme: The authentication scheme to use. Defaults to "Bearer".
        :type auth_scheme: str
        :yield: The `RemoteAPI` instance with authentication headers set.
        :rtype: AsyncGenerator[Self]
        """
        with self.extra_headers(
            {"Authorization": f"{auth_scheme} {api_key}".strip()}
        ) as api:
            yield api

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
        :raises HTTPException: If the request returns an error response.
        """
        async with self._request(method, path, **kwargs) as response:
            try:
                response_data = await response.json()
                self.logger.debug(
                    "RemoteAPI (%s): %s request to %s response (%s): %s",
                    self.endpoint,
                    method,
                    path,
                    response.status,
                    response_data,
                )
                response.raise_for_status()
            except ContentTypeError as err:
                response_content = response.content
                self.logger.exception(
                    "RemoteAPI (%s): %s request to %s response content (%s): %s",
                    self.endpoint,
                    method,
                    path,
                    response.status,
                    response_content,
                )
                raise HTTPException(
                    err.status, detail="An unexpected error occurred on the server."
                ) from None
            except ClientResponseError as err:
                error_detail = response_data.get(
                    self.error_detail_key, "An unexpected error occurred on the server."
                )
                error_headers = None
                if self.error_code_key and (
                    error_code := response_data.get(self.error_code_key)
                ):
                    error_headers = {"X-Error-Code": error_code}
                raise HTTPException(
                    status_code=err.status, detail=error_detail, headers=error_headers
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
