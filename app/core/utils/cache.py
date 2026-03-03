# Copyright 2025 Percona LLC
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

"""Define cache utilities."""

__all__ = ["ttl_cache"]

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from threading import RLock
from time import monotonic
from typing import Any, Generic, NamedTuple, ParamSpec, TypeVar

from pydantic import PositiveFloat, PositiveInt, validate_call

P = ParamSpec("P")
T = TypeVar("T")

_KW_MARKER = object()


def _make_key(
    *, args: tuple[Any, ...], kwargs: dict[str, Any], typed: bool
) -> tuple[Any, ...]:
    """Build a hashable cache key from function arguments.

    This roughly emulates the key strategy used by :func:`functools.lru_cache`.

    :param args: Positional arguments.
    :type args: tuple[Any, ...]
    :param kwargs: Keyword arguments.
    :type kwargs: dict[str, Any]
    :param typed: If `True`, include argument types in the key.
    :type typed: bool
    :return: A hashable tuple key.
    :rtype: tuple[Any, ...]
    """
    if kwargs:
        items = tuple(sorted(kwargs.items()))
        key = (*args, _KW_MARKER, *items)
    else:
        items = ()
        key = args

    if typed:
        key += tuple(type(v) for v in args)
        if items:
            key += (_KW_MARKER, *((k, type(v)) for k, v in items))

    return key


@dataclass(slots=True)
class _CacheShortStats:
    """Define structure to store hits and misses statistics in a cached function.

    :param hits: Number of cache hits.
    :type hits: int
    :param misses: Number of cache misses.
    :type misses: int
    """

    hits: int = 0
    misses: int = 0


class CacheInfo(NamedTuple):
    """Define structure to hold cache statistics.

    This mimics the structure used by :func:`functools.lru_cache`, adding a `ttl` field.

    :param hits: Number of cache hits.
    :type hits: int
    :param misses: Number of cache misses.
    :type misses: int
    :param maxsize: The configured maximum size of the cache (`None` means unlimited).
    :type maxsize: int | None
    :param currsize: Current number of entries stored in the cache.
    :type currsize: int
    :param ttl: Time-to-live, in seconds, for each cached entry.
    :type ttl: float
    """

    hits: int
    misses: int
    maxsize: int | None
    currsize: int
    ttl: float


class _TTLCache(Generic[T]):
    """Encapsulate TTL cache logic with LRU eviction.

    :param ttl: Time-to-live for each cached entry, in seconds.
    :type ttl: float
    :param maxsize: Maximum number of entries to cache (LRU). `None` means unlimited.
    :type maxsize: int | None
    :param typed: If `True`, treat arguments with different types as distinct.
    :type typed: bool
    :ivar: lock: A reentrant lock to ensure thread safety.
    :vartype lock: RLock
    :ivar store: The underlying ordered dictionary used for caching.
    :vartype store: OrderedDict[tuple[Any, ...], tuple[T, float]]
    :ivar hits: Number of cache hits.
    :vartype hits: int
    :ivar misses: Number of cache misses.
    :vartype misses: int
    :ivar prune_limit: Maximum number of expired entries to prune in a single eviction
        cycle.
    :vartype prune_limit: int
    """

    def __init__(self, *, ttl: float, maxsize: int | None, typed: bool) -> None:
        self.ttl = ttl
        self.maxsize = maxsize
        self.typed = typed
        self.lock = RLock()
        self.store = OrderedDict()
        self.hits = self.misses = 0
        self.prune_limit = max(8, min(64, (maxsize or 0) // 64 or 8))

    def evict_if_needed(self, now: float) -> None:
        """Evict expired entries and enforce LRU size limit.

        This method checks the cache for expired entries and removes them. It also
        ensures that the cache does not exceed the maximum size limit. The eviction
        process is limited to a number of entries defined by `prune_limit` to avoid
        excessive performance overhead.

        :param now: Current monotonic time in fractional seconds.
        :type now: float
        """
        for _ in range(min(len(self.store), self.prune_limit)):
            _, old_expires = next(iter(self.store.values()))
            if old_expires > now:
                break
            self.store.popitem(last=False)

        while len(self.store) > (self.maxsize or 0):
            self.store.popitem(last=False)

    def set(self, key: tuple[Any, ...], value: T, now: float) -> None:
        """Set a value in the cache with a TTL.

        This method sets a value in the cache with an expiration time calculated
        as the current time plus the TTL. It also moves the key to the end of the
        cache to mark it as recently used.

        :param key: Cache key.
        :type key: tuple[Any, ...]
        :param value: Value to cache.
        :type value: T
        :param now: Current monotonic time in fractional seconds.
        :type now: float
        """
        expires_at = now + self.ttl
        self.store[key] = (value, expires_at)
        self.store.move_to_end(key)

    def get(self, key: tuple[Any, ...], now: float) -> tuple[bool, T | None]:
        """Get a value from the cache, checking for expiration.

        :param key: Cache key.
        :type key: tuple[Any, ...]
        :param now: Current monotonic time in fractional seconds.
        :type now: float
        :return: Tuple of `(hit, value)` where `hit` is `True` if found and not expired.
        :rtype: tuple[bool, T | None]
        """
        if key in self.store:
            value, exp = self.store[key]
            if exp > now:
                self.store.move_to_end(key)
                self.hits += 1
                return True, value

        self.store.pop(key, None)
        self.misses += 1
        return False, None

    def clear(self) -> None:
        """Clear all cached entries and reset statistics."""
        with self.lock:
            self.store.clear()
            self.hits = 0
            self.misses = 0

    def info(self) -> CacheInfo:
        """Return cache statistics.

        :return: A :class:`CacheInfo` tuple with hits, misses, maxsize, currsize, ttl.
        :rtype: CacheInfo
        """
        with self.lock:
            return CacheInfo(
                hits=self.hits,
                misses=self.misses,
                maxsize=self.maxsize,
                currsize=len(self.store),
                ttl=self.ttl,
            )

    def parameters(self) -> dict[str, Any]:
        """Return the cache configuration parameters.

        :return: Dictionary with `maxsize`, `typed` and `ttl`.
        :rtype: dict[str, Any]
        """
        return {"maxsize": self.maxsize, "typed": self.typed, "ttl": self.ttl}


@validate_call
def ttl_cache(
    *,
    ttl: PositiveFloat,
    maxsize: PositiveInt | None = 128,
    typed: bool = False,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Memoize function results with a time-to-live (TTL) and LRU eviction.

    Works similarly to :func:`functools.lru_cache`, but entries automatically
    expire `ttl` seconds after being written. When an entry is expired it is
    treated as missing and recomputed on the next call.

    :param ttl: Time-to-live for each cached entry, in seconds.
    :type ttl: PositiveFloat
    :param maxsize: Maximum number of entries to cache (LRU). `None` means unlimited.
        Defaults to `128`.
    :type maxsize: PositiveInt | None
    :param typed: If `True`, treat arguments with different types as distinct. Defaults
        to `False`.
    :type typed: bool
    :return: A decorator that applies a TTL/LRU cache to the target function.
    :rtype: Callable[[Callable[P, T]], Callable[P, T]]
    """

    def decorating_function(func: Callable[P, T]) -> Callable[P, T]:
        """Define decorator that applies TTL/LRU caching to a function.

        :param func: The function to be decorated with TTL/LRU caching.
        :type func: Callable[P, T]
        :return: The wrapped function with caching capabilities.
        :rtype: Callable[P, T]
        """
        cache = _TTLCache(ttl=ttl, maxsize=maxsize, typed=typed)

        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            """Define wrapped function with TTL/LRU caching."""
            key = _make_key(args=args, kwargs=kwargs, typed=typed)
            now = monotonic()
            with cache.lock:
                hit, value = cache.get(key, now)
                if hit:
                    return value
            result = func(*args, **kwargs)
            now = monotonic()
            with cache.lock:
                cache.set(key, result, now)
                cache.evict_if_needed(now)
            return result

        wrapper.cache_info = cache.info
        wrapper.cache_clear = cache.clear
        wrapper.cache_parameters = cache.parameters
        return wrapper

    return decorating_function
