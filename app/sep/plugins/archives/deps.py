# Copyright (C) 2026 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Define dependencies for the Archives plugin."""

import logging
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import Body, Depends, Form

from app.core.exceptions import HTTPUnprocessableEntityException
from app.inventory.constants import DEFAULT_MYSQL_PORT
from app.inventory.models import ServiceTypeEnum
from app.sep.connectivity import (
    CONNECTIVITY_META_HOST_KEY,
    CONNECTIVITY_META_PORT_KEY,
    CONNECTIVITY_META_SERVICE_TYPE_KEY,
)
from app.sep.deps import (
    DefaultContext,
    ExecutorHostsCtx,
    get_created_entity,
    get_tasks_context,
    InventoryAPI,
    TaskAPI,
)
from app.sep.models import SyncInventoryEntityTypeEnum
from app.sep.plugins.archives.models import (
    ArchivesCreate,
    ArchivesTaskResponse,
    PurgeConfig,
    PurgeConfigAll,
)
from app.sep.plugins.framework import (
    build_default_task_response,
    build_task_list_responses,
    make_task_dep,
)
from app.tasks.models import (
    Task,
    TaskBackendEnum,
    TaskHistoryStatusEnum,
    TaskOwner,
    TaskWrite,
)

logger = logging.getLogger(__name__)


async def _resolve_source_tables(
    form: ArchivesCreate, inventory_api: InventoryAPI, service_id: int
) -> tuple[dict[str, str], Any]:
    """Resolve source database and table names.

    Fetches source schema and table entities from inventory if IDs are provided,
    otherwise uses manually-entered names.

    :param form: The form data containing source specifications.
    :type form: ArchivesCreate
    :param inventory_api: The Inventory API client.
    :type inventory_api: InventoryAPI
    :param service_id: The source service ID.
    :type service_id: int
    :return: A tuple of resolved source data dict and schema object (or None).
    :rtype: tuple[dict[str, str], Any]
    """
    source_data = {}
    schema = None

    if form.source_db_id is not None:
        schema = await get_created_entity(
            inventory_api,
            SyncInventoryEntityTypeEnum.SCHEMA,
            form.source_db_id,
            service_id=service_id,
        )
        source_data["source_db"] = schema.name
    elif source_db := form.source_db_name.strip():
        source_data["source_db"] = source_db
        if source_table := form.source_table_name.strip():
            source_data["source_table"] = source_table
        return source_data, schema

    if form.source_table_id is not None:
        source_table = await get_created_entity(
            inventory_api,
            SyncInventoryEntityTypeEnum.TABLE,
            form.source_table_id,
            schema_id=schema.id,
        )
        source_data["source_table"] = source_table.name

    return source_data, schema


async def _resolve_destination_tables(
    form: ArchivesCreate, inventory_api: InventoryAPI
) -> dict[str, str]:
    """Resolve destination table or file path.

    Fetches destination table entity from inventory if ID is provided,
    otherwise uses manually-entered name or file path.

    :param form: The form data containing destination specifications.
    :type form: ArchivesCreate
    :param inventory_api: The Inventory API client.
    :type inventory_api: InventoryAPI
    :return: A dictionary with resolved destination data.
    :rtype: dict[str, str]
    """
    dest_data = {}

    if form.dest_table_id is not None:
        dest_table = await get_created_entity(
            inventory_api,
            SyncInventoryEntityTypeEnum.TABLE,
            form.dest_table_id,
        )
        dest_data["dest_table"] = dest_table.name
    elif dest_table := form.dest_table_name.strip():
        dest_data["dest_table"] = dest_table
    elif form.dest_file is not None:
        dest_data["dest_file"] = form.dest_file

    return dest_data


async def _resolve_destination_host_and_db(
    form: ArchivesCreate, inventory_api: InventoryAPI
) -> dict[str, Any]:
    """Resolve destination host and database schema.

    Fetches destination service and schema from inventory if IDs are provided,
    otherwise uses manually-entered host, port, and database name.

    :param form: The form data containing destination specifications.
    :type form: ArchivesCreate
    :param inventory_api: The Inventory API client.
    :type inventory_api: InventoryAPI
    :return: A dictionary with resolved destination host/port/database data.
    :rtype: dict[str, Any]
    """
    dest_data = {}

    if form.dest_service_id is not None:
        dest_service = await get_created_entity(
            inventory_api,
            SyncInventoryEntityTypeEnum.SERVICE,
            form.dest_service_id,
            type=ServiceTypeEnum.MYSQL,
        )
        dest_data["dest_host"] = dest_service.node.address
        dest_data["dest_port"] = dest_service.port or DEFAULT_MYSQL_PORT
    elif dest_host := (form.dest_host or "").strip():
        dest_data["dest_host"] = dest_host
        dest_data["dest_port"] = form.dest_port or DEFAULT_MYSQL_PORT

    if form.dest_db_id is not None:
        dest_schema = await get_created_entity(
            inventory_api,
            SyncInventoryEntityTypeEnum.SCHEMA,
            form.dest_db_id,
            service_id=form.dest_service_id,
        )
        dest_data["dest_db"] = dest_schema.name
    elif dest_db := form.dest_db_name.strip():
        dest_data["dest_db"] = dest_db

    return dest_data


def _assert_not_self_archive(
    source_data: dict[str, str],
    dest_tables: dict[str, str],
    dest_host_db: dict[str, Any],
    source_host: str,
    source_port: int,
) -> None:
    """Raise if destination resolves to the same host, port, schema, and table as source.

    Called after all inventory resolutions are complete so names are concrete.
    Skips the check when there is no destination table (file destination or
    swap_drop path) or when there is no resolved source table (source_query path).

    :param source_data: Resolved source fields (``source_db``, ``source_table``).
    :type source_data: dict[str, str]
    :param dest_tables: Resolved destination table fields (``dest_table``).
    :type dest_tables: dict[str, str]
    :param dest_host_db: Resolved destination host fields (``dest_host``, ``dest_port``, ``dest_db``).
    :type dest_host_db: dict[str, Any]
    :param source_host: The source service node address.
    :type source_host: str
    :param source_port: The source service port.
    :type source_port: int
    :raises HTTPUnprocessableEntityException: If source and destination are the same table.
    """
    if "dest_table" not in dest_tables or not source_data.get("source_table"):
        return
    effective_dest_host = dest_host_db.get("dest_host") or source_host
    effective_dest_port = dest_host_db.get("dest_port") or source_port
    effective_dest_db = dest_host_db.get("dest_db") or source_data.get("source_db")
    if (
        effective_dest_host == source_host
        and effective_dest_port == source_port
        and (effective_dest_db or "") == (source_data.get("source_db") or "")
        and dest_tables["dest_table"] == source_data["source_table"]
    ):
        raise HTTPUnprocessableEntityException(
            detail="Source and Destination tables cannot be the same."
        )


async def _build_archives_payload(
    form: ArchivesCreate,
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build the ``TaskWrite`` payload from a validated ``ArchivesCreate``.

    Shared core for both the form-bodied (Jinja2) and JSON-bodied (REST API)
    entry points. The two FastAPI dependency wrappers below remain separate
    because mixing ``Form()`` and ``Body()`` parameter types in a single route
    signature silently breaks request parsing; this helper holds the body so
    the wrappers stay thin.

    :param form: The validated form/body model for the Archives creation.
    :type form: ArchivesCreate
    :param inventory_api: The Inventory API to get entities from.
    :type inventory_api: InventoryAPI
    :return: A fully constructed ``TaskWrite`` object.
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
                "disable_bulk_insert",
                "delete_data",
            },
            by_alias=True,
        ),
    }

    source_data, _ = await _resolve_source_tables(form, inventory_api, service.id)
    purge_item_data.update(source_data)

    dest_tables = await _resolve_destination_tables(form, inventory_api)
    purge_item_data.update(dest_tables)

    dest_host_db = await _resolve_destination_host_and_db(form, inventory_api)
    purge_item_data.update(dest_host_db)

    _assert_not_self_archive(
        source_data,
        dest_tables,
        dest_host_db,
        service.node.address,
        service.port or DEFAULT_MYSQL_PORT,
    )

    purge_config = PurgeConfig(
        all=PurgeConfigAll(
            source_host=service.node.address,
            source_port=service.port or DEFAULT_MYSQL_PORT,
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
                    purge_config.model_dump(
                        mode="json", by_alias=True, exclude_none=True
                    )
                ),
                "target": form.hostname,
                "requirements": "PyMySQL[rsa,ed25519]\nfilelock\nPyYAML",
                "_service_name": service.name,
                # Source DB node name for PMM annotations (overrides TaskExecutionRequest.target).
                "_pmm_node_name": service.node.name,
                CONNECTIVITY_META_HOST_KEY: service.node.address,
                CONNECTIVITY_META_PORT_KEY: service.port or DEFAULT_MYSQL_PORT,
                CONNECTIVITY_META_SERVICE_TYPE_KEY: service.type.value,
            },
            "payload": f"file://{payload_path}",
        },
        alert_on_fail=form.alert_on_fail,
    )


async def build_archives_task_payload(
    form: Annotated[ArchivesCreate, Form()],
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build the archive task payload from an HTML form body (Jinja2 path)."""
    return await _build_archives_payload(form, inventory_api)


ArchivesGeneratedTask = Annotated[TaskWrite, Depends(build_archives_task_payload)]


async def build_archives_api_task_payload(
    form: Annotated[ArchivesCreate, Body()],
    inventory_api: InventoryAPI,
) -> TaskWrite:
    """Build the archive task payload from a JSON body (REST API path)."""
    return await _build_archives_payload(form, inventory_api)


ArchivesApiGeneratedTask = Annotated[
    TaskWrite, Depends(build_archives_api_task_payload)
]


get_archives_task = make_task_dep(TaskOwner.ARCHIVER)

ArchivesTask = Annotated[Task, Depends(get_archives_task)]


def build_archives_api_task_response(
    task: Task,
    status: TaskHistoryStatusEnum | None = None,
) -> ArchivesTaskResponse:
    """Build an archive task response object for the JSON API.

    :param task: The archive task retrieved from the Tasks API.
    :type task: Task
    :param status: The latest known execution status for the task.
    :type status: TaskHistoryStatusEnum | None
    :return: A validated archive task API response object.
    :rtype: ArchivesTaskResponse
    """
    return build_default_task_response(
        ArchivesTaskResponse,
        task,
        status,
        extras={"service_type": ServiceTypeEnum.MYSQL},
    )


async def get_archives_api_task_responses(
    tasks_api: TaskAPI,
) -> list[ArchivesTaskResponse]:
    """Retrieve archive task responses for the JSON API.

    :param tasks_api: The TaskAPI instance used to query archive tasks.
    :type tasks_api: TaskAPI
    :return: The archive task responses enriched with service_type and status.
    :rtype: list[ArchivesTaskResponse]
    """
    return await build_task_list_responses(
        tasks_api,
        owner=TaskOwner.ARCHIVER.value,
        response_builder=build_archives_api_task_response,
    )


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
    dest_db = purge_item.get("DEST_DB")

    result = {
        "hostname": meta["target"],
        "created_by": task.get("created_by"),
        "last_updated_by": task.get("last_updated_by"),
    }

    if source_db and source_table:
        result["source_table"] = f"{source_db}.{source_table}"
    if dest_table:
        display_db = dest_db if dest_db else source_db
        if display_db:
            result["dest_table"] = f"{display_db}.{dest_table}"
        else:
            result["dest_table"] = dest_table
    if source_query:
        result["source_query"] = source_query
    if dest_file:
        result["dest_file"] = dest_file

    return result


async def get_archives_index_context(
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    context: DefaultContext,
    executor_hosts_ctx: ExecutorHostsCtx,
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
    :param executor_hosts_ctx: The executor hosts context for the Archives tasks.
    :type executor_hosts_ctx: ExecutorHostsCtx
    :return: An updated context dictionary containing Archives-related data.
    :rtype: dict[str, Any]
    """
    return await get_tasks_context(
        inventory_api,
        tasks_api,
        get_archives_task_info,
        executor_hosts_ctx,
        context,
        TaskOwner.ARCHIVER,
        alert_on_fail_default=True,
    )
