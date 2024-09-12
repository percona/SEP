"""Define reusable auth exceptions."""

from fastapi import HTTPException
from fastapi import status


class HTTPUnauthorizedException(HTTPException):
    """Exception raised for unauthorized access (HTTP 401).

    Parameters
    ----------
    detail : str, optional
        A message providing additional details about the exception. Defaults to
        "Could not validate credentials".

    """

    def __init__(self, detail: str = "Could not validate credentials"):
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


class HTTPForbiddenException(HTTPException):
    """Exception raised for forbidden access (HTTP 403).

    Parameters
    ----------
    detail : str, optional
        A message providing additional details about the exception. Defaults to
        "You don't have permission to perform this action".

    """

    def __init__(
        self,
        detail: str = "You don't have permission to perform this action",
    ):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class HTTPTemporaryRedirectException(HTTPException):
    """Exception raised for temporary redirect (HTTP 307).

    Parameters
    ----------
    location : str
        The URL to which the client should be redirected.

    """

    def __init__(self, location: str):
        self.location = location
        super().__init__(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": location},
        )
