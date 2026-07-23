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

"""Define reusable exceptions."""

from typing import Any

from fastapi import HTTPException, status
from starlette.exceptions import HTTPException as StarletteHTTPException


class HTTPNotFoundException(HTTPException):
    """Define exception raised for resource not found (HTTP 404).

    ``detail`` may be a string or a JSON-serializable structure, matching
    :class:`fastapi.HTTPException` (and :class:`HTTPGoneException`), so
    :func:`app.core.requests.remote_api.exception_for_status` can pass through
    structured 404 payloads without a type mismatch.

    :param detail: Human-readable or structured error payload. Defaults to
        ``"Not Found"``.
    :param headers: Optional response headers to preserve (e.g. a PMM
        ``X-Error-Code``).
    """

    def __init__(
        self,
        detail: Any = "Not Found",
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND, detail=detail, headers=headers
        )


class HTTPConflictException(HTTPException):
    """Define exception raised for resource conflict (HTTP 409).

    :param detail: A message, dict, or other JSON-serializable structure providing
        additional details about the exception. Defaults to "Conflict".
    :param headers: Optional response headers to preserve (e.g. ``X-Error-Code``).
    """

    def __init__(
        self, detail: Any = "Conflict", *, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT, detail=detail, headers=headers
        )


class HTTPBadRequestException(HTTPException):
    """Define exception raised for bad request (HTTP 400).

    :param detail: A message, dict, or other JSON-serializable structure providing
        additional details about the exception. Defaults to "Bad Request".
    :param headers: Optional response headers to preserve (e.g. ``X-Error-Code``).
    """

    def __init__(
        self, detail: Any = "Bad Request", *, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST, detail=detail, headers=headers
        )


class HTTPUnprocessableEntityException(HTTPException):
    """Define exception raised for unprocessable content (HTTP 422).

    :param detail: A message, list, dict, or other JSON-serializable structure
        providing additional details about the exception. Defaults to
        "Unprocessable Entity".
    :param headers: Optional response headers to preserve (e.g. ``X-Error-Code``).
    """

    def __init__(
        self,
        detail: Any = "Unprocessable Entity",
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=detail,
            headers=headers,
        )


class HTTPInternalServerErrorException(HTTPException):
    """Define exception raised for an internal server error (HTTP 500).

    ``detail`` accepts a string or a JSON-serializable structure, matching
    :class:`fastapi.HTTPException`, so callers can pass structured payloads
    (e.g. orphaned-task lists from a partial cascade failure).

    :param detail: Human-readable or structured error payload. Defaults to
        ``"Internal Server Error"``.
    :param headers: Optional response headers to preserve (e.g. ``X-Error-Code``).
    """

    def __init__(
        self,
        detail: Any = "Internal Server Error",
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
            headers=headers,
        )


class HTTPBadGatewayException(HTTPException):
    """Define exception raised for bad gateway (HTTP 502).

    :param detail: A message, dict, or other JSON-serializable structure providing
        additional details about the exception. Defaults to "Bad Gateway".
    :param headers: Optional response headers to preserve (e.g. ``X-Error-Code``).
    """

    def __init__(
        self, detail: Any = "Bad Gateway", *, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=detail, headers=headers
        )


class HTTPServiceUnavailableException(HTTPException):
    """Define exception raised for service unavailable (HTTP 503).

    :param detail: A message, dict, or other JSON-serializable structure providing
        additional details about the exception. Defaults to "Service Unavailable".
    :param headers: Optional response headers to preserve (e.g. ``X-Error-Code``).
    """

    def __init__(
        self,
        detail: Any = "Service Unavailable",
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
            headers=headers,
        )


class HTTPGoneException(HTTPException):
    """Define exception raised for resource gone (HTTP 410).

    Used when a remote API signals that data is no longer available (e.g. Tasks API
    task executor state). ``detail`` may be a string or structured JSON (dict), matching
    :class:`fastapi.HTTPException`.

    :param detail: Human-readable or structured error payload. Defaults to ``"Gone"``.
    :type detail: Any
    :param headers: Optional response headers (e.g. ``X-Error-Code``).
    :type headers: dict[str, str] | None
    """

    def __init__(
        self,
        detail: Any = "Gone",
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            status_code=status.HTTP_410_GONE, detail=detail, headers=headers
        )


class HTTPRedirectException(StarletteHTTPException):
    """Define exception raised for redirects.

    :param location: The URL to which the client should be redirected.
    :type location: str
    :param status_code: The HTTP status code for the redirect response. Defaults to
        307 (Temporary Redirect).
    :type status_code: int
    """

    def __init__(
        self, location: str, status_code: int = status.HTTP_307_TEMPORARY_REDIRECT
    ) -> None:
        self.location = location
        super().__init__(status_code=status_code)
        self.headers = {"Location": location}
