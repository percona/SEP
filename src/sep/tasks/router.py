"""
Task routing
"""

from tornado.web import Application
from tornado.util import ObjectDict

from sep.core import RemoteCallHandler
from sep.core.utils import get_process_config

from . import (
    DEFAULT_BACKEND_ADDRESS,
    TaskHandler,
)
from .nomad import NomadRemoteCallHandler


def get_default_router(cfg: ObjectDict, handlers_only: bool = False) -> Application | list:
    """Generate the router for tasks

    :return: router
    """
    try:
        nomad_uri = cfg.nomad.api
    except (AttributeError, KeyError):
        nomad_uri = {"uri": "http://127.0.0.1:4646"}

    try:
        api_uri = get_process_config(cfg, "tasks")
        if api_uri is None:
            raise ValueError("Tasks API URI is not configured")
    except (AttributeError, KeyError, ValueError):
        api_uri = {"uri": DEFAULT_BACKEND_ADDRESS}

    handlers = [
        (rf"^{TaskHandler.PATHS['ui']}(?P<route>(?!api|nomad).*)?$", TaskHandler, {}),
        (rf"^{TaskHandler.PATHS['api']}(?P<route>.*)?$", RemoteCallHandler, api_uri),
        (
            rf"^{TaskHandler.PATHS['ui']}{NomadRemoteCallHandler.PATHS['base']}(?P<route>.+)$",
            NomadRemoteCallHandler,
            nomad_uri,
        ),
    ]
    if handlers_only:
        return handlers
    return Application(handlers=handlers)
