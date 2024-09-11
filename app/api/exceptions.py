"""Define reusable API exceptions."""

from app.core.auth.exceptions import HTTPForbiddenException

InactiveUserException = HTTPForbiddenException("User is not active")
