"""Define dependencies for the Archives plugin."""

import logging
from pathlib import Path
from typing import Annotated

import yaml
from fastapi import Depends, Form, HTTPException

from app.inventory.models import ServiceTypeEnum
from app.sep.deps import get_created_entity, InventoryAPI, TaskAPI
from app.sep.models import SyncInventoryEntityTypeEnum
from app.sep.plugins.archives.models import (
    ArchivesCreate,
    PurgeConfig,
    PurgeConfigAll,
)
from app.tasks.models import TaskBackendEnum, TaskWrite

logger = logging.getLogger(__name__)


async def build_archives_task_payload(
    form: Annotated[ArchivesCreate, Form()],
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build the archive task payload from form.

    Build the payload for an Archives task to be executed, including the
    necessary command arguments for performing archive.

    :param form: The form data for the Archives creation.
    :type form: ArchivesCreate
    :param inventory_api: The Inventory API to get entities from.
    :type inventory_api: InventoryAPI
    :return: A fully constructed `TaskWrite` object containing all the necessary
        configuration to create the Archives task.
    :rtype: TaskWrite
    """
    service = await get_created_entity(
        inventory_api,
        SyncInventoryEntityTypeEnum.SERVICE,
        form.service_id,
        type=ServiceTypeEnum.MYSQL,
    )
    schema = await get_created_entity(
        inventory_api,
        SyncInventoryEntityTypeEnum.SCHEMA,
        form.source_db_id,
        service_id=service.id,
    )
    source_table = await get_created_entity(
        inventory_api,
        SyncInventoryEntityTypeEnum.TABLE,
        form.source_table_id,
        schema_id=schema.id,
    )
    dest_table = await get_created_entity(
        inventory_api,
        SyncInventoryEntityTypeEnum.TABLE,
        form.dest_table_id,
        schema_id=schema.id,
    )
    purge_item_data = {
        **form.model_dump(include={"alias", "where"}, by_alias=True),
        "source_db": schema.name,
        "source_table": source_table.name,
        "dest_table": dest_table.name,
    }
    purge_config = PurgeConfig(
        all=PurgeConfigAll(
            source_host=service.node.address, source_port=service.port or 3306
        ),
        purge_list=[purge_item_data],
        alias=form.alias,
    )
    payload_path = Path(__file__).parent / "payload"
    return TaskWrite(
        name=form.alias,
        backend=TaskBackendEnum.PROXY,
        owner="archiver",
        data={
            "task": "run-python",
            "meta": {
                "config": yaml.dump(purge_config.model_dump(by_alias=True)),
                "target": form.hostname,
                "requirements": "PyMySQL\nfilelock\nPyYAML",
            },
            "payload": f"file://{payload_path}",
        },
    )


ArchivesGeneratedTask = Annotated[TaskWrite, Depends(build_archives_task_payload)]


async def get_archives_task(
    task_name: str,
    tasks_api: TaskAPI,
) -> dict:  # TODO: refactor - (ab)use pydantic models  # noqa: TD002, TD003
    """Fetch and validate a task for the Archives plugin.

    This function retrieves a task by its name from the Tasks API and validates
    that it is owned by the Archives plugin. If the task does not exist or is not
    owned by Archives, it raises a 404 HTTP exception.

    :param task_name: The name of the task to retrieve.
    :type task_name: str
    :param tasks_api: The TaskAPI instance used to make requests to the task service.
    :type tasks_api: TaskAPI
    :return: The task data as a dictionary.
    :rtype: dict[str, Any]
    :raises HTTPException: If the task is not found or is not owned by Archives
        (HTTP status 404).
    """
    task = await tasks_api.get(
        f"/{task_name}",
    )  # TODO: refactor - (ab)use pydantic models  # noqa: TD002, TD003
    if (
        task.get("owner") != "archiver"
    ):  # TODO: Consider getting owner name from plugin MODULE_NAME  # noqa: TD002, TD003
        raise HTTPException(404)
    return task


ArchivesTask = Annotated[dict, Depends(get_archives_task)]
