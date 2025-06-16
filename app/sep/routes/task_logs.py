"""Define routes for the finished tasks logs."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.sep.deps import get_task_history, IsAuthenticated
from app.sep.utils.decorators import csrf_exempt
from app.tasks.models import TaskHistoryResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/{task_history_id}", dependencies=[IsAuthenticated])
@csrf_exempt
async def task_logs(
    request: Request,
    task_history: Annotated[TaskHistoryResponse, Depends(get_task_history)],
) -> JSONResponse:
    """Retrieve task logs and status for a specific task history entry."""
    logger.debug("request.state.is_csrf_exempt is %s", request.state.is_csrf_exempt)

    execution_request = task_history.execution_request
    if not execution_request or "task_logs" not in execution_request.tracking:
        raise HTTPException(status_code=404, detail="Logs not found")

    return JSONResponse(
        content={
            "task_logs": execution_request.tracking["task_logs"],
            "status": task_history.status,
        }
    )
