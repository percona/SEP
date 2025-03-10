"""Define routes for decryption of tasks logs."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from starlette.responses import JSONResponse

from app.sep.deps import get_task_history, IsAdminDep, IsAuthenticated
from app.sep.utils.decorators import csrf_exempt
from app.tasks.models import TaskHistoryResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/{task_history_id}", dependencies=[IsAuthenticated, IsAdminDep])
@csrf_exempt
async def decrypt_task_history_logs(
    request: Request,
    task_history: Annotated[TaskHistoryResponse, Depends(get_task_history)],
) -> JSONResponse:
    """Retrieve and return a task history's logs.

    The logs are extracted from `execution_request.tracking`, which contains
    detailed information about the task's execution stages.

    :param request: The incoming HTTP request.
    :type request: Request
    :param task_history: The task history data retrieved via dependency injection.
    :type task_history: TaskHistoryResponse
    :return: A JSON response containing the task logs.
    :rtype: JSONResponse
    """
    logger.debug("request.state.is_csrf_exempt is %s", request.state.is_csrf_exempt)

    response_data = task_history.execution_request.tracking

    return JSONResponse(content=response_data)
