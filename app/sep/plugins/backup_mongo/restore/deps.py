"""Define dependencies for the Restores plugin."""

from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import Depends, Form, Request
from fastapi.encoders import jsonable_encoder

from app.core.utils.pydantic import extract_model_from_instance
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
from app.sep.plugins.backup_mongo.models import BackupType
from app.sep.plugins.backup_mongo.restore.models import (
    BaseRestoreConfigServer,
    RestoreConfig,
    RestoreConfigAll,
    RestoreConfigServer,
    RestoreCreate,
)
from app.tasks.models import Task, TaskBackendEnum, TaskOwner, TaskWrite


async def build_restore_task_payload(
    form: Annotated[RestoreCreate, Form()],
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build task payload for a restore operation."""
    all_config_dict = {'backup_name': form.backup_name, 'pitr': form.pitr}
    base_config_dict = extract_model_from_instance(form, BaseRestoreConfigServer)

    service = await get_created_entity(
        inventory_api,
        SyncInventoryEntityTypeEnum.SERVICE,
        form.service_id,
        type=ServiceTypeEnum.MONGODB,
    )

    dest_host, dest_port = "localhost", 27017
    if isinstance(service.address, str) and ":" in service.address:
        host, port_str = service.address.split(":", 1)
        dest_host = host.strip()
        dest_port = int(port_str.strip())

    restore_config_payload = {
        **base_config_dict.model_dump(),
        "dest_host": dest_host,
        "dest_port": dest_port,
        "alias": form.task_name,
    }

    if str(form.schema_id).isdigit() and int(form.schema_id) > 0:
        schema = await get_created_entity(
            inventory_api,
            SyncInventoryEntityTypeEnum.SCHEMA,
            form.schema_id,
            service_id=service.id,
        )
        restore_config_payload["database"] = schema.name

    restore_config = RestoreConfig(
        all_servers=RestoreConfigAll.model_validate(all_config_dict),
        server_list=[RestoreConfigServer.model_validate(restore_config_payload)],
    )

    backup_type_to_payload = {
        BackupType.PBM_PHYSICAL: "pbm_physical_restore_payload",
    }

    payload_name = backup_type_to_payload.get(form.backup_type)
    if not payload_name:
        raise ValueError(f"Invalid Backup Type {form.backup_type}")

    requirements = "packaging\nPyYAML\nPyMySQL[rsa,ed25519]\nboto3"
    if form.backup_type == BackupType.PBM_PHYSICAL:
        requirements += "\nfilelock"

    payload_path = Path(__file__).parent / payload_name

    return TaskWrite(
        name=form.task_name,
        backend=TaskBackendEnum.PROXY,
        owner=TaskOwner.RESTORES,
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
    return await get_task_by_name(tasks_api, task_name, TaskOwner.RESTORES)


RestoresTask = Annotated[Task, Depends(get_restores_task)]


def get_restores_task_info(task: dict[str, Any]) -> dict[str, Any]:
    """Extract relevant information from a task for the Restores plugin.

    Processes the task data to extract hostname and tables information.

    :param task: The task data retrieved from the Tasks API.
    :type task: dict[str, Any]
    :return: A dictionary containing hostname and tables information.
    :rtype: dict[str, Any]
    """
    data = task["data"]
    meta = data["meta"]
    task_config = yaml.safe_load(meta["config"])
    restore_server = task_config["SERVER_LIST"][0]

    return {
        "hostname": meta["target"],
        "host": restore_server.get("HOST"),
        "port": restore_server.get("PORT") or 3306,
        "backup_type": BackupType(restore_server.get("BACKUP_TYPE")).name,
    }


async def get_restores_index_context(
    request: Request,
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    context: DefaultContext,
) -> dict[str, Any]:
    """Assemble the context for the Restores plugin index view.

    Retrieves MySQL services and associated tasks, organizing them based on their
    execution status. Integrates this information into the default context for
    rendering in templates.

    :param request: The HTTP request object.
    :type request: Request
    :param inventory_api: The Inventory API client for fetching service and schema data.
    :type inventory_api: InventoryAPI
    :param tasks_api: The TaskAPI client for fetching task data.
    :type tasks_api: TaskAPI
    :param context: The default context to be updated with Restores-specific information.
    :type context: DefaultContext
    :return: An updated context dictionary containing Restores-related data.
    :rtype: dict[str, Any]
    """
    return await get_tasks_context(
        request,
        inventory_api,
        tasks_api,
        get_restores_task_info,
        context,
        TaskOwner.RESTORES,
    )