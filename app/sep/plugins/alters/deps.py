"""Define dependencies for the Alters plugin."""

import logging
from typing import Annotated

from fastapi import Depends
from fastapi import HTTPException

from app.sep.deps import TaskAPI

logger = logging.getLogger(__name__)


async def get_alters_task(
    task_name: str,
    tasks_api: TaskAPI,
) -> dict:  # TODO: refactor - (ab)use pydantic models
    """Fetch and validate a task for the Alters plugin.

    This function retrieves a task by its name from the Tasks API and validates
    that it is owned by the Alters plugin. If the task does not exist or is not
    owned by Alters, it raises a 404 HTTP exception.

    Parameters
    ----------
    task_name : str
        The name of the task to retrieve.
    tasks_api : TaskAPI
        The TaskAPI instance used to make requests to the task service.

    Returns
    -------
    dict
        The task data as a dictionary.

    Raises
    ------
    HTTPException
        If the task is not found or is not owned by Alters (HTTP status 404).

    """
    task = await tasks_api.get(
        f"/{task_name}",
    )  # TODO: refactor - (ab)use pydantic models
    if (
        task.get("owner") != "alters"
    ):  # TODO: Consider getting owner name from plugin MODULE_NAME
        raise HTTPException(404)
    return task


AltersTask = Annotated[dict, Depends(get_alters_task)]
