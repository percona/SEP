"""
Default routing
"""

import asyncio.exceptions
import importlib
from os import path
import pathlib

from tornado.log import app_log
from tornado.web import (
    Application,
    StaticFileHandler,
)
from tornado.util import ObjectDict

from . import (
    AuthZHandler,
    HomepageHandler,
    DummyHandler,
)


def get_default_router(cfg: ObjectDict, handlers_only: bool = False) -> Application | list:
    """Generate the router for SEP

    TODO: Built-in rules, here temporarily
    With a registry, which in its simplest form could just be "modules" in the JSON config,
    we could look up what should be enabled and go off to each to retrieve its handlers. This would
    allow the app/handler/registry to be the source of the configuration. Perhaps this could even remove
    the need to populate the handlers and instead get used to configure an intelligent router

    :param cfg:
    :param handlers_only:
    :return:
    """
    handlers = [
        (r"^/$", HomepageHandler, {}),
        (r"^/api/(?P<route>signin|signout)$", AuthZHandler, {}),
        (r"^/static/(.*)", StaticFileHandler, {"path": get_static_path(cfg)}),
    ]
    app_log.debug("Default SEP handlers: %r", handlers)
    if handlers_only:
        return handlers
    return Application(handlers=handlers)


def get_module_routers(cfg: ObjectDict, handlers_only: bool = False) -> Application | list:
    """Search for module routers

    TODO: Built-in rules, here temporarily
    With a registry, which in its simplest form could just be "modules" in the JSON config,
    we could look up what should be enabled and go off to each to retrieve its handlers. This would
    allow the app/handler/registry to be the source of the configuration. Perhaps this could even remove
    the need to populate the handlers and instead get used to configure an intelligent router

    :param cfg:
    :param handlers_only:
    :return:
    """
    handlers = []
    for module, module_cfg in cfg.items():
        try:
            router = importlib.import_module(f"{module_cfg.get('_module') or module}.router")
            for default_handler in router.get_default_router(cfg=cfg, handlers_only=True):
                handlers.append(default_handler)
                app_log.debug("Auto-loaded handler for module %s", module)
        except (AttributeError, ModuleNotFoundError) as err:
            app_log.warning("Failed to auto-load handler for module %s", module)
    if handlers_only:
        return handlers
    return Application(handlers=handlers)


def get_static_path(cfg: ObjectDict) -> str:
    """Determine the static path

    :param cfg:
    :return:
    """
    source_dir = path.abspath(path.join(__file__, "..", "..", ".."))
    app_log.debug("Source dir defined as %s", source_dir)
    if "static_path" in cfg.sep and cfg.sep.static_path is not None:
        static_path = pathlib.Path(cfg.sep.static_path)
        if not static_path.exists():
            raise asyncio.exceptions.CancelledError(f"Cannot find static_path {static_path}")
    else:
        static_path = path.abspath(path.join(source_dir, "static"))
    app_log.debug("Static path defined as %s", static_path)
    return static_path
