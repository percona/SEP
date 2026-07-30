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

"""Define routes for the report plugin."""

import logging
from typing import Annotated

from fastapi import APIRouter, Form, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import ValidationError

from app.sep.apps.report.celery import (
    render_report_pdf_job,
    upload_report_snapshot_job,
)
from app.sep.config import sep_settings
from app.sep.deps import IsAuthenticated, IsCsrfValidated
from app.sep.middleware.csrf import CSRF_COOKIE_NAME

from .deps import IsUploadConfigured, ReportIndexContext, RequiredPMMAPIDep
from .job_service import filter_report_sections, report_pdf_filename
from .models import ReportData
from .service import (
    generate_report,
    SERVICE_NAMES,
)

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES


@router.get(
    "/",
    dependencies=[IsAuthenticated],
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def report_index(request: Request, context: ReportIndexContext) -> HTMLResponse:
    """Render the report plugin landing page.

    :param request: The incoming HTTP request.
    :type request: Request
    :param context: Template context for the landing page.
    :type context: ReportIndexContext
    :return: Rendered report landing page.
    :rtype: HTMLResponse
    """
    return templates.TemplateResponse(request, "report/index.html.j2", context)


@router.post(
    "/generate",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def report_generate(
    request: Request,
    pmm_api: RequiredPMMAPIDep,
    context: ReportIndexContext,
    since: Annotated[str, Form()] = "now-7d",
    until: Annotated[str, Form()] = "now",
    *,
    full: Annotated[bool, Form()] = True,
    refresh: Annotated[bool, Form()] = False,
) -> HTMLResponse:
    """Generate a report and render the HTML result page.

    :param request: The incoming HTTP request.
    :type request: Request
    :param pmm_api: The PMM API client.
    :type pmm_api: PMMRemoteAPI
    :param context: Template context.
    :type context: ReportIndexContext
    :param since: Relative start of the report period.
    :type since: str
    :param until: Relative end of the report period.
    :type until: str
    :param full: Include all check results and full backup history.
    :type full: bool
    :param refresh: Force a refresh of advisor checks before fetching results.
    :type refresh: bool
    :return: Rendered HTML report.
    :rtype: HTMLResponse
    """
    report = await generate_report(
        pmm_api, since=since, until=until, full=full, refresh=refresh
    )
    context.update(
        {
            "report": report,
            "service_names": SERVICE_NAMES,
            "report_json": report.model_dump_json(),
            "report_params": {
                "since": since,
                "until": until,
                "full": full,
                "refresh": refresh,
            },
            "csrf_token": request.cookies.get(CSRF_COOKIE_NAME, ""),
            "upload_disabled_reasons": sep_settings.HEALTH_REPORT.upload_disabled_reasons,
        }
    )
    return templates.TemplateResponse(request, "report/result.html.j2", context)


@router.get(
    "/generate/json",
    dependencies=[IsAuthenticated],
    response_class=JSONResponse,
    include_in_schema=False,
)
async def report_generate_json(
    pmm_api: RequiredPMMAPIDep,
    since: Annotated[str, Query()] = "now-7d",
    until: Annotated[str, Query()] = "now",
    *,
    full: Annotated[bool, Query()] = True,
    refresh: Annotated[bool, Query()] = False,
    sections: Annotated[list[str] | None, Query()] = None,
) -> JSONResponse:
    """Generate a report and return as JSON.

    :param pmm_api: The PMM API client.
    :type pmm_api: PMMRemoteAPI
    :param since: Relative start of the report period.
    :type since: str
    :param until: Relative end of the report period.
    :type until: str
    :param full: Include all check results and full backup history.
    :type full: bool
    :param refresh: Force a refresh of advisor checks before fetching results.
    :type refresh: bool
    :param sections: Optional list of sections to include.
    :type sections: list[str] | None
    :return: JSON response with the full report data.
    :rtype: JSONResponse
    """
    report = await generate_report(
        pmm_api,
        since=since,
        until=until,
        full=full,
        refresh=refresh,
        sections=filter_report_sections(sections),
    )
    return JSONResponse(content=report.model_dump(mode="json"))


@router.post(
    "/generate/pdf",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    include_in_schema=False,
)
async def report_generate_pdf(
    request: Request,
    context: ReportIndexContext,
    report_json: Annotated[str, Form()],
) -> Response:
    """Enqueue PDF rendering and render an async job status page.

    :param request: The incoming HTTP request.
    :type request: Request
    :param context: Template context.
    :type context: ReportIndexContext
    :param report_json: Existing report JSON snapshot.
    :type report_json: str
    :return: Rendered job status page, or a validation error response.
    :rtype: HTMLResponse | JSONResponse
    """
    try:
        report = ReportData.model_validate_json(report_json)
    except ValidationError as exc:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": exc.errors()},
        )
    result = render_report_pdf_job.delay(report.model_dump(mode="json"))
    context.update(
        {
            "job_id": result.id,
            "job_title": "PDF generation started",
            "job_description": f"Rendering {report_pdf_filename(report)}.",
            "poll_url": str(request.url_for("report_pdf_job_api", job_id=result.id)),
            "download_url": str(
                request.url_for("report_download_pdf_api", job_id=result.id)
            ),
            "success_message": "PDF is ready.",
            "back_url": str(request.url_for("report_index")),
        }
    )
    return templates.TemplateResponse(request, "report/job.html.j2", context)


@router.post(
    "/upload",
    dependencies=[IsAuthenticated, IsCsrfValidated, IsUploadConfigured],
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def report_upload(
    request: Request,
    context: ReportIndexContext,
    report_json: Annotated[str, Form()],
) -> Response:
    """Enqueue PDF upload and render an async job status page.

    :param request: The incoming HTTP request.
    :type request: Request
    :param context: Template context.
    :type context: ReportIndexContext
    :param report_json: Existing report JSON snapshot.
    :type report_json: str
    :return: Rendered job status page, or a validation error response.
    :rtype: HTMLResponse | JSONResponse
    """
    try:
        report = ReportData.model_validate_json(report_json)
    except ValidationError as exc:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": exc.errors()},
        )
    result = upload_report_snapshot_job.delay(report.model_dump(mode="json"))
    context.update(
        {
            "job_id": result.id,
            "job_title": "ServiceNow upload started",
            "job_description": f"Uploading {report_pdf_filename(report)}.",
            "poll_url": str(request.url_for("report_upload_job_api", job_id=result.id)),
            "download_url": None,
            "success_message": "Report uploaded to ServiceNow.",
            "back_url": str(request.url_for("report_index")),
        }
    )
    return templates.TemplateResponse(request, "report/job.html.j2", context)
