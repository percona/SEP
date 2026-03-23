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

"""Define tests for the app.core.exceptions module."""

from fastapi import status

from app.core.exceptions import (
    HTTPBadRequestException,
    HTTPConflictException,
    HTTPGoneException,
    HTTPNotFoundException,
)


def test_http_not_found_exception():
    """Test HTTPNotFoundException initialization."""
    exception = HTTPNotFoundException("Resource not found")
    assert type(exception).__name__ == "HTTPNotFoundException"
    assert exception.status_code == status.HTTP_404_NOT_FOUND
    assert exception.detail == "Resource not found"


def test_http_conflict_exception():
    """Test HTTPConflictException initialization."""
    exception = HTTPConflictException("Resource conflict occurred")
    assert type(exception).__name__ == "HTTPConflictException"
    assert exception.status_code == status.HTTP_409_CONFLICT
    assert exception.detail == "Resource conflict occurred"


def test_http_bad_request_exception():
    """Test HTTPBadRequestException initialization."""
    exception = HTTPBadRequestException("Invalid input provided")
    assert type(exception).__name__ == "HTTPBadRequestException"
    assert exception.status_code == status.HTTP_400_BAD_REQUEST
    assert exception.detail == "Invalid input provided"


def test_http_gone_exception_string_detail():
    """Test HTTPGoneException with a string detail."""
    exc = HTTPGoneException("Stale resource")
    assert exc.status_code == status.HTTP_410_GONE
    assert exc.detail == "Stale resource"


def test_http_gone_exception_structured_detail():
    """Test HTTPGoneException with structured detail (e.g. Tasks API executor payload)."""
    payload = {"message": "gone", "resource_type": "allocation"}
    exc = HTTPGoneException(payload, headers={"X-Error-Code": "E1"})
    assert exc.status_code == status.HTTP_410_GONE
    assert exc.detail == payload
    assert exc.headers == {"X-Error-Code": "E1"}
