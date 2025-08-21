# Copyright (C) 2025 Percona LLC
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

"""Define iterator utilities."""

from collections.abc import Callable, Generator, Iterable
from typing import Any, TypeVar

__all__ = ["unique_everseen"]

T = TypeVar("T")


def unique_everseen(
    iterable: Iterable[T], key_func: Callable[[T], Any] | None = None
) -> Generator[T]:
    """Yield unique elements, preserving order. Remember all elements ever seen.

    :param iterable: An iterable to filter for unique elements.
    :type iterable: Iterable[T]
    :param key_func: Optional function to extract a key from each element.
    :type key_func: Callable[[T], Any] | None
    :yield: Unique elements from the iterable.
    :rtype: Generator[T]
    """
    seen_set = set()
    seen_list = []
    key_func = key_func or (lambda x: x)
    for item in iterable:
        key = key_func(item)
        try:
            if key not in seen_set:
                seen_set.add(key)
                yield item
        except TypeError:
            if key not in seen_list:
                seen_list.append(key)
                yield item
