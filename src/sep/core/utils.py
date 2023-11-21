"""
Utility library
"""
import logging

LOG_FORMAT = '%(asctime)s %(levelname)s:%(name)s: PID<%(process)d> %(module)s.%(funcName)s - %(message)s'


def get_logger(name: str, level: int = logging.WARNING) -> logging.Logger:
    """Get a logger instance

    :param name: name of the logger
    :type name: str
    :param level: logging level as per logging.getLevelNamesMapping().values()
    :type level: int
    :return:
    """
    if not logging.root.hasHandlers():
        logging.basicConfig(level=level if level is not None else logging.WARNING,
                            format=LOG_FORMAT)
    return logging.getLogger(name)
