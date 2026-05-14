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

"""Define asyncio-related utilities."""

import asyncio
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from typing import ParamSpec, TypeVar

__all__ = ["async_run"]

P = ParamSpec("P")
R = TypeVar("R")


async def async_run(
    func: Callable[P, R],
    *args: P.args,
    **kwargs: P.kwargs,
) -> R:
    """Execute a non-async function asynchronously.

    :param func: The function to execute.
    :type func: Callable[P, R]
    :param args: Arguments to pass to the function.
    :type args: P.args
    :param kwargs: Keyword arguments to pass to the function.
    :type kwargs: P.kwargs
    :return: The result of the function execution.
    :rtype: R
    """
    loop = asyncio.get_running_loop()
    call = partial(func, *args, **kwargs)

    with ProcessPoolExecutor(max_workers=1) as pool:
        return await loop.run_in_executor(pool, call)
