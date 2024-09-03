from fastapi import APIRouter

from app.api.deps import IsAuthenticatedDep
from app.inventory.config import inventory_settings
from app.inventory.models import InventoryItem

router = APIRouter()


@router.get("/", dependencies=[IsAuthenticatedDep])
async def list_inventory() -> list[InventoryItem]:
    """List nodes from source's inventory."""
    return await inventory_settings.PMM.get_inventory()
