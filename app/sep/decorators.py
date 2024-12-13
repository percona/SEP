"""Module containing decorators for CSRF exemption."""

from collections.abc import Callable
from typing import Any


def csrf_exempt(func: Callable[..., Any]) -> Callable[..., Any]:
    """Mark a route handler as exempt from CSRF checks."""
    func.is_csrf_exempt = True
    return func
