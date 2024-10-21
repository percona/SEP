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


class HTTPTemporaryRedirectException(HTTPException):
    """Exception raised for temporary redirect (HTTP 307).

    :param location: The URL to which the client should be redirected.
    :type location: str
    """

    def __init__(self, location: str) -> None:
        self.location = location
        super().__init__(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": location},
        )
