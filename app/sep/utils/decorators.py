"""Define reusable decorators for the SEP app."""

from collections.abc import Callable
from functools import wraps
from typing import Any


def csrf_exempt(func: Callable[..., Any]) -> Callable[..., Any]:
    """Mark a route handler as exempt from CSRF checks."""

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        request = kwargs.get("request") or (args[0] if args else None)
        request.state.is_csrf_exempt = True
        return await func(*args, **kwargs)

    return wrapper
