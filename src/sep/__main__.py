"""
SEP entrypoint
"""

from argparse import (
    ArgumentDefaultsHelpFormatter,
    ArgumentParser,
    FileType,
)
import asyncio
import logging

import uvloop

from . import main


if __name__ == "__main__":
    parser = ArgumentParser(formatter_class=ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        "--config", type=FileType("rb"), default="config.json", help="Configuration file in either JSON, or YAML format"
    )
    parser.add_argument(
        "--log-level",
        default="WARN",
        choices=tuple(logging.getLevelNamesMapping().keys()),
        help="Set the log verbosity",
    )
    try:
        uvloop.run(main(**vars(parser.parse_args())))
    except (KeyboardInterrupt, asyncio.exceptions.CancelledError):
        print("Exiting application")
