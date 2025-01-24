"""Define dependencies for the Tasks plugin."""

from typing import Annotated

from fastapi import Depends

from app.sep.deps import get_task_by_name
from app.tasks.models import Task

TaskDep = Annotated[Task, Depends(get_task_by_name)]
