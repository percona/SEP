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

from tornado.template import (
    Loader,
    Template,
)
from tornado.web import HTTPError

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
