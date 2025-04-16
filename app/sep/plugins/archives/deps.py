"""Define dependencies for the Archives plugin."""

import asyncio
import logging
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import Depends, Form

from app.inventory.models import ServiceTypeEnum
from app.sep.deps import (
    DefaultContext,
    get_created_entity,
    get_task_by_name,
    get_tasks_context,
    InventoryAPI,
    TaskAPI,
)
from app.sep.models import SyncInventoryEntityTypeEnum
from app.sep.plugins.archives.models import (
    ArchivesCreate,
    ArchivesUpdate,
    PurgeConfig,
    PurgeConfigAll,
    PurgeConfigItem,
)
from app.tasks.models import (
    Task,
    TaskBackendEnum,
    TaskHistoryStatusEnum,
    TaskOwner,
    TaskWrite,
)

logger = logging.getLogger(__name__)


def build_task_write(
    task_name: str, target: str, purge_config: PurgeConfig
) -> TaskWrite:
    """Build the task write object for the Archives plugin.

    :param task_name: The name of the task to be created.
    :type task_name: str
    :param target: The target host for the task.
    :type target: str
    :param purge_config: The configuration for the purge operation.
    :type purge_config: PurgeConfig
    :return: A `TaskWrite` object containing the task configuration.
    :rtype: TaskWrite
    """
    payload_path = Path(__file__).parent / "payload"
    return TaskWrite(
        name=task_name,
        backend=TaskBackendEnum.PROXY,
        owner=TaskOwner.ARCHIVER,
        data={
            "task": "run-python",
            "meta": {
                "config": yaml.dump(
                    purge_config.model_dump(by_alias=True, exclude_none=True)
                ),
                "target": target,
                "requirements": "PyMySQL\nfilelock\nPyYAML",
            },
            "payload": f"file://{payload_path}",
        },
    )


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
        purge_list=[PurgeConfigItem.model_validate(purge_item_data)],
    )
    return build_task_write(form.alias, form.hostname, purge_config)


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


async def build_archives_updated_task_payload(
    task: ArchivesTask,
    form: Annotated[ArchivesUpdate, Form()],
) -> TaskWrite:
    """Build the archive task payload from form.

    Build the payload for an Archives task to be executed, including the
    necessary command arguments for performing archive.

    :param task: The ArchivesTask instance resolved by the task name.
    :type task: ArchivesTask
    :param form: The form data for the Archives creation.
    :type form: ArchivesCreate
    :return: A fully constructed `TaskWrite` object containing all the necessary
        configuration to create the Archives task.
    :rtype: TaskWrite
    """
    purge_item_data = {
        **form.model_dump(
            exclude={"hostname"},
            by_alias=True,
        ),
    }
    meta = task.data["meta"]
    task_config = yaml.safe_load(meta["config"])
    task_config["PURGE_LIST"][0].update(purge_item_data)
    purge_config = PurgeConfig.model_validate(task_config)
    return build_task_write(form.alias, form.hostname, purge_config)


ArchivesUpdatedTask = Annotated[TaskWrite, Depends(build_archives_updated_task_payload)]


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

    result = {"hostname": meta["target"]}

    if source_db and source_table:
        result["source"] = f"{source_db}.{source_table}"
    else:
        result["source"] = purge_item.get("SOURCE_QUERY")

    if source_db and dest_table:
        result["dest"] = f"{source_db}.{dest_table}"
    else:
        result["dest"] = purge_item.get("DEST_FILE")

    return result


async def get_archives_index_context(
    inventory_api: InventoryAPI, tasks_api: TaskAPI, context: DefaultContext
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
    :return: An updated context dictionary containing Archives-related data.
    :rtype: dict[str, Any]
    """
    return await get_tasks_context(
        inventory_api, tasks_api, get_archives_task_info, context, TaskOwner.ARCHIVER
    )


async def get_archives_detail_context(
    task: ArchivesTask,
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    context: DefaultContext,
) -> dict[str, Any]:
    """Assemble the context for the Archives detail view.

    This dependency extracts task details, retrieves associated service, schema,
    and table information, and also gathers history and stats data.

    :param task: The ArchivesTask instance resolved by the task name.
    :type task: ArchivesTask
    :param inventory_api: The Inventory API client.
    :type inventory_api: InventoryAPI
    :param tasks_api: The Tasks API client.
    :type tasks_api: TaskAPI
    :param context: The default context dictionary.
    :type context: DefaultContext
    :return: A dictionary containing all data needed for the detail view template.
    :rtype: dict[str, Any]
    """
    meta = task.data["meta"]
    task_config = yaml.safe_load(meta["config"])
    host_data = task_config["ALL"]
    purge_item = task_config["PURGE_LIST"][0]

    task_data = {
        "name": task.name,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "hostname": meta["target"],
        "meta": meta,
        "dest_file": purge_item.get("DEST_FILE"),
    }

    if source_host := host_data.get("SOURCE_HOST"):
        address = source_host
        if source_port := host_data.get("SOURCE_PORT"):
            address += f":{source_port}"
        task_data["db_address"] = address

    source_db = purge_item.get("SOURCE_DB")
    source_table = purge_item.get("SOURCE_TABLE")
    dest_table = purge_item.get("DEST_TABLE")

    if source_db and source_table:
        task_data["source"] = f"{source_db}.{source_table}"
    else:
        task_data["source"] = purge_item.get("SOURCE_QUERY")

    if source_db and dest_table:
        task_data["dest"] = f"{source_db}.{dest_table}"
    else:
        task_data["dest"] = purge_item.get("DEST_FILE")

    archive_data = PurgeConfigItem.model_validate(purge_item)

    mysql_services = await inventory_api.get(
        "/services/", params={"service_type": ServiceTypeEnum.MYSQL}
    )
    schemas_tasks = [
        inventory_api.get(f"/services/{service['id']}/schemas/")
        for service in mysql_services
    ]
    schemas_results = await asyncio.gather(*schemas_tasks)
    for service, schemas in zip(mysql_services, schemas_results, strict=False):
        service["schemas"] = schemas

    history_url = f"/{task.name}/history/"
    history_task = tasks_api.get(history_url)
    running_tasks_task = tasks_api.get(
        history_url, params={"status": TaskHistoryStatusEnum.RUNNING}
    )
    stats_task = tasks_api.get(f"/stats/{task.name}")
    history, running_tasks, stats = await asyncio.gather(
        history_task, running_tasks_task, stats_task
    )
    executor_hosts = await tasks_api.get("/hosts/")
    context.update(
        {
            "executor_hosts": [
                host
                for host in executor_hosts.values()
                if host != task_data["meta"]["target"]
            ],
            "mysql_services": mysql_services,
            "archive_data": archive_data,
            "task": task_data,
            "history": history,
            "running_tasks": running_tasks,
            "stats": stats,
        }
    )
    return context
