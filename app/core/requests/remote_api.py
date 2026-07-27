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

__all__ = [
    "UPSTREAM_NON_JSON_HEADER",
    "BaseRemoteAPI",
    "RemoteAPI",
    "exception_for_status",
]

import asyncio
import logging
from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    AsyncIterator,
    Generator,
    Iterable,
    Mapping,
)
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar, Token
from functools import cached_property, lru_cache
from ssl import create_default_context, SSLContext
from types import TracebackType
from typing import Any, BinaryIO, ClassVar, NoReturn, Self
from urllib.parse import urljoin

from aiohttp import (
    ClientResponse,
    ClientResponseError,
    ClientSession,
    ClientTimeout,
    ContentTypeError,
    FormData,
    TCPConnector,
)
from fastapi import HTTPException, status
from pydantic import computed_field, Field, PrivateAttr

from app.core.exceptions import (
    HTTPBadGatewayException,
    HTTPBadRequestException,
    HTTPConflictException,
    HTTPGoneException,
    HTTPInternalServerErrorException,
    HTTPNotFoundException,
    HTTPServiceUnavailableException,
    HTTPUnprocessableEntityException,
)
from app.core.log import correlation_id_var
from app.core.models import BaseCaseInsensitiveModel
from app.core.requests.connectivity import (
    build_connectivity_result,
    classify_connectivity_error,
    ConnectivityResult,
    ConnectivityStatusEnum,
    PROBE_TIMEOUT_SECONDS,
)
from app.core.utils import json_serializer
from app.core.utils.fields import (
    CredentialHttpUrl,
    NonEmptyStr,
    redact_credential_url,
    RelativeFilePathField,
)

# Maximum size of a single line yielded by RemoteAPI.stream(). aiohttp's default
# StreamReader caps lines at ~128 KiB (2 * read_bufsize), which is too small for
# verbose NDJSON log lines from tasks like xtrabackup. 16 MiB stays well below an
# OOM threshold while comfortably covering real log chunks.
_MAX_STREAM_LINE_BYTES = 16 * 1024 * 1024

# Request headers whose values carry credentials and must never reach the logs.
# Compared case-insensitively.
_SENSITIVE_HEADERS = frozenset(
    {"authorization", "x-api-key", "cookie", "proxy-authorization"}
)
# Request body fields whose values carry credentials and must never reach the
# logs. Compared case-insensitively against JSON/form body keys.
_SENSITIVE_BODY_FIELDS = frozenset({"password", "secret", "token"})
_REDACTED_VALUE = "****"

# Stamped on the raised ``HTTPException`` when an error response has a non-JSON
# body (e.g. an nginx HTML 502), letting callers tell a proxy/gateway failure
# apart from an app-level JSON error at the same status code.
UPSTREAM_NON_JSON_HEADER = "X-Upstream-Non-JSON"

#: The body of a single multipart file part: raw bytes held in memory, an open
#: binary handle, or an async iterator of chunks. aiohttp streams the latter two,
#: so a caller forwarding a file it never has on disk passes the iterator through.
FileContent = bytes | BinaryIO | AsyncIterable[bytes]

#: A single multipart file part: ``(filename, content, content_type)``.
FileSpec = tuple[str, FileContent, str]

# Maps an upstream error status to the project exception that represents it, so
# RemoteAPI raises app/core/exceptions classes instead of a bare HTTPException.
_HTTP_EXCEPTION_BY_STATUS: dict[int, type[HTTPException]] = {
    status.HTTP_400_BAD_REQUEST: HTTPBadRequestException,
    status.HTTP_404_NOT_FOUND: HTTPNotFoundException,
    status.HTTP_409_CONFLICT: HTTPConflictException,
    status.HTTP_410_GONE: HTTPGoneException,
    status.HTTP_422_UNPROCESSABLE_CONTENT: HTTPUnprocessableEntityException,
    status.HTTP_500_INTERNAL_SERVER_ERROR: HTTPInternalServerErrorException,
    status.HTTP_502_BAD_GATEWAY: HTTPBadGatewayException,
    status.HTTP_503_SERVICE_UNAVAILABLE: HTTPServiceUnavailableException,
}


def _is_redirect(status_code: int) -> bool:
    """Return whether ``status_code`` is a 3xx redirect.

    :param status_code: The upstream HTTP status to classify.
    :return: ``True`` for any 3xx status.
    """
    return status.HTTP_300_MULTIPLE_CHOICES <= status_code < status.HTTP_400_BAD_REQUEST


def exception_for_status(
    status_code: int, *, detail: Any, headers: dict[str, str] | None = None
) -> HTTPException:
    """Return the project exception mapped to ``status_code``, else a bare HTTPException.

    Fall back to a bare :class:`fastapi.HTTPException` when no project class is
    mapped. Every mapped class accepts a ``headers`` kwarg, so headers are always
    preserved.

    A non-JSON error body (marked with ``UPSTREAM_NON_JSON_HEADER``) signals a
    proxy/gateway failure rather than an app-level status, so a non-JSON 404 stays
    a bare HTTPException -- callers narrowing to ``except HTTPNotFoundException``
    must not mistake an upstream infra failure for a real resource-absent
    response. The other statuses keep their mapping on non-JSON bodies, matching
    how they already behave for JSON bodies.

    :param status_code: The upstream HTTP error status to translate.
    :param detail: The error detail payload to attach to the exception.
    :param headers: Optional response headers to preserve (e.g. ``X-Error-Code``).
    :return: The mapped project exception, or a bare HTTPException.
    """
    exc_class = _HTTP_EXCEPTION_BY_STATUS.get(status_code)
    is_non_json = bool(headers) and UPSTREAM_NON_JSON_HEADER in headers
    if exc_class is None or (is_non_json and exc_class is HTTPNotFoundException):
        return HTTPException(status_code=status_code, detail=detail, headers=headers)
    return exc_class(detail, headers=headers)


def _sanitize_request_kwargs(
    kwargs: dict[str, Any],
    *,
    extra_sensitive_headers: frozenset[str] = frozenset(),
    extra_sensitive_body_fields: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Return a shallow copy of request kwargs with credentials redacted.

    The auth context injects an ``Authorization`` header into ``kwargs`` before
    the request is logged, and some endpoints post credentials in the request
    body (a password-login payload, for example); this scrubs both
    credential-bearing headers and known-sensitive body fields so secrets never
    reach the debug log. Only the returned copy is masked -- the outgoing
    request keeps the real values.

    :param kwargs: The request keyword arguments about to be logged.
    :param extra_sensitive_headers: Additional lowercase header names to mask,
        beyond the always-masked credential headers.
    :param extra_sensitive_body_fields: Additional lowercase body field names to
        mask, beyond the always-masked credential fields.
    :return: A copy safe to log, with sensitive header and body values masked.
    """
    sensitive_headers = _SENSITIVE_HEADERS | extra_sensitive_headers
    sensitive_body_fields = _SENSITIVE_BODY_FIELDS | extra_sensitive_body_fields
    safe = {**kwargs}
    headers = kwargs.get("headers")
    if headers:
        safe["headers"] = {
            key: (_REDACTED_VALUE if key.lower() in sensitive_headers else value)
            for key, value in headers.items()
        }
    for body_key in ("json", "data"):
        body = kwargs.get(body_key)
        if isinstance(body, dict):
            safe[body_key] = {
                key: (
                    _REDACTED_VALUE if key.lower() in sensitive_body_fields else value
                )
                for key, value in body.items()
            }
    return safe


def _raise_stream_line_too_big(size: int, path: str) -> NoReturn:
    """Raise :class:`ValueError` for a stream line larger than the cap.

    :param size: Size in bytes of the offending line or pending buffer.
    :type size: int
    :param path: The stream path, included in the error message.
    :type path: str
    :raises ValueError: Always — this function never returns.
    """
    msg = (
        f"Stream line exceeded {_MAX_STREAM_LINE_BYTES} bytes "
        f"(size={size}, path={path})"
    )
    raise ValueError(msg)


async def _iter_lines_from_chunks(
    chunks: AsyncIterator[bytes], path: str
) -> AsyncGenerator[bytes, None]:
    """Yield newline-terminated lines from an async iterator of byte chunks.

    Buffer chunks from ``chunks`` and yield each newline-terminated slice with
    the trailing newline byte preserved. Flush any remaining partial line at
    end-of-stream so callers receive the final unterminated chunk. Reject any
    line larger than ``_MAX_STREAM_LINE_BYTES`` to protect consumers from a
    runaway producer.

    :param chunks: An async iterator producing byte chunks (e.g. from
        ``aiohttp`` ``StreamReader.iter_any()``).
    :type chunks: AsyncIterator[bytes]
    :param path: The stream path, included in the error message when a single
        line exceeds the cap.
    :type path: str
    :yield: Each line as ``bytes`` with its trailing newline preserved; the
        final unterminated chunk is also yielded when the stream ends without
        a newline.
    :rtype: AsyncGenerator[bytes, None]
    :raises ValueError: If a single line exceeds ``_MAX_STREAM_LINE_BYTES``.
    """
    buffer = bytearray()
    async for chunk in chunks:
        if not chunk:
            continue
        buffer.extend(chunk)
        offset = 0
        while True:
            newline_pos = buffer.find(b"\n", offset)
            if newline_pos == -1:
                break
            line_end = newline_pos + 1
            line_size = line_end - offset
            if line_size > _MAX_STREAM_LINE_BYTES:
                _raise_stream_line_too_big(line_size, path)
            yield bytes(buffer[offset:line_end])
            offset = line_end
        if offset:
            del buffer[:offset]
        if len(buffer) > _MAX_STREAM_LINE_BYTES:
            _raise_stream_line_too_big(len(buffer), path)
    if buffer:
        if len(buffer) > _MAX_STREAM_LINE_BYTES:
            _raise_stream_line_too_big(len(buffer), path)
        yield bytes(buffer)


class BaseRemoteAPI(BaseCaseInsensitiveModel):
    """Base class for interacting with external APIs.

    Provides foundational functionality for making HTTP requests, handling SSL
    configurations, and managing request paths and headers.

    :param endpoint: The base URL for the external API endpoint.
    :type endpoint: CredentialHttpUrl
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
    :cvar CONNECTIVITY_CHECK_PATH: Lightweight route hit by
        :meth:`RemoteAPI.check_connectivity` for a reachability probe. Never
        enters the client-registry key or model serialization. Override per
        client, or pass an explicit ``path`` to ``check_connectivity``.
    """

    CONNECTIVITY_CHECK_PATH: ClassVar[str] = "/"
    endpoint: CredentialHttpUrl = Field(..., frozen=True)
    verify_ssl: bool = Field(default=True, frozen=True)
    ssl_cafile: RelativeFilePathField | None = Field(None, frozen=True)
    ssl_keyfile: RelativeFilePathField | None = Field(None, frozen=True)
    ssl_certfile: RelativeFilePathField | None = Field(None, frozen=True)
    logger_name: str = __name__
    _session: ClientSession | None = None
    _extra_headers: ContextVar[dict[str, str] | None] = PrivateAttr(
        default_factory=lambda: ContextVar("api_extra_headers", default=None)
    )
    _extra_sensitive_headers: ContextVar[frozenset[str]] = PrivateAttr(
        default_factory=lambda: ContextVar(
            "api_extra_sensitive_headers", default=frozenset()
        )
    )
    _extra_sensitive_body_fields: ContextVar[frozenset[str]] = PrivateAttr(
        default_factory=lambda: ContextVar(
            "api_extra_sensitive_body_fields", default=frozenset()
        )
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

    @contextmanager
    def redact_headers(self, names: Iterable[str]) -> Generator[Self]:
        """Mask additional request headers in the debug request log for the call.

        Register case-insensitive header names whose values must be redacted in
        the request-log line for the duration of the call, on top of the
        always-masked credential headers. Use this to hide a custom-named
        credential header a caller injects via :meth:`extra_headers`.

        :param names: Header names to mask, compared case-insensitively.
        :yield: The instance with the extra redaction set applied.
        """
        token = self._extra_sensitive_headers.set(
            self._extra_sensitive_headers.get() | frozenset(n.lower() for n in names)
        )
        try:
            yield self
        finally:
            self._extra_sensitive_headers.reset(token)

    @contextmanager
    def redact_body_fields(self, names: Iterable[str]) -> Generator[Self]:
        """Mask additional request-body fields in the debug request log for the call.

        Register case-insensitive body keys whose values must be redacted in the
        request-log line for the duration of the call, on top of the
        always-masked credential fields. Use this to hide a custom-named
        credential a caller posts in a JSON or form body.

        :param names: Body field names to mask, compared case-insensitively.
        :yield: The instance with the extra redaction set applied.
        """
        token = self._extra_sensitive_body_fields.set(
            self._extra_sensitive_body_fields.get()
            | frozenset(name.lower() for name in names)
        )
        try:
            yield self
        finally:
            self._extra_sensitive_body_fields.reset(token)

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
        correlation_id = correlation_id_var.get()
        if correlation_id != "-":
            kwargs["headers"] = kwargs.pop("headers", {}) | {
                "X-Correlation-ID": correlation_id
            }
        self.logger.debug(
            "RemoteAPI (%s): Sending %s request to %s with kwargs %s",
            redact_credential_url(str(self.endpoint)),
            method,
            path,
            _sanitize_request_kwargs(
                kwargs,
                extra_sensitive_headers=self._extra_sensitive_headers.get(),
                extra_sensitive_body_fields=self._extra_sensitive_body_fields.get(),
            ),
        )
        async with self._session.request(method, prepared_path, **kwargs) as response:
            yield response

    @staticmethod
    def _raise_stream_http_error(
        status_code: int,
        *,
        detail: Any,
        headers: dict[str, str] | None = None,
    ) -> NoReturn:
        """Raise the mapped project exception (or bare HTTPException) for a failed stream.

        :param status_code: The upstream HTTP error status.
        :param detail: The error detail payload for the raised exception.
        :param headers: Optional response headers to preserve.
        """
        raise exception_for_status(
            status_code, detail=detail, headers=headers
        ) from None

    async def stream_chunks(
        self, path: str, method: str = "GET", **kwargs: Any
    ) -> AsyncGenerator[bytes, None]:
        """Perform a streaming HTTP request and yield raw byte chunks as they arrive.

        Use this for binary, gzip, or any non-line-oriented payload. For NDJSON
        log streams, prefer :meth:`stream`, which buffers chunks across newline
        boundaries so each yield is a single line.

        :param path: The API endpoint path to request.
        :type path: str
        :param method: The HTTP method to use for the request. Defaults to "GET".
        :type method: str
        :param kwargs: Additional keyword arguments to pass to the request.
        :type kwargs: Any
        :yield: Raw byte chunks from the response body in arrival order.
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
        self.logger.debug("Stream started path=%s method=%s", path, method)
        try:
            async with self._request(method, path, **kwargs) as response:
                if response.status >= status.HTTP_400_BAD_REQUEST:
                    detail_key = getattr(self, "error_detail_key", "detail")
                    code_key = getattr(self, "error_code_key", None)
                    try:
                        response_data = await response.json()
                    except (ContentTypeError, ValueError):
                        text = await response.text()
                        fallback = text or "An unexpected error occurred on the server."
                        self._raise_stream_http_error(
                            response.status,
                            detail=fallback,
                            headers={UPSTREAM_NON_JSON_HEADER: "1"},
                        )
                    error_body = (
                        response_data if isinstance(response_data, Mapping) else {}
                    )
                    error_detail = error_body.get(
                        detail_key, "An unexpected error occurred on the server."
                    )
                    error_headers = None
                    if code_key and (error_code := error_body.get(code_key)):
                        error_headers = {"X-Error-Code": str(error_code)}
                    self._raise_stream_http_error(
                        response.status,
                        detail=error_detail,
                        headers=error_headers,
                    )
                async for chunk in response.content.iter_any():
                    if chunk:
                        yield chunk
            self.logger.debug("Stream ended normally path=%s method=%s", path, method)
        except HTTPException:
            raise
        except Exception as exc:
            self.logger.warning(
                "Stream error path=%s method=%s: %s",
                path,
                method,
                exc,
                exc_info=True,
            )
            raise

    async def stream(
        self, path: str, method: str = "GET", **kwargs: Any
    ) -> AsyncGenerator[bytes, None]:
        """Perform a streaming HTTP request and yield response content one line at a time.

        Buffer chunks across newline boundaries and yield each newline-terminated
        slice with its trailing newline byte preserved. Flush any remaining partial
        line at end-of-stream. Use this for NDJSON log streams; for binary or
        non-line payloads, use :meth:`stream_chunks`.

        :param path: The API endpoint path to request.
        :type path: str
        :param method: The HTTP method to use for the request. Defaults to "GET".
        :type method: str
        :param kwargs: Additional keyword arguments to pass to the request.
        :type kwargs: Any
        :yield: Each line of response content as ``bytes`` with its trailing
            newline preserved; the final unterminated chunk is also yielded
            when the body does not end with a newline.
        :rtype: AsyncGenerator[bytes, None]
        :raises HTTPGoneException: See :meth:`stream_chunks`.
        :raises HTTPException: See :meth:`stream_chunks`.
        :raises ValueError: If a single line exceeds ``_MAX_STREAM_LINE_BYTES``.
        """
        try:
            async for line in _iter_lines_from_chunks(
                self.stream_chunks(path, method, **kwargs), path
            ):
                yield line
        except ValueError as exc:
            self.logger.warning(
                "Stream line cap exceeded path=%s method=%s: %s",
                path,
                method,
                exc,
                exc_info=True,
            )
            raise

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
    methods for standard HTTP operations (GET, POST, PUT, PATCH, DELETE) returning
    parsed JSON, or ``None`` when the response has no body (for example HTTP 204).

    :param endpoint: The base URL for the external API endpoint.
    :type endpoint: CredentialHttpUrl
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

    async def check_connectivity(
        self, service: str, *, path: str | None = None
    ) -> ConnectivityResult:
        """Probe the endpoint and return a normalized connectivity result.

        Issue a lightweight ``GET`` against ``path`` (or
        :attr:`CONNECTIVITY_CHECK_PATH`) under a short bounded timeout and map
        the outcome to one of the :class:`ConnectivityStatusEnum` states:
        reachable, authentication failure, unreachable, SSL verification
        failure, or timeout. Any failure is captured and classified -- this
        method never raises -- so a single probe can be fanned out safely
        alongside others.

        The result carries only fixed, secret-free ``detail`` text; the
        configured API key and any credentials embedded in the endpoint URL are
        never echoed.

        :param service: Stable identifier of the probed service (e.g. ``"pmm"``).
        :type service: str
        :param path: Optional override for the probe route. Defaults to
            :attr:`CONNECTIVITY_CHECK_PATH`.
        :type path: str | None
        :return: The normalized connectivity result.
        :rtype: ConnectivityResult
        """
        probe_path = path if path is not None else self.CONNECTIVITY_CHECK_PATH
        try:
            async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
                await self.get(probe_path)
        except Exception as exc:  # noqa: BLE001 -- classified, never re-raised
            return build_connectivity_result(service, classify_connectivity_error(exc))
        return build_connectivity_result(service, ConnectivityStatusEnum.REACHABLE)

    async def request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Perform an HTTP request and return the JSON response.

        :param method: The HTTP method to use for the request.
        :param path: The API endpoint path to request.
        :param kwargs: Additional keyword arguments to pass to the request.
        :return: The JSON response as a Python object, or ``None`` when the
            server returns HTTP 204 No Content (no response body).
        :raises HTTPException: If the request returns an error response -- the
            project exception mapped to the status (a subclass of
            :class:`fastapi.HTTPException`), or a bare :class:`fastapi.HTTPException`
            when the status is unmapped or a non-JSON 404 must stay unmapped.
            A ``3xx`` response also raises when the caller passed
            ``allow_redirects=False``: the redirect was not followed, so the
            status is reported rather than treated as a result.
        """
        follows_redirects = kwargs.get("allow_redirects", True)
        async with self._request(method, path, **kwargs) as response:
            if response.status == status.HTTP_204_NO_CONTENT:
                return None
            if not follows_redirects and _is_redirect(response.status):
                self.logger.warning(
                    "RemoteAPI (%s): %s request to %s answered %s, which this "
                    "caller does not follow.",
                    redact_credential_url(str(self.endpoint)),
                    method,
                    path,
                    response.status,
                )
                raise exception_for_status(
                    response.status,
                    detail="The server answered with an unfollowed redirect.",
                )
            try:
                response_data = await response.json()
                self.logger.debug(
                    "RemoteAPI (%s): %s request to %s response (%s): %s",
                    redact_credential_url(str(self.endpoint)),
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
                    redact_credential_url(str(self.endpoint)),
                    method,
                    path,
                    response.status,
                    response_content,
                )
                raise exception_for_status(
                    err.status,
                    detail="An unexpected error occurred on the server.",
                    headers={UPSTREAM_NON_JSON_HEADER: "1"},
                ) from None
            except ClientResponseError as err:
                error_body = response_data if isinstance(response_data, Mapping) else {}
                error_detail = error_body.get(
                    self.error_detail_key, "An unexpected error occurred on the server."
                )
                error_headers = None
                if self.error_code_key and (
                    error_code := error_body.get(self.error_code_key)
                ):
                    error_headers = {"X-Error-Code": str(error_code)}
                raise exception_for_status(
                    err.status, detail=error_detail, headers=error_headers
                ) from None

            return response_data

    async def get(
        self, path: str, **kwargs: Any
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Perform a GET request and return the JSON response.

        :param path: The API endpoint path to request.
        :type path: str
        :param kwargs: Additional keyword arguments to pass to the request.
        :type kwargs: Any
        :return: The JSON response as a Python object, or ``None`` on HTTP 204.
        :rtype: dict[str, Any] | list[dict[str, Any]] | None
        """
        return await self.request("GET", path, **kwargs)

    async def post(
        self, path: str, **kwargs: Any
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Perform a POST request and return the JSON response.

        :param path: The API endpoint path to request.
        :type path: str
        :param kwargs: Additional keyword arguments to pass to the request.
        :type kwargs: Any
        :return: The JSON response as a Python object, or ``None`` on HTTP 204.
        :rtype: dict[str, Any] | list[dict[str, Any]] | None
        """
        return await self.request("POST", path, **kwargs)

    async def put(
        self, path: str, **kwargs: Any
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Perform a PUT request and return the JSON response.

        :param path: The API endpoint path to request.
        :type path: str
        :param kwargs: Additional keyword arguments to pass to the request.
        :type kwargs: Any
        :return: The JSON response as a Python object, or ``None`` on HTTP 204.
        :rtype: dict[str, Any] | list[dict[str, Any]] | None
        """
        return await self.request("PUT", path, **kwargs)

    async def patch(
        self, path: str, **kwargs: Any
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Perform a PATCH request and return the JSON response.

        :param path: The API endpoint path to request.
        :type path: str
        :param kwargs: Additional keyword arguments to pass to the request.
        :type kwargs: Any
        :return: The JSON response as a Python object, or ``None`` on HTTP 204.
        :rtype: dict[str, Any] | list[dict[str, Any]] | None
        """
        return await self.request("PATCH", path, **kwargs)

    async def delete(
        self, path: str, **kwargs: Any
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Perform a DELETE request and return the JSON response.

        :param path: The API endpoint path to request.
        :type path: str
        :param kwargs: Additional keyword arguments to pass to the request.
        :type kwargs: Any
        :return: The JSON response as a Python object, or ``None`` on HTTP 204.
        :rtype: dict[str, Any] | list[dict[str, Any]] | None
        """
        return await self.request("DELETE", path, **kwargs)

    async def upload(
        self,
        path: str,
        *,
        files: Mapping[str, FileSpec],
        fields: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Send a ``multipart/form-data`` body (file bundle plus scalar fields).

        Reuse the JSON request transport for error translation, credential
        redaction, correlation IDs, and SSL. Two deltas versus :meth:`request`:
        the multipart body carries its own boundary Content-Type, which must
        override the session's default ``application/json`` header; and a
        successful non-JSON response body is tolerated -- a vendor-neutral intake
        may answer ``201`` with a ``text/plain`` acknowledgement or an empty
        (non-204) body, which :meth:`request` alone surfaces as a bare ``2xx``
        ``HTTPException`` because it parses the body before ``raise_for_status``.

        :param path: The API endpoint path to POST to.
        :param files: Multipart file parts keyed by field name; each value is a
            ``(filename, content, content_type)`` tuple. Pass an open binary file
            handle or an async byte iterator as ``content`` to stream a large
            bundle with bounded memory.
        :param fields: Scalar form fields sent alongside the files.
        :param kwargs: Additional keyword arguments passed through to the request.
        :return: The parsed JSON response, or ``None`` on a ``2xx`` response with
            an empty or non-JSON body.
        :raises HTTPException: The project exception mapped to an error status,
            as translated by :meth:`request`.
        """
        form = FormData()
        for name, value in (fields or {}).items():
            form.add_field(name, value)
        for name, (filename, content, content_type) in files.items():
            form.add_field(name, content, filename=filename, content_type=content_type)
        payload = form()
        headers = {**kwargs.pop("headers", {}), "Content-Type": payload.content_type}
        try:
            return await self.request(
                "POST", path, data=payload, headers=headers, **kwargs
            )
        except HTTPException as exc:
            if exc.status_code < status.HTTP_400_BAD_REQUEST and (
                exc.headers or {}
            ).get(UPSTREAM_NON_JSON_HEADER):
                return None
            raise
