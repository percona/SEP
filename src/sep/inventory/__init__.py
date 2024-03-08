"""
Inventory
"""

from sep.core import ApiBackendHandler

DEFAULT_BACKEND_ADDRESS = "http://127.0.0.1:8184"


class InventoryHandler(ApiBackendHandler):
    """Default handler for Inventory"""

    PATHS = {
        "api": "/inventory/api/",
        "ui": "/inventory/",
    }
