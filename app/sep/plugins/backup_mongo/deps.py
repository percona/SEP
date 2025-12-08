"""Define dependencies for the Backups plugin."""

import logging
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import Depends, Form

from app.sep.deps import (
    DefaultContext,
    ExecutorHosts,
    get_task_by_name,
    get_tasks_context,
    InventoryAPI,
    TaskAPI,
)
from app.sep.plugins.backup_mongo.models import (
    BackupConfig,
    BackupConfigBackup,
    BackupConfigPITR,
    BackupConfigStorage,
    BackupCreate,
)
from app.tasks.models import (
    Task,
    TaskBackendEnum,
    TaskOwner,
    TaskWrite,
)

logger = logging.getLogger(__name__)


def _build_pitr_config(form: BackupCreate) -> dict[str, Any]:
    """Build PITR configuration from form data."""
    return {
        "enabled": form.pitr_enabled,
        "oplogSpanMin": form.pitr_oplog_span_min,
        "compression": form.pitr_compression,
    }


def _build_storage_config(form: BackupCreate) -> dict[str, Any]:
    """Build storage configuration from form data."""
    storage_config = {}
    if form.storage_type == "s3":
        storage_config = {
            "region": form.storage_s3_region,
            "bucket": form.storage_s3_bucket,
            "prefix": form.storage_s3_prefix,
            "endpointUrl": form.storage_s3_endpoint_url,
        }
    elif form.storage_type == "filesystem":
        storage_config = {"path": form.storage_filesystem_path}

    return {"type": form.storage_type, form.storage_type: storage_config}


def _parse_backup_priority(priority_str: str) -> dict[str, float] | None:
    """Parse backup priority YAML string and return as dictionary.

    Parses YAML input (dict format) and returns it as a dictionary
    mapping node addresses to priority values for PBM configuration.

    :param priority_str: YAML string containing priority configuration.
    :return: Parsed priority dictionary mapping node to priority or None if parsing fails.
    """
    try:
        priority_parsed = yaml.safe_load(priority_str)
    except yaml.YAMLError:
        logger.warning("Failed to parse backup priority YAML: %s", priority_str)
        return None
    else:
        if priority_parsed is None:
            return None
        if isinstance(priority_parsed, dict):
            return {str(k): float(v) for k, v in priority_parsed.items()}
        logger.warning(
            "Priority must be a dictionary/mapping, got: %s", type(priority_parsed)
        )
        return None


def _build_backup_config_dict(form: BackupCreate) -> dict[str, Any]:
    """Build backup configuration dictionary from form data."""
    has_backup_config = any(
        [
            form.backup_priority,
            form.backup_compression,
            form.backup_compression_level is not None,
            form.backup_timeouts_starting_status is not None,
            form.backup_oplog_span_min is not None,
            form.backup_num_parallel_collections is not None,
        ]
    )

    if not has_backup_config:
        return {}

    backup_config_dict = {}

    if form.backup_priority:
        priority_parsed = _parse_backup_priority(form.backup_priority)
        if priority_parsed is not None:
            backup_config_dict["priority"] = priority_parsed

    if form.backup_compression:
        backup_config_dict["compression"] = form.backup_compression

    if form.backup_compression_level is not None:
        backup_config_dict["compressionLevel"] = form.backup_compression_level

    if form.backup_timeouts_starting_status is not None:
        backup_config_dict["timeouts"] = {
            "startingStatus": form.backup_timeouts_starting_status
        }

    if form.backup_oplog_span_min is not None:
        backup_config_dict["oplogSpanMin"] = form.backup_oplog_span_min

    if form.backup_num_parallel_collections is not None:
        backup_config_dict["numParallelCollections"] = (
            form.backup_num_parallel_collections
        )

    return backup_config_dict


async def build_backup_task_payload(
    form: Annotated[BackupCreate, Form()],
) -> TaskWrite:
    """Build the backup task payload from form.

    Build the payload for a Backups task to be executed.

    :param form: The form data for the Backups creation.
    :type form: BackupCreate
    :return: A fully constructed `TaskWrite` object containing all the necessary
        configuration to create the Backup task.
    :rtype: TaskWrite
    """
    pitr = _build_pitr_config(form)
    storage = _build_storage_config(form)
    backup_config_dict = _build_backup_config_dict(form)

    backup_config = BackupConfig(
        storage=BackupConfigStorage.model_validate(storage),
        pitr=BackupConfigPITR.model_validate(pitr),
        backup=BackupConfigBackup.model_validate(backup_config_dict)
        if backup_config_dict
        else None,
    )

    if form.backup_type == "pbm_config":
        requirements = "packaging\nPyYAML"
    else:
        requirements = "packaging"

    payload_path = Path(__file__).parent / f"{form.backup_type}_payload"

    return TaskWrite(
        name=form.task_name,
        backend=TaskBackendEnum.PROXY,
        owner=TaskOwner.BACKUP_MONGO,
        data={
            "task": "run-python",
            "meta": {
                "config": yaml.dump(
                    backup_config.model_dump(
                        by_alias=False, exclude_none=True, mode="json"
                    ),
                    default_flow_style=False,
                    allow_unicode=True,
                ),
                "target": form.hostname,
                "requirements": requirements,
            },
            "payload": f"file://{payload_path}",
            "backup_type": form.backup_type,
        },
        alert_on_fail=form.alert_on_fail,
    )


BackupGeneratedTask = Annotated[TaskWrite, Depends(build_backup_task_payload)]


async def get_backups_task(
    task_name: str,
    tasks_api: TaskAPI,
) -> Task:
    """Fetch and validate a task for the Backups plugin.

    This function retrieves a task by its name from the Tasks API and validates
    that it is owned by the Backups plugin. If the task does not exist or is not
    owned by Backups, it raises a 404 HTTP exception.

    :param task_name: The name of the task to retrieve.
    :type task_name: str
    :param tasks_api: The TaskAPI instance used to make requests to the task service.
    :type tasks_api: TaskAPI
    :return: The retrieved task.
    :rtype: Task
    :raises HTTPNotFoundException: If the task is not found or is not owned by Backups.
    """
    return await get_task_by_name(tasks_api, task_name, TaskOwner.BACKUP_MONGO)


BackupsTask = Annotated[Task, Depends(get_backups_task)]


def get_backups_task_info(task: dict[str, Any]) -> dict[str, Any]:
    """Extract relevant information from a task for the Backups plugin.

    Processes the task data to extract hostname and tables information.

    :param task: The task data retrieved from the Tasks API.
    :type task: dict[str, Any]
    :return: A dictionary containing hostname and tables information.
    :rtype: dict[str, Any]
    """
    data = task["data"]
    meta = data["meta"]
    return {
        "config": yaml.safe_load(meta["config"]),
        "parent": data.get("parent"),
        "target": meta["target"],
        "created_at": task["created_at"],
        "created_by": task.get("created_by"),
        "last_updated_by": task.get("last_updated_by"),
    }


async def get_backups_index_context(
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    context: DefaultContext,
    executor_hosts: ExecutorHosts,
) -> dict[str, Any]:
    """Assemble the context for the Backups plugin index view.

    Retrieves MongoDB services and associated tasks, organizing them based on their
    execution status. Integrates this information into the default context for
    rendering in templates.

    :param inventory_api: The Inventory API client for fetching service and schema data.
    :type inventory_api: InventoryAPI
    :param tasks_api: The TaskAPI client for fetching task data.
    :type tasks_api: TaskAPI
    :param context: The default context to be updated with Backups-specific information.
    :type context: DefaultContext
    :param executor_hosts: The executor hosts for the Backups tasks.
    :type executor_hosts: ExecutorHosts
    :return: An updated context dictionary containing Backups-related data.
    :rtype: dict[str, Any]
    """
    return await get_tasks_context(
        inventory_api,
        tasks_api,
        get_backups_task_info,
        executor_hosts,
        context,
        TaskOwner.BACKUP_MONGO,
        alert_on_fail_default=True,
    )
