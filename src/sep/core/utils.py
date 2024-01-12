"""
Utility library
"""
import asyncio
from concurrent.futures import ProcessPoolExecutor
from http import HTTPStatus
import logging
import os.path
from sys import argv
from typing import (
    Callable,
    Union,
)

from fastapi import Request
import requests
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
