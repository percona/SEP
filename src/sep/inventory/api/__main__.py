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

define("inventory-address", default="127.0.0.1", help="Inventory API address", type=str)
define("inventory-port", default=8181, help="Inventory API port", type=int)


if __name__ == "__main__":
    try:
        parse_command_line()
        uvicorn.run(
            "sep.inventory.api:app",
            log_level=options.logging,
            reload=False,
            **{"host": options.inventory_address, "port": options.inventory_port},
        )
    except (KeyboardInterrupt, asyncio.exceptions.CancelledError):
        print("Exiting application")
