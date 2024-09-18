"""Define reusable API exceptions."""

from fastapi import HTTPException
from fastapi import status

from app.core.auth.exceptions import HTTPForbiddenException


class HTTPNotFoundException(HTTPException):
    """Exception raised for resource not found (HTTP 404).

    Parameters
    ----------
    detail : str, optional
        A message providing additional details about the exception. Defaults to
        "Not Found".

    """

    def __init__(self, detail: str = "Not Found"):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


InactiveUserException = HTTPForbiddenException("User is not active")
