"""Module containing decorators for CSRF exemption."""

from collections.abc import Callable
from functools import wraps
from typing import Any


def csrf_exempt(func: Callable[..., Any]) -> Callable[..., Any]:
    """Mark a route handler as exempt from CSRF checks."""

    @wraps(func)
    async def wrapper(*args: tuple[Any, ...], **kwargs: dict[str, Any]) -> Any:
        request = kwargs.get("request") or (args[0] if args else None)

        if request and hasattr(request, "state"):
            request.state.is_csrf_exempt = True

        return await func(*args, **kwargs)

    return wrapper
