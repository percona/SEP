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

from fastapi import HTTPException, status
from starlette.exceptions import HTTPException as StarletteHTTPException


class HTTPNotFoundException(HTTPException):
    """Define exception raised for resource not found (HTTP 404).

    :param detail: A message providing additional details about the exception.
        Defaults to "Not Found".
    :type detail: str
    """

    def __init__(self, detail: str = "Not Found") -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class HTTPConflictException(HTTPException):
    """Define exception raised for resource conflict (HTTP 409).

    :param detail: A message providing additional details about the exception.
        Defaults to "Conflict".
    :type detail: str
    """

    def __init__(self, detail: str = "Conflict") -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


class HTTPBadRequestException(HTTPException):
    """Define exception raised for bad request (HTTP 400).

    :param detail: A message providing additional details about the exception.
        Defaults to "Bad Request".
    :type detail: str
    """

    def __init__(self, detail: str = "Bad Request") -> None:
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class HTTPUnprocessableEntityException(HTTPException):
    """Define exception raised for unprocessable entity (HTTP 422).

    :param detail: A message providing additional details about the exception.
        Defaults to "Unprocessable Entity".
    :type detail: str
    """

    def __init__(self, detail: str = "Unprocessable Entity") -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail
        )


class HTTPGoneException(HTTPException):
    """Define exception raised for resource gone (HTTP 410).

    :param detail: A message providing additional details about the exception.
        Defaults to "Gone".
    :type detail: str
    """

    def __init__(self, detail: str = "Gone") -> None:
        super().__init__(status_code=status.HTTP_410_GONE, detail=detail)


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
