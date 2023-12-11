"""
Entrypoint for module
"""
import asyncio

from tornado.options import (
    define,
    options,
    parse_command_line,
)
import uvicorn

define("tasks-address", default="127.0.0.1", help="Tasks API address", type=str)
define("tasks-port", default=8182, help="Tasks API port", type=int)


if __name__ == "__main__":
    try:
        parse_command_line()
        uvicorn.run(
            "sep.tasks.api:app",
            log_level=options.logging,
            reload=False,
            **{"host": options.tasks_address, "port": options.tasks_port},
        )
    except (KeyboardInterrupt, asyncio.exceptions.CancelledError):
        print("Exiting application")
