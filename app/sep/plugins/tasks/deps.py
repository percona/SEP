"""Define dependencies for the Tasks plugin."""

from typing import Annotated

from fastapi import Depends

from app.sep.deps import get_task_by_name

TaskDep = Annotated[dict, Depends(get_task_by_name)]
