# Copyright (C) 2026 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Provide a lazy proxy for deferring object instantiation to first access."""

from __future__ import annotations

from typing import Generic, TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

T = TypeVar("T")

_SENTINEL = object()


class LazyProxy(Generic[T]):
    """Defer instantiation of an object until the first attribute access.

    Wrap a zero-argument factory callable. The factory is not called until
    an attribute is read, set, or deleted on the proxy. After the first call,
    the result is cached and all subsequent operations delegate directly to
    the cached instance.

    :param factory: Zero-argument callable that produces the real instance.
    :type factory: Callable[[], T]
    """

    __slots__ = ("_factory", "_instance")

    def __init__(self, factory: Callable[[], T]) -> None:
        object.__setattr__(self, "_factory", factory)
        object.__setattr__(self, "_instance", _SENTINEL)

    def _resolve(self) -> T:
        """Resolve the proxy by calling the factory if not yet resolved.

        :return: The real instance produced by the factory.
        :rtype: T
        """
        instance = object.__getattribute__(self, "_instance")
        if instance is _SENTINEL:
            factory = object.__getattribute__(self, "_factory")
            instance = factory()
            object.__setattr__(self, "_instance", instance)
        return instance

    def __getattr__(self, name: str) -> object:
        return getattr(self._resolve(), name)

    def __setattr__(self, name: str, value: object) -> None:
        setattr(self._resolve(), name, value)

    def __delattr__(self, name: str) -> None:
        delattr(self._resolve(), name)

    @property
    def __class__(self) -> type:
        """Return the class of the wrapped instance for isinstance() support."""
        return type(self._resolve())

    def __repr__(self) -> str:
        instance = object.__getattribute__(self, "_instance")
        if instance is _SENTINEL:
            factory = object.__getattribute__(self, "_factory")
            return f"<LazyProxy({factory!r}) unresolved>"
        return repr(instance)
