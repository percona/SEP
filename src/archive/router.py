"""
Data archiver routing
"""

from tornado.web import Application
from tornado.util import ObjectDict

from . import ArchiveHandler


def get_default_router(cfg: ObjectDict, handlers_only: bool = False) -> Application | list:
    """Generate the router for data archival

    :param cfg:
    :param handlers_only:
    :return:
    """
    handlers = [
        (
            r"^/archiver/(?P<route>.*)?",
            ArchiveHandler,
            {k: v for k, v in cfg.get("archiver", {}).items() if k not in ["_module"]},
        ),
    ]
    if handlers_only:
        return handlers
    return Application(handlers=handlers)
