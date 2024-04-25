"""
Utility library
"""

import asyncio
from concurrent.futures import ProcessPoolExecutor
from datetime import (
    datetime,
    timezone,
)
from http import HTTPStatus
import json
import logging
import os.path
from sys import argv
from time import time
import traceback
from typing import (
    Callable,
    Union,
)

from fastapi import Request
import requests
from tornado.httpclient import (
    AsyncHTTPClient,
    HTTPRequest,
)
from tornado.log import app_log
from tornado.template import (
    Loader,
    Template,
)
from tornado.util import ObjectDict
from tornado.web import (
    HTTPError,
    RequestHandler,
)

LOG_FORMAT = "%(asctime)s %(levelname)s:%(name)s: PID<%(process)d> %(module)s.%(funcName)s - %(message)s"
REFRESH_INTERVAL = 3600


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
        """

        :param details:
        :return:
        """
        self.details = details
        if "status_code" not in self.details:
            return HTTPStatus.NOT_FOUND
        return self._resolve_code(self.details["status_code"])

    @staticmethod
    def _resolve_code(code: int) -> HTTPStatus:
        """

        :param code:
        :return:
        """
        for status_code in HTTPStatus:
            if code == status_code.value:
                return status_code
        return HTTPStatus.NOT_FOUND


error_formatter = ErrorFormatter()
format_error_heading, format_error_message = error_formatter.format_error_heading, error_formatter.format_error_message


async def async_request(
    url: str,
    request: Union["Request", "HTTPServerRequest"],
    method: str = "GET",
    payload: dict | None = None,
    raise_error: bool = True,
    return_raw_body: bool = False,
    **kwargs,
) -> Union[dict, list, str, bytes]:
    """Make an async HTTP request for JSON

    :param url:
    :param request:
    :param method:
    :param payload:
    :param raise_error:
    :param return_raw_body:
    :param kwargs:
    :return:
    """
    app_log.debug("Making %s request to %s", method, url)
    client = AsyncHTTPClient()
    headers = dict(request.headers)
    headers["Content-Type"] = "application/json"
    if method == "POST" and not payload:
        raise HTTPError(status_code=HTTPStatus.BAD_REQUEST, log_message=f"POST request is missing payload")
    if payload:
        app_log.debug("Payload: %s", payload)
        kwargs["body"] = json.dumps(payload)

    if "Content-Length" in headers:
        # TODO: check this, it seemed to cause an issue deleting from the archiver app
        #       when the content length was left in place
        del headers["Content-Length"]
    response = await client.fetch(
        HTTPRequest(url=url, method=method, headers=headers, **kwargs), raise_error=raise_error
    )

    if return_raw_body:
        return response.body
    try:
        return json.loads(response.body.decode())
    except json.decoder.JSONDecodeError:
        return response.body.decode()


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


def get_logger(name: str, level: int = logging.WARNING) -> logging.Logger:
    """Get a logger instance

    :param name: name of the logger
    :type name: str
    :param level: logging level as per logging.getLevelNamesMapping().values()
    :type level: int
    :return:
    """
    if not logging.root.hasHandlers():
        logging.basicConfig(level=level if level is not None else logging.WARNING, format=LOG_FORMAT)
    return logging.getLogger(name)


def get_process_config(cfg: dict | ObjectDict, name: str) -> ObjectDict | None:
    """Extract the configuration for a built-in process

    :param cfg:
    :param name:
    :return:
    """
    try:
        api_uri = None
        for p in cfg.sep.processes:
            if p.get("name") == name:
                scheme = "https" if p.get("secure") else "http"
                api_uri = ObjectDict({"uri": f"{scheme}://{p['host']}:{p['port']}"})
                break
        if api_uri is None:
            raise ValueError("Tasks API URI is not configured")
    except (AttributeError, KeyError, ValueError):
        api_uri = None
    return api_uri


def get_requests_session(request: Union[RequestHandler, Request]) -> requests.Session:
    """Get a requests.Session instance populated from a handler

    :param request:
    :return:
    """
    session = requests.Session()
    for c, v in request.cookies.items():
        # TODO: use settings to determine cookie names
        if c not in ["_xsrf", "fastapi-session", "casdoorUser", "sep"]:
            continue
        val = v.value if isinstance(request, RequestHandler) else v
        if c == "_xsrf":
            session.headers.setdefault("X-Xsrftoken", val)
        session.cookies.set(c, val)
    return session


def get_timestamp() -> datetime:
    """Get the current time in UTC

    :return: the current time in UTC
    :rtype: datetime
    """
    return datetime.now(tz=timezone.utc)


def get_template(template_name: str, template_dirs: list) -> Union[Template, None]:
    """Load and return a template

    :param template_name:
    :param template_dirs:
    :return:
    """
    for template_dir in template_dirs:
        match template_dir.startswith("#resolve#"):
            case True:
                template_dir = os.path.abspath(template_dir.replace("#resolve#", ""))

        match template_dir:
            case "#appdir":
                _dir = os.path.dirname(argv[0])
            case "#appdir+templates":
                _dir = os.path.join(os.path.dirname(argv[0]), "templates")
            case "#appdir..templates":
                _dir = os.path.join(os.path.dirname(argv[0]), "..", "templates")
            case "#appdir....templates":
                _dir = os.path.join(os.path.dirname(argv[0]), "..", "..", "templates")
            case _:
                _dir = template_dir
        loader = Loader(_dir)
        # TODO: review this setting, compacting to a single line for now
        # loader.whitespace = "oneline"
        try:
            return loader.load(template_name)
        except FileNotFoundError:
            pass
    return None


def render_template(template: Template, **kwargs):
    """Render a template

    :param template:
    :param kwargs:
    :raises tornado.web.HTTPError: when the template is unusable
    :return:
    """
    if template is None:
        raise HTTPError(status_code=HTTPStatus.NOT_FOUND)
    return template.generate(**kwargs)


class Timer:
    """Timer mechanism for refreshing the inventory"""

    _last_refreshed: int = 0
    _refresh_after: int = REFRESH_INTERVAL

    @property
    def last_refresh(self) -> int:
        """Access the last refresh time

        :return: the last refresh
        """
        return self._last_refreshed

    @property
    def refresh_after(self) -> int:
        """Access the refresh interval

        :return: the number of seconds to refresh the inventory
        """
        return self._refresh_after

    @refresh_after.setter
    def refresh_after(self, interval: int) -> None:
        """Set the refresh interval

        :param interval:
        :return:
        """
        if isinstance(interval, int):
            self._refresh_after = interval

    def needs_refresh(self) -> bool:
        """Check if a refresh is required

        :return: True if refresh is required
        """
        return self._last_refreshed == 0 or self._last_refreshed + self._refresh_after < time()

    def update(self) -> None:
        """Update the last_refreshed value

        :return:
        """
        self._last_refreshed = int(time())
