"""Define tests for the app.core.exceptions module."""

from http import HTTPStatus

from app.core.exceptions import (
    HTTPBadRequestException,
    HTTPConflictException,
    HTTPNotFoundException,
)


def test_http_not_found_exception():
    """Test HTTPNotFoundException initialization."""
    exception = HTTPNotFoundException("Resource not found")
    assert type(exception).__name__ == "HTTPNotFoundException"
    assert exception.status_code == HTTPStatus.NOT_FOUND
    assert exception.detail == "Resource not found"


def test_http_conflict_exception():
    """Test HTTPConflictException initialization."""
    exception = HTTPConflictException("Resource conflict occurred")
    assert type(exception).__name__ == "HTTPConflictException"
    assert exception.status_code == HTTPStatus.CONFLICT
    assert exception.detail == "Resource conflict occurred"


def test_http_bad_request_exception():
    """Test HTTPBadRequestException initialization."""
    exception = HTTPBadRequestException("Invalid input provided")
    assert type(exception).__name__ == "HTTPBadRequestException"
    assert exception.status_code == HTTPStatus.BAD_REQUEST
    assert exception.detail == "Invalid input provided"
