"""Define reusable API exceptions."""

from fastapi import HTTPException
from fastapi import status

from app.core.auth.exceptions import HTTPForbiddenException


class HTTPNotFoundException(HTTPException):
    """Exception raised for resource not found (HTTP 404).

    :param detail: A message providing additional details about the exception.
        Defaults to "Not Found".
    :type detail: str
    """

    def __init__(self, detail: str = "Not Found") -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class HTTPConflictException(HTTPException):
    """Exception raised for resource conflict (HTTP 409).

    :param detail: A message providing additional details about the exception.
        Defaults to "Conflict".
    :type detail: str
    """

    def __init__(self, detail: str = "Conflict") -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


class HTTPBadRequestException(HTTPException):
    """Exception raised for bad request (HTTP 400).

    :param detail: A message providing additional details about the exception.
        Defaults to "Bad Request".
    :type detail: str
    """

    def __init__(self, detail: str = "Bad Request") -> None:
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


InactiveUserException = HTTPForbiddenException("User is not active")
