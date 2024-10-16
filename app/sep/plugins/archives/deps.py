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
