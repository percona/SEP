"""Define dependencies for the Archives plugin."""

import logging
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import Depends, Form

from app.inventory.models import ServiceTypeEnum
from app.sep.deps import (
    DefaultContext,
    ExecutorHosts,
    get_created_entity,
    get_task_by_name,
    get_tasks_context,
    InventoryAPI,
    TaskAPI,
)
from app.sep.models import SyncInventoryEntityTypeEnum
from app.sep.plugins.archives.models import (
    ArchivesCreate,
    PurgeConfig,
    PurgeConfigAll,
)
from app.tasks.models import (
    Task,
    TaskBackendEnum,
    TaskOwner,
    TaskWrite,
)

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

    purge_item_data = {
        **form.model_dump(
            include={
                "alias",
                "source_query",
                "where",
                "swap_drop",
                "swp_table_suffix",
                "use_index",
                "extra_args",
                "limit",
                "sleep",
                "disable_binlog",
                "delete_data",
            },
            by_alias=True,
        ),
    }

    if form.source_db_id is not None:
        schema = await get_created_entity(
            inventory_api,
            SyncInventoryEntityTypeEnum.SCHEMA,
            form.source_db_id,
            service_id=service.id,
        )
        purge_item_data["source_db"] = schema.name

    if form.source_table_id is not None:
        source_table = await get_created_entity(
            inventory_api,
            SyncInventoryEntityTypeEnum.TABLE,
            form.source_table_id,
            schema_id=schema.id,
        )
        purge_item_data["source_table"] = source_table.name

    if form.dest_table_id is not None:
        dest_table = await get_created_entity(
            inventory_api,
            SyncInventoryEntityTypeEnum.TABLE,
            form.dest_table_id,
            schema_id=schema.id,
        )
        purge_item_data["dest_table"] = dest_table.name
    elif form.dest_file is not None:
        purge_item_data["dest_file"] = form.dest_file

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
        owner=TaskOwner.ARCHIVER,
        data={
            "task": "run-python",
            "meta": {
                "config": yaml.dump(
                    purge_config.model_dump(by_alias=True, exclude_none=True)
                ),
                "target": form.hostname,
                "requirements": "PyMySQL[rsa,ed25519]\nfilelock\nPyYAML",
            },
            "payload": f"file://{payload_path}",
        },
        alert_on_fail=form.alert_on_fail,
    )


ArchivesGeneratedTask = Annotated[TaskWrite, Depends(build_archives_task_payload)]


async def get_archives_task(
    task_name: str,
    tasks_api: TaskAPI,
) -> Task:
    """Fetch and validate a task for the Archives plugin.

    This function retrieves a task by its name from the Tasks API and validates
    that it is owned by the Archives plugin. If the task does not exist or is not
    owned by Archives, it raises a 404 HTTP exception.

    :param task_name: The name of the task to retrieve.
    :type task_name: str
    :param tasks_api: The TaskAPI instance used to make requests to the task service.
    :type tasks_api: TaskAPI
    :return: The retrieved task.
    :rtype: Task
    :raises HTTPNotFoundException: If the task is not found or is not owned by Archiver.
    """
    return await get_task_by_name(tasks_api, task_name, TaskOwner.ARCHIVER)


ArchivesTask = Annotated[Task, Depends(get_archives_task)]


def get_archives_task_info(task: dict[str, Any]) -> dict[str, Any]:
    """Extract relevant information from a task for the Archives plugin.

    Processes the task data to extract hostname and tables information.

    :param task: The task data retrieved from the Tasks API.
    :type task: dict[str, Any]
    :return: A dictionary containing hostname and tables information.
    :rtype: dict[str, Any]
    """
    data = task["data"]
    meta = data["meta"]
    task_config = yaml.safe_load(meta["config"])
    purge_item = task_config["PURGE_LIST"][0]

    source_db = purge_item.get("SOURCE_DB")
    source_table = purge_item.get("SOURCE_TABLE")
    dest_table = purge_item.get("DEST_TABLE")
    source_query = purge_item.get("SOURCE_QUERY")
    dest_file = purge_item.get("DEST_FILE")

    result = {
        "hostname": meta["target"],
        "created_by": task.get("created_by"),
        "last_updated_by": task.get("last_updated_by"),
    }

    if source_db and source_table:
        result["source_table"] = f"{source_db}.{source_table}"
    if source_db and dest_table:
        result["dest_table"] = f"{source_db}.{dest_table}"
    if source_query:
        result["source_query"] = source_query
    if dest_file:
        result["dest_file"] = dest_file

    return result


async def get_archives_index_context(
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    context: DefaultContext,
    executor_hosts: ExecutorHosts,
) -> dict[str, Any]:
    """Assemble the context for the Archives plugin index view.

    Retrieves MySQL services and associated tasks, organizing them based on their
    execution status. Integrates this information into the default context for
    rendering in templates.

    :param inventory_api: The Inventory API client for fetching service and schema data.
    :type inventory_api: InventoryAPI
    :param tasks_api: The TaskAPI client for fetching task data.
    :type tasks_api: TaskAPI
    :param context: The default context to be updated with Archives-specific information.
    :type context: DefaultContext
    :param executor_hosts: The executor hosts for the Archives tasks.
    :type executor_hosts: ExecutorHosts
    :return: An updated context dictionary containing Archives-related data.
    :rtype: dict[str, Any]
    """
    return await get_tasks_context(
        inventory_api,
        tasks_api,
        get_archives_task_info,
        executor_hosts,
        context,
        TaskOwner.ARCHIVER,
        alert_on_fail_default=True,
    )
