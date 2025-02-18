"""Define reusable auth exceptions."""

from fastapi import HTTPException, status


class HTTPUnauthorizedException(HTTPException):
    """Exception raised for unauthorized access (HTTP 401).

    :param detail: A message providing additional details about the exception.
        Defaults to "Could not validate credentials".
    :type detail: str
    """

    def __init__(self, detail: str = "Could not validate credentials") -> None:
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


class HTTPForbiddenException(HTTPException):
    """Exception raised for forbidden access (HTTP 403).

    :param detail: A message providing additional details about the exception.
        Defaults to "You don't have permission to perform this action".
    :type detail: str
    """

    def __init__(
        self,
        detail: str = "You don't have permission to perform this action",
    ) -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


InactiveUserException = HTTPForbiddenException("User is not active")


class BaseAuthProviderException(HTTPException):
    """Define base exception for auth providers.

    :param status_code: The HTTP status code for the error response. Defaults to
        502 (Bad Gateway).
    :type status_code: int
    :param detail: A message providing additional details about the exception.
        Defaults to "Error getting response from auth provider.".
    :type detail: str
    """

    def __init__(
        self,
        status_code: int = status.HTTP_502_BAD_GATEWAY,
        detail: str = "Error getting response from auth provider.",
    ) -> None:
        super().__init__(status_code=status_code, detail=detail)
