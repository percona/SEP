"""Define dependencies for the Restores plugin."""

from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import Depends, Form
from fastapi.encoders import jsonable_encoder

from app.core.utils.pydantic import extract_model_from_instance
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
from app.sep.plugins.backup_mongo.models import BackupType
from app.sep.plugins.backup_mongo.restore.models import (
    BaseRestoreConfigServer,
    RestoreConfig,
    RestoreConfigAll,
    RestoreConfigRestore,
    RestoreConfigServer,
    RestoreCreate,
)
from app.tasks.models import Task, TaskBackendEnum, TaskOwner, TaskWrite


def _update_restore_config_from_service(
    restore_config_payload: dict[str, Any],
    service_address: str,
) -> None:
    """Update restore config payload with service address information."""
    if isinstance(service_address, str) and ":" in service_address:
        host, port_str = service_address.split(":", 1)
        restore_config_payload["dest_host"] = host.strip()
        restore_config_payload["dest_port"] = int(port_str.strip())


def _parse_mongod_location_map(location_map_str: str) -> dict[str, Any] | None:
    """Parse mongod location map from YAML string."""
    try:
        mongod_location_map = yaml.safe_load(location_map_str)
        if isinstance(mongod_location_map, dict):
            return mongod_location_map
    except yaml.YAMLError:
        pass  # Ignore invalid YAML
    return None


def _build_restore_config_dict(form: RestoreCreate) -> dict[str, Any]:
    """Build restore configuration dictionary from form data."""
    field_mapping = {
        "batchSize": form.restore_batch_size,
        "numInsertionWorkers": form.restore_num_insertion_workers,
        "numParallelCollections": form.restore_num_parallel_collections,
        "numDownloadWorkers": form.restore_num_download_workers,
        "maxDownloadBufferMb": form.restore_max_download_buffer_mb,
        "downloadChunkMb": form.restore_download_chunk_mb,
    }
    restore_config_dict = {
        key: value for key, value in field_mapping.items() if value is not None
    }
    if form.restore_mongod_location:
        restore_config_dict["mongodLocation"] = form.restore_mongod_location
    if form.restore_mongod_location_map:
        location_map = _parse_mongod_location_map(form.restore_mongod_location_map)
        if location_map is not None:
            restore_config_dict["mongodLocationMap"] = location_map
    return restore_config_dict


async def build_restore_config_task_payload(
    form: Annotated[RestoreCreate, Form()],
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build task payload for restore config operation."""
    all_config_dict = extract_model_from_instance(form, RestoreConfigAll)
    base_config_dict = extract_model_from_instance(form, BaseRestoreConfigServer)

    restore_config_payload: dict[str, Any] = {
        **base_config_dict.model_dump(),
        "alias": form.task_name,
    }

    # Get service information if service_id is provided
    if form.service_id:
        service = await get_created_entity(
            inventory_api,
            SyncInventoryEntityTypeEnum.SERVICE,
            form.service_id,
            type=ServiceTypeEnum.MONGODB,
        )
        _update_restore_config_from_service(restore_config_payload, service.address)

    # Build restore configuration
    restore_config_dict = _build_restore_config_dict(form)

    restore_config = RestoreConfig(
        all_servers=RestoreConfigAll.model_validate(all_config_dict),
        restore=RestoreConfigRestore.model_validate(restore_config_dict)
        if restore_config_dict
        else None,
        server_list=[RestoreConfigServer.model_validate(restore_config_payload)],
    )

    requirements = "packaging\nPyYAML"
    payload_path = Path(__file__).parent / "pbm_restore_config_payload"

    return TaskWrite(
        name=form.task_name,
        backend=TaskBackendEnum.PROXY,
        owner=TaskOwner.RESTORE_MONGO,
        data={
            "task": "run-python",
            "meta": {
                "config": yaml.dump(
                    jsonable_encoder(restore_config, by_alias=True, exclude_none=True)
                ),
                "target": form.hostname,
                "requirements": requirements,
            },
            "payload": f"file://{payload_path}",
        },
    )


async def build_restore_task_payload(
    form: Annotated[RestoreCreate, Form()],
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build task payload for a restore operation."""
    all_config_dict = extract_model_from_instance(form, RestoreConfigAll)
    base_config_dict = extract_model_from_instance(form, BaseRestoreConfigServer)

    restore_config_payload: dict[str, Any] = {
        **base_config_dict.model_dump(),
        "alias": form.task_name,
    }

    # Get service information if service_id is provided
    if form.service_id:
        service = await get_created_entity(
            inventory_api,
            SyncInventoryEntityTypeEnum.SERVICE,
            form.service_id,
            type=ServiceTypeEnum.MONGODB,
        )
        _update_restore_config_from_service(restore_config_payload, service.address)

    restore_config = RestoreConfig(
        all_servers=RestoreConfigAll.model_validate(all_config_dict),
        restore=None,  # Restore options are already synced in config task
        server_list=[RestoreConfigServer.model_validate(restore_config_payload)],
    )

    backup_type_to_payload = {
        BackupType.PBM_LOGICAL: "pbm_logical_restore_payload",
        BackupType.PBM_PHYSICAL: "pbm_physical_restore_payload",
    }

    payload_name = backup_type_to_payload.get(form.backup_type)
    if not payload_name:
        raise ValueError(f"Invalid Backup Type {form.backup_type} for restore")

    requirements = "packaging\nPyYAML"

    payload_path = Path(__file__).parent / payload_name

    return TaskWrite(
        name=f"{form.task_name}-{form.backup_type}",
        backend=TaskBackendEnum.PROXY,
        owner=TaskOwner.RESTORE_MONGO,
        data={
            "task": "run-python",
            "meta": {
                "config": yaml.dump(
                    jsonable_encoder(restore_config, by_alias=True, exclude_none=True)
                ),
                "target": form.hostname,
                "requirements": requirements,
            },
            "payload": f"file://{payload_path}",
            "parent": form.task_name,
        },
    )


def _parse_restore_config_options(restore_config: dict[str, Any]) -> dict[str, Any]:
    """Parse restore configuration options from task data."""
    result = {}
    if "batchSize" in restore_config:
        result["restore_batch_size"] = restore_config["batchSize"]
    if "numInsertionWorkers" in restore_config:
        result["restore_num_insertion_workers"] = restore_config["numInsertionWorkers"]
    if "numParallelCollections" in restore_config:
        result["restore_num_parallel_collections"] = restore_config[
            "numParallelCollections"
        ]
    if "numDownloadWorkers" in restore_config:
        result["restore_num_download_workers"] = restore_config["numDownloadWorkers"]
    if "maxDownloadBufferMb" in restore_config:
        result["restore_max_download_buffer_mb"] = restore_config["maxDownloadBufferMb"]
    if "downloadChunkMb" in restore_config:
        result["restore_download_chunk_mb"] = restore_config["downloadChunkMb"]
    if "mongodLocation" in restore_config:
        result["restore_mongod_location"] = restore_config["mongodLocation"]
    if "mongodLocationMap" in restore_config:
        result["restore_mongod_location_map"] = yaml.dump(
            restore_config["mongodLocationMap"]
        )
    return result


def parse_restore_task_data(task: dict[str, Any]) -> dict[str, Any]:
    """Parse restore task data for editing.

    Extracts configuration from an existing restore task to populate the edit form.

    :param task: The task data retrieved from the Tasks API.
    :type task: dict[str, Any]
    :return: A dictionary containing parsed restore configuration.
    :rtype: dict[str, Any]
    """
    data = task["data"]
    meta = data["meta"]
    task_config = yaml.safe_load(meta["config"])
    server_config = task_config["SERVER_LIST"][0]
    all_servers_config = task_config.get("ALL_SERVERS", {})
    restore_config = task_config.get("RESTORE", {})

    result = {
        "name": task["name"],
        "hostname": meta["target"],
        "backup_type": server_config["BACKUP_TYPE"],
        "service_id": None,
        "host": server_config.get("DEST_HOST"),
        "port": server_config.get("DEST_PORT") or 27017,
        "backup_source": server_config.get("BACKUP_SOURCE"),
    }

    # Add restore options
    if restore_config:
        result.update(_parse_restore_config_options(restore_config))

    for config in [server_config, all_servers_config]:
        result.update(
            {k.lower(): v for k, v in config.items() if k.lower() not in result}
        )

    return result


async def build_restore_tasks(
    form: Annotated[RestoreCreate, Form()],
    inventory_api: InventoryAPI,
) -> tuple[TaskWrite, TaskWrite]:
    """Build both restore config and restore task payloads."""
    config_task = await build_restore_config_task_payload(form, inventory_api)
    restore_task = await build_restore_task_payload(form, inventory_api)
    return config_task, restore_task


RestoreTasks = Annotated[tuple[TaskWrite, TaskWrite], Depends(build_restore_tasks)]
RestoreGeneratedTask = Annotated[TaskWrite, Depends(build_restore_task_payload)]


async def get_restores_task(
    task_name: str,
    tasks_api: TaskAPI,
) -> Task:
    """Fetch and validate a task for the Restores plugin.

    This function retrieves a task by its name from the Tasks API and validates
    that it is owned by the Restores plugin. If the task does not exist or is not
    owned by Restores, it raises a 404 HTTP exception.

    :param task_name: The name of the task to retrieve.
    :type task_name: str
    :param tasks_api: The TaskAPI instance used to make requests to the task service.
    :type tasks_api: TaskAPI
    :return: The retrieved task.
    :rtype: Task
    :raises HTTPNotFoundException: If the task is not found or is not owned by Restores.
    """
    return await get_task_by_name(tasks_api, task_name, TaskOwner.RESTORE_MONGO)


RestoresTask = Annotated[Task, Depends(get_restores_task)]


def get_restores_task_info(task: dict[str, Any]) -> dict[str, Any]:
    """Extract relevant information from a task for the Restores plugin.

    Processes the task data to extract hostname and backup information.

    :param task: The task data retrieved from the Tasks API.
    :type task: dict[str, Any]
    :return: A dictionary containing hostname and backup information.
    :rtype: dict[str, Any]
    """
    data = task["data"]
    meta = data["meta"]
    task_config = yaml.safe_load(meta["config"])
    restore_server = task_config["SERVER_LIST"][0]

    return {
        "config": task_config,
        "parent": data.get("parent"),
        "target": meta["target"],
        "hostname": meta["target"],
        "host": restore_server.get("DEST_HOST"),
        "port": restore_server.get("DEST_PORT") or 27017,
        "backup_type": BackupType(restore_server.get("BACKUP_TYPE")).name,
        "created_at": task.get("created_at"),
        "created_by": task.get("created_by"),
        "last_updated_by": task.get("last_updated_by"),
    }


async def get_restores_index_context(
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    context: DefaultContext,
    executor_hosts: ExecutorHosts,
) -> dict[str, Any]:
    """Assemble the context for the Restores plugin index view.

    Retrieves MongoDB services and associated tasks, organizing them based on their
    execution status. Integrates this information into the default context for
    rendering in templates.

    :param inventory_api: The Inventory API client for fetching service and schema data.
    :type inventory_api: InventoryAPI
    :param tasks_api: The TaskAPI client for fetching task data.
    :type tasks_api: TaskAPI
    :param context: The default context to be updated with Restores-specific information.
    :type context: DefaultContext
    :param executor_hosts: The executor hosts for the Restore tasks.
    :type executor_hosts: ExecutorHosts
    :return: An updated context dictionary containing Restores-related data.
    :rtype: dict[str, Any]
    """
    return await get_tasks_context(
        inventory_api,
        tasks_api,
        get_restores_task_info,
        executor_hosts,
        context,
        TaskOwner.RESTORE_MONGO,
    )
