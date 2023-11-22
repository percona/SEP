"""
Entrypoint for module
"""

from argparse import (
    ArgumentDefaultsHelpFormatter,
    ArgumentParser,
)
import asyncio
from logging import getLevelNamesMapping
import os.path

import uvicorn


if __name__ == "__main__":
    parser = ArgumentParser(formatter_class=ArgumentDefaultsHelpFormatter)
    parser.add_argument("--ip", dest="host", default="127.0.0.1", help="API address")
    parser.add_argument("--port", type=int, default="8182", help="API port")
    parser.add_argument(
        "--log-level", default="WARNING", choices=tuple(getLevelNamesMapping().keys()), help="Set the log verbosity"
    )
    parser.add_argument("--reload", action="store_true", help="Reload on changes")
    try:
        run_args = parser.parse_args()
        uvicorn.run(
            "report.api:app",
            log_level=run_args.log_level.lower(),
            reload_dirs=[os.path.dirname(__file__)],
            **{k: v for k, v in vars(run_args).items() if k != "log_level"},
        )
    except (KeyboardInterrupt, asyncio.exceptions.CancelledError):
        print("Exiting application")
