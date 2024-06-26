"""
MySQL Backups routing
"""

from tornado.web import Application
from tornado.util import ObjectDict

from . import MysqlBackupsHandler


def get_default_router(cfg: ObjectDict, handlers_only: bool = False) -> Application | list:
    """Generate the router for mysql backups
    :param cfg:
    :param handlers_only:
    :return:
    """
    handlers = [
        (
            r"^/mysql_backups/(?P<route>.*)?",
            MysqlBackupsHandler,
            {k: v for k, v in cfg.get("mysql_backups", {}).items() if k not in ["_module"]},
        ),
    ]
    if handlers_only:
        return handlers
    return Application(handlers=handlers)
