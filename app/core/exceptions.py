"""Define reusable exceptions."""

from fastapi import HTTPException, status


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


class HTTPRedirectException(HTTPException):
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
