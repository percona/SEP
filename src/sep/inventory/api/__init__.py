"""
Inventory API
"""

import logging
from os import getenv
from secrets import token_hex
from typing import (
    List,
)

from fastapi import (
    BackgroundTasks,
    FastAPI,
    Request,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import (
    event,
    null,
)
from sqlalchemy.engine import Engine
from starlette.middleware.sessions import SessionMiddleware

from .models import (
    inventory,
    InventoryItem,
    InventoryItemBaseModel,
    InventoryItemData,
    InventoryItemService,
    INVENTORY_BACKEND_MAP,
    INVENTORY_CREDENTIAL_SOURCE_MAP,
)
from .pmm import InventorySource
from sep.authz.casdoor import SESSION_TOKEN_LENGTH
import sep.core.db
from sep.core.models import Widget
from sep.core.utils import (
    get_logger,
    Timer,
)

DEFAULT_DATABASE_DSN = f"{sep.core.db.DEFAULT_DATABASE_DSN}/inventory.db"
DEFAULT_ORIGINS = "http://localhost:8000,http://127.0.0.1:8000"

DATABASE_URL = getenv("INVENTORY_DATABASE_URL", DEFAULT_DATABASE_DSN)
ORIGINS = getenv("INVENTORY_ORIGINS", DEFAULT_ORIGINS).split(",")

database = sep.core.db.get_database(DATABASE_URL)

app = FastAPI()
app.log = get_logger("inventory-api", level=logging.DEBUG)
app.log.debug("dialect._json_serializer: %r", database.engine.dialect._json_serializer)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    SessionMiddleware,
    secret_key=token_hex(SESSION_TOKEN_LENGTH),
    session_cookie="fastapi-session",
)

timer = Timer()


async def lookup_inventory(source: str = "pmm"):
    """Lookup the inventory from a remote source

    :param source:
    :return:
    """
    app.log.debug("Checking remote source")
    inventory_source = None
    match source:
        case "pmm":
            # TODO: set address from config
            inventory_source = InventorySource(uri="https://localhost:8443", verify_tls=False)
        case "_":
            raise NotImplementedError(f"{source} is not supported")
    # TODO: this needs to be more intelligent for updates
    for _, node in inventory_source.nodes.items():
        app.log.debug("Checking for node %s", node.name)
        exists = await database.fetch_all(inventory.select().where(inventory.c.node_id == node.id))

        services = []
        for svc in node.services:
            services.append(InventoryItemService(**svc.to_dict()))
        item_data = InventoryItemData(name=node.name, services=services)
        model = InventoryItemBaseModel(
            name=node.name,
            node_id=node.id,
            data=item_data,
            backend=INVENTORY_BACKEND_MAP["pmm"],
            credential_source=INVENTORY_CREDENTIAL_SOURCE_MAP["default"],
        )
        if not exists:
            await create_item(model)
        else:
            item_id = exists[0][0]
            await update_item(item_id, model)
    timer.update()


async def select_active_inventory():
    query = inventory.select().where(inventory.c.deleted_at == null())
    return await database.fetch_all(query)


@app.on_event("startup")
async def startup():
    """Prepare the database and application"""
    inventory.to_metadata(database.metadata)
    await sep.core.db.startup(database)


@app.on_event("shutdown")
async def shutdown():
    """Perform a clean shutdown"""
    await database.disconnect()


@event.listens_for(Engine, "connect")
def prepare_connection(connection, record):
    """Prepare the connection"""
    sep.core.db.prepare_connection(connection, record)


@app.get(path="/", response_model=List[InventoryItem])
async def list_inventory(background_tasks: BackgroundTasks):
    """List the inventory content

    :return:
    """
    app.log.debug("Listing inventory")
    results = await select_active_inventory()
    if not results or timer.needs_refresh():
        background_tasks.add_task(lookup_inventory, "pmm")
    return results


@app.get(path="/refresh", response_class=JSONResponse)
async def refresh_inventory(background_tasks: BackgroundTasks):
    """Refresh the inventory content

    :return:
    """
    app.log.debug("Refreshing the inventory")
    background_tasks.add_task(lookup_inventory, "pmm")
    return {"status": "success"}


@app.get(path="/widget", response_model=Widget)
async def get_widget(request: Request):
    """Generate data used in widgets

    :param request:
    :return:
    """
    if request.query_params:
        # TODO
        pass
    data = {}
    for node in [x.data for x in await select_active_inventory()]:
        data.setdefault("summary", {})
        data.setdefault("total_nodes", 0)
        data.setdefault("total_nodes_without_services", 0)
        data.setdefault("total_services", 0)
        data["total_nodes"] += 1
        has_service = False
        for service in node["services"]:
            if not service["type"]:
                continue
            data["summary"].setdefault(f"{service['type']}", 0)
            data["summary"][f"{service['type']}"] += 1
            data["total_services"] += 1
            has_service = True
        if not has_service:
            data["total_nodes_without_services"] += 1
    return Widget(heading="Inventory", data=data, layout="grid").model_dump()


@app.post(path="/", response_model=InventoryItem)
async def create_item(item: InventoryItemBaseModel):
    """

    :param item:
    :return:
    """
    last_record_id = await database.execute(inventory.insert().values(**item.model_dump()))
    return {**item.model_dump(), "id": last_record_id}


@app.put(path="/{item_id}", response_model=InventoryItem)
async def update_item(item_id: int, item: InventoryItemBaseModel):
    """

    :param item_id:
    :param item:
    :return:
    """
    await database.execute(inventory.update().where(inventory.c.id == item_id).values(**item.model_dump()))
    return {**item.model_dump(), "id": item_id}
