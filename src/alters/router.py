"""
Schema change routing
"""

from tornado.web import Application
from tornado.util import ObjectDict

from . import AlterHandler


def get_default_router(cfg: ObjectDict, handlers_only: bool = False) -> Application | list:
    """Generate the router for schema changes

    :param cfg:
    :param handlers_only:
    :return:
    """
    handlers = [
        (
            r"^/alters/(?P<route>.*)?",
            AlterHandler,
            {k: v for k, v in cfg.get("alters", {}).items() if k not in ["_module"]},
        )
    ]
    if handlers_only:
        return handlers
    return Application(handlers=handlers)
