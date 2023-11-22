"""
Utility library
"""
import logging
import os.path
from sys import modules
from typing import Union

from tornado.template import (
    Loader,
    Template,
)

LOG_FORMAT = "%(asctime)s %(levelname)s:%(name)s: PID<%(process)d> %(module)s.%(funcName)s - %(message)s"


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
        match template_dir:
            case "#filedir":
                _dir = os.path.dirname(__file__)
            case "#filedir+templates":
                _dir = os.path.join(os.path.dirname(__file__), "templates")
            case "#filedir..templates":
                _dir = os.path.join(os.path.dirname(__file__), "..", "templates")
            #case "#moduledir":
            #    _dir = dir(modules[__name__])
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
    :return:
    """
    if template is None:
        return "Page not found"
    return template.generate(**kwargs)
