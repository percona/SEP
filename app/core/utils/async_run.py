"""Define asyncio-related utilities."""

import asyncio
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from typing import Any

__all__ = ["async_run"]


async def async_run(func: Callable, *args: Any) -> Any:
    """Execute a non-async function asynchronously.

    :param func: The function to execute.
    :type func: Callable
    :param args: Arguments to pass to the function.
    :type args: Any
    :return: The result of the function execution.
    :rtype: Any
    """

    async def _run_in_process(executor: ProcessPoolExecutor) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(executor, func, *args)

    with ProcessPoolExecutor(max_workers=1) as pool:
        try:
            result = await asyncio.gather(_run_in_process(pool))
        except TimeoutError:
            result = None
    return result
