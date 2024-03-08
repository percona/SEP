"""
Inventory routing
"""

from tornado.web import Application
from tornado.util import ObjectDict

from sep.core import RemoteCallHandler
from sep.core.utils import get_process_config

from . import (
    DEFAULT_BACKEND_ADDRESS,
    InventoryHandler,
)


def get_default_router(cfg: ObjectDict, handlers_only: bool = False) -> Application | list:
    """Generate the router for inventory

    :param cfg:
    :param handlers_only:
    :return:
    """
    try:
        api_uri = get_process_config(cfg, "inventory")
        if api_uri is None:
            raise ValueError("Tasks API URI is not configured")
    except (AttributeError, KeyError, ValueError):
        api_uri = {"uri": DEFAULT_BACKEND_ADDRESS}

    handlers = [
        (rf"{InventoryHandler.PATHS['ui']}(?P<route>(?!api).*)?", InventoryHandler, {}),
        (rf"{InventoryHandler.PATHS['api']}(?P<route>.*)?", RemoteCallHandler, api_uri),
    ]
    if handlers_only:
        return handlers
    return Application(handlers=handlers)
