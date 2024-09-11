"""Utility library"""

import asyncio
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from datetime import timezone
from http import HTTPStatus
from typing import Any
from typing import Callable

LOG_FORMAT = "%(asctime)s %(levelname)s:%(name)s: PID<%(process)d> %(module)s.%(funcName)s - %(message)s"
REFRESH_INTERVAL = 3600


def to_uppercase(name: str) -> str:
    """Convert a string to uppercase.

    This function takes a string input and returns a new string with all
    characters converted to uppercase.

    Parameters
    ----------
    name : str
        The string to be converted to uppercase.

    Returns
    -------
    str
        The input string converted to uppercase.

    """
    return name.upper()


class ErrorFormatter:
    __storage = {}

    @property
    def details(self) -> dict:
        return self.__storage.get("details", {})

    @details.setter
    def details(self, details: dict):
        if not isinstance(details, dict):
            raise TypeError("details is not a dict")
        if "details" not in self.__storage or self.__storage["details"] != details:
            self.__storage["details"] = details

    def format_error_heading(self, details: dict) -> str:
        """Extract the error heading

        :param details:
        :return:
        """
        return self._format(details).phrase

    def format_error_message(self, details: dict) -> str:
        """Extract the error message

        :param details:
        :return:
        """
        return self._format(details).description

    def _format(self, details: dict) -> HTTPStatus:
        """:param details:
        :return:
        """
        self.details = details
        if "status_code" not in self.details:
            return HTTPStatus.NOT_FOUND
        return self._resolve_code(self.details["status_code"])

    @staticmethod
    def _resolve_code(code: int) -> HTTPStatus:
        """:param code:
        :return:
        """
        for status_code in HTTPStatus:
            if code == status_code.value:
                return status_code
        return HTTPStatus.NOT_FOUND


error_formatter = ErrorFormatter()
format_error_heading, format_error_message = (
    error_formatter.format_error_heading,
    error_formatter.format_error_message,
)


async def async_run(func: Callable, *args):
    """Execute a non-async call

    :param func:
    :param args:
    :param kwargs:
    :return:
    """

    async def _run_in_process(executor: ProcessPoolExecutor):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(executor, func, *args)

    with ProcessPoolExecutor(max_workers=1) as pool:
        try:
            result = await asyncio.gather(_run_in_process(pool))
        except asyncio.TimeoutError:
            result = None
    return result


def get_timestamp() -> datetime:
    """Get the current time in UTC

    :return: the current time in UTC
    :rtype: datetime
    """
    return datetime.now(tz=timezone.utc)


def deep_dict_update(main_dict: dict[Any, Any], update_dict: dict[Any, Any]) -> None:
    for key, value in update_dict.items():
        if (
            key in main_dict
            and isinstance(main_dict[key], dict)
            and isinstance(value, dict)
        ):
            deep_dict_update(main_dict[key], value)
        elif (
            key in main_dict
            and isinstance(main_dict[key], list)
            and isinstance(update_dict[key], list)
        ):
            main_dict[key] = update_dict[key] + main_dict[key]
        else:
            main_dict[key] = value
