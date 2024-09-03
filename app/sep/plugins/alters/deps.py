from typing import Annotated

from fastapi import Depends
from fastapi import HTTPException

from app.sep.deps import TaskAPI


async def get_alters_task(
    task_name: str, tasks_api: TaskAPI
) -> dict:  # TODO: refactor - (ab)use pydantic models
    task = await tasks_api.get(
        f"/{task_name}",
    )  # TODO: refactor - (ab)use pydantic models
    if "alters" not in task.get("meta", {}).get("owners", []):  # TODO: filter on query
        raise HTTPException(404)
    return task


AltersTask = Annotated[dict, Depends(get_alters_task)]
