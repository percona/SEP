"""Define dependencies for the Archives plugin."""

import logging
import yaml

from typing import Annotated

from fastapi import Depends
from fastapi import Form
from fastapi import HTTPException

from app.sep.deps import TaskAPI
from app.sep.plugins.archives.models import ArchivesCreate
from app.tasks.models import GeneratedTask

logger = logging.getLogger(__name__)

PURGE_TABLES_CONFIG_WHERE = {
    "ALL": {"SOURCE_HOST": None, "SOURCE_PORT": 0},
    "PURGE_LIST": [{"ALIAS": None, "SOURCE_DB": None, "SOURCE_TABLE": None, "DEST_TABLE": None, "WHERE": None}],
}

async def build_archives_task_payload(
    form: Annotated[ArchivesCreate, Form()],
) -> GeneratedTask:
    """Build the archive task payload from form.

    Build the payload for an Archives task to be executed, including the
    necessary command arguments for performing archive.

    :param form: The form data for the Archives creation.
    :type form: ArchivesCreate
    :return: A fully constructed `GeneratedTask` object containing all the necessary
        commands and parameters for the Archives task execution.
    :rtype: GeneratedTask
    """
    match form.archive_type:
        case "where":
            purge_config = PURGE_TABLES_CONFIG_WHERE.copy()
        case _:
            raise NotImplementedError("Currently only 'where' is supported")
       
    purge_config_all = purge_config["ALL"]
    purge_config_list = purge_config["PURGE_LIST"][0]
    purge_config_all.update(SOURCE_HOST=form.hostname, SOURCE_PORT=3306)
    purge_config_list.update(
        ALIAS=form.task_name,
        SOURCE_DB=form.sourcedb,
        SOURCE_TABLE=form.sourcetbl,
        DEST_TABLE=form.dest_name,
        WHERE=f'{form.where}',
    )
    
    purge_config.update(ALL=purge_config_all, PURGE_LIST=[purge_config_list])

    return GeneratedTask(
        app="archiver",
        commands=[
            {
                "args": [
                    f"--alias={form.task_name}",
                    "--config=${NOMAD_TASK_DIR}/purge_tables.yaml",
                ],
                "command": "/home/percona/bin/purge-tables.py",
                "config": [
                    {
                        "content": yaml.dump(purge_config),
                        "path": "purge_tables.yaml",
                    }
                ],
            }
        ],
        name=form.task_name,
        target=form.hostname,
    )

ArchivesGeneratedTask = Annotated[GeneratedTask, Depends(build_archives_task_payload)]


async def get_archives_task(
    task_name: str,
    tasks_api: TaskAPI,
) -> dict:  # TODO: refactor - (ab)use pydantic models
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
    )  # TODO: refactor - (ab)use pydantic models
    if (
        task.get("owner") != "alters"
    ):  # TODO: Consider getting owner name from plugin MODULE_NAME
        raise HTTPException(404)
    return task


ArchivesTask = Annotated[dict, Depends(get_archives_task)]
