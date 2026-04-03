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

"""Define routes for the Alert Troubleshooting plugin."""

import logging

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse

from app.sep.config import sep_settings
from app.sep.deps import IsAuthenticated, TaskAPI
from app.sep.plugins.alert_troubleshooting.deps import (
    ExecutionRequestMeta,
    TroubleshootingDetailContext,
    TroubleshootingIndexContext,
)
from app.sep.plugins.snippets.deps import ExecutableSnippet

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def troubleshooting_index(
    request: Request,
    context: TroubleshootingIndexContext,
) -> HTMLResponse:
    """Render the Alert Troubleshooting index page.

    Display available alerts grouped by database service type in expandable
    accordion sections.

    :param request: The HTTP request object.
    :type request: Request
    :param context: The assembled template context with grouped alerts.
    :type context: TroubleshootingIndexContext
    :return: The rendered HTML response.
    :rtype: HTMLResponse
    """
    return templates.TemplateResponse(
        request=request,
        name="alert_troubleshooting/index.html.j2",
        context=context,
    )


@router.get(
    "/{alert_name}", dependencies=[IsAuthenticated], response_class=HTMLResponse
)
async def troubleshooting_detail(
    request: Request,
    context: TroubleshootingDetailContext,
) -> HTMLResponse:
    """Render the Alert Troubleshooting detail page for a specific alert.

    Display the alert header, shared host selector, and snippet cards with
    parameter forms for AJAX-based execution.

    :param request: The HTTP request object.
    :type request: Request
    :param context: The assembled template context with alert info and snippets.
    :type context: TroubleshootingDetailContext
    :return: The rendered HTML response.
    :rtype: HTMLResponse
    """
    return templates.TemplateResponse(
        request=request,
        name="alert_troubleshooting/detail.html.j2",
        context=context,
    )


@router.post(
    "/execute/{snippet_filename}",
    dependencies=[IsAuthenticated],
)
async def troubleshooting_execute(
    tasks_api: TaskAPI,
    snippet: ExecutableSnippet,
    execution_request_meta: ExecutionRequestMeta,
) -> JSONResponse:
    """Execute a snippet via AJAX and return the task ID as JSON.

    Proxy the execution request to the Tasks API and return the task history
    ID for subsequent output polling.

    :param tasks_api: The authenticated Tasks API client.
    :type tasks_api: TaskAPI
    :param snippet: The validated executable snippet.
    :type snippet: ExecutableSnippet
    :param execution_request_meta: The assembled execution metadata.
    :type execution_request_meta: ExecutionRequestMeta
    :return: A JSON response with the task ID and submission status.
    :rtype: JSONResponse
    """
    try:
        result = await tasks_api.post(
            f"/execute/{snippet.execution_task_name}",
            json={
                "meta": execution_request_meta.model_dump(
                    by_alias=True, exclude_none=True
                )
            },
        )
        logger.info(
            "Troubleshooting execution submitted for snippet %r, task %s",
            snippet.filename,
            result.get("id"),
        )
        return JSONResponse({"task_id": result["id"], "status": "submitted"})
    except Exception:
        logger.exception(
            "Failed to execute snippet %r via troubleshooting", snippet.filename
        )
        return JSONResponse(
            {"error": "Failed to submit snippet execution"},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )


@router.get("/output/{task_history_id}", dependencies=[IsAuthenticated])
async def troubleshooting_output(
    task_history_id: int,
    tasks_api: TaskAPI,
) -> JSONResponse:
    """Poll the execution status and output for a task history entry.

    Return the current task status and, when completed, the STDOUT content
    from the task's output files.

    :param task_history_id: The task history ID to poll.
    :type task_history_id: int
    :param tasks_api: The authenticated Tasks API client.
    :type tasks_api: TaskAPI
    :return: A JSON response with the task status and optional output.
    :rtype: JSONResponse
    """
    try:
        history = await tasks_api.get(f"/history/{task_history_id}/")
        task_status = history.get("status", "unknown")
        response_data = {"status": task_status, "output": ""}
        if task_status in ("completed", "failed", "stopped"):
            try:
                files = await tasks_api.get(f"/history/{task_history_id}/files/")
                output_parts = []
                for file_entry in files:
                    content = file_entry.get("content", "")
                    if content:
                        output_parts.append(content)
                response_data["output"] = "\n".join(output_parts)
            except (HTTPException, KeyError, TypeError, OSError):
                logger.debug(
                    "Could not fetch output files for task %s",
                    task_history_id,
                    exc_info=True,
                )
        return JSONResponse(response_data)
    except Exception:
        logger.exception("Failed to poll output for task history %s", task_history_id)
        return JSONResponse(
            {"error": "Failed to retrieve task output"},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
