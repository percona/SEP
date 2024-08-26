"""Define Inventory routes."""

import logging

from fastapi import FastAPI

from app.api.deps import CurrentUser
from app.inventory.config import inventory_settings
from app.inventory.models import InventoryItem

logger = logging.getLogger(__name__)

inventory_app = FastAPI()


@inventory_app.get("/")
async def list_inventory(user: CurrentUser) -> list[InventoryItem]:
    """List nodes from source's inventory."""
    return await inventory_settings.PMM.get_inventory()
