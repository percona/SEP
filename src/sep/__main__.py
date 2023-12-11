"""
SEP entrypoint
"""

import asyncio

from tornado.options import (
    define,
    options,
    parse_command_line,
)
import uvloop

from . import main

define("config", default="config.json", help="Path to the config file; supports JSON, YAML and Python")


if __name__ == "__main__":
    asyncio.set_event_loop(uvloop.new_event_loop())
    with asyncio.Runner() as runner:
        try:
            parse_command_line(final=False)
            runner.run(main(**options.__dict__["_options"]))
        except (KeyboardInterrupt, asyncio.exceptions.CancelledError):
            print("Exiting application")
