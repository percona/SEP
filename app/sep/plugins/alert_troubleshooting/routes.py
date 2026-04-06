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
from app.sep.deps import IsAuthenticated, IsCsrfValidated, TaskAPI
from app.sep.plugins.alert_troubleshooting.deps import (
    AjaxExecutableSnippet,
    ExecutionRequestMeta,
    TroubleshootingDetailContext,
    TroubleshootingIndexContext,
)

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


@router.post(
    "/execute/{snippet_filename}",
    dependencies=[IsAuthenticated, IsCsrfValidated],
)
async def troubleshooting_execute(
    tasks_api: TaskAPI,
    snippet: AjaxExecutableSnippet,
    execution_request_meta: ExecutionRequestMeta,
) -> JSONResponse:
    """Execute a snippet via AJAX and return the task ID as JSON.

    Proxy the execution request to the Tasks API and return the task history
    ID for subsequent output polling.

    :param tasks_api: The authenticated Tasks API client.
    :type tasks_api: TaskAPI
    :param snippet: The validated executable snippet.
    :type snippet: AjaxExecutableSnippet
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
        task_id = result["id"]
        logger.info(
            "Troubleshooting execution submitted for snippet %r, task %s",
            snippet.filename,
            task_id,
        )
        return JSONResponse({"task_id": task_id, "status": "submitted"})
    except KeyError:
        logger.warning(
            "Unexpected response from Tasks API for snippet %r",
            snippet.filename,
        )
        return JSONResponse(
            {"error": "Unexpected response from Tasks API"},
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except HTTPException as exc:
        logger.warning(
            "HTTP error executing snippet %r: %s %s",
            snippet.filename,
            exc.status_code,
            exc.detail,
        )
        return JSONResponse(
            {"error": exc.detail or "Execution failed"},
            status_code=exc.status_code,
        )


@router.get("/output/{task_history_id}", dependencies=[IsAuthenticated])
async def troubleshooting_output(
    task_history_id: int,
    tasks_api: TaskAPI,
) -> JSONResponse:
    """Poll the execution status and output for a task history entry.

    Return the current task status and, when successful, the STDOUT content
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
        if task_status in ("success", "failed", "stopped"):
            try:
                files_meta = await tasks_api.get(f"/history/{task_history_id}/files/")
                output_parts = []
                for filename in files_meta:
                    try:
                        content = "".join(
                            [
                                chunk.decode("utf-8", errors="replace")
                                async for chunk in tasks_api.stream(
                                    f"/history/{task_history_id}/file/",
                                    params={"path": filename},
                                )
                            ]
                        )
                        if content:
                            output_parts.append(content)
                    except (HTTPException, KeyError, TypeError, OSError):
                        pass
                response_data["output"] = "\n".join(output_parts)
            except (HTTPException, KeyError, TypeError, OSError):
                logger.debug(
                    "Could not fetch output files for task %s",
                    task_history_id,
                    exc_info=True,
                )
        return JSONResponse(response_data)
    except HTTPException as exc:
        logger.warning(
            "HTTP error polling task %s: %s %s",
            task_history_id,
            exc.status_code,
            exc.detail,
        )
        return JSONResponse(
            {"error": exc.detail or "Failed to retrieve task output"},
            status_code=exc.status_code,
        )


@router.get(
    "/{service_type}/{alert_name}",
    dependencies=[IsAuthenticated],
    response_class=HTMLResponse,
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
