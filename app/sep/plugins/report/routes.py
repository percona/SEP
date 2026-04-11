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

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app.sep.config import sep_settings
from app.sep.deps import IsAuthenticated, IsCsrfValidated
from app.sep.middleware.csrf import CSRF_COOKIE_NAME

from .deps import IsUploadConfigured, ReportIndexContext, RequiredPMMAPIDep
from .models import REPORT_SECTIONS
from .service import (
    generate_pdf_report,
    generate_report,
    SERVICE_NAMES,
    upload_pdf_report,
)

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def report_index(request: Request, context: ReportIndexContext) -> HTMLResponse:
    """Render the report plugin landing page."""
    return templates.TemplateResponse(request, "report/index.html.j2", context)


@router.post(
    "/generate",
    dependencies=[IsAuthenticated, IsCsrfValidated],
    response_class=HTMLResponse,
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
    if sections:
        sections = [s for s in sections if s in REPORT_SECTIONS]
    report = await generate_report(
        pmm_api, since=since, until=until, full=full, refresh=refresh, sections=sections
    )
    return JSONResponse(content=report.model_dump(mode="json"))


@router.post(
    "/generate/pdf",
    dependencies=[IsAuthenticated, IsCsrfValidated],
)
async def report_generate_pdf(
    pmm_api: RequiredPMMAPIDep,
    since: Annotated[str, Form()] = "now-7d",
    until: Annotated[str, Form()] = "now",
    *,
    full: Annotated[bool, Form()] = True,
    refresh: Annotated[bool, Form()] = False,
) -> Response:
    """Generate a report and return it as a downloadable PDF.

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
    :return: PDF file response.
    :rtype: Response
    """
    report = await generate_report(
        pmm_api, since=since, until=until, full=full, refresh=refresh
    )
    pdf_bytes = await generate_pdf_report(report)
    filename = f"Health_and_Security_Report_{report.metadata.generated_at:%Y-%m-%d}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/upload",
    dependencies=[IsAuthenticated, IsCsrfValidated, IsUploadConfigured],
    response_class=JSONResponse,
)
async def report_upload(
    pmm_api: RequiredPMMAPIDep,
    since: Annotated[str, Form()] = "now-7d",
    until: Annotated[str, Form()] = "now",
    *,
    full: Annotated[bool, Form()] = True,
    refresh: Annotated[bool, Form()] = False,
) -> JSONResponse:
    """Generate a report, convert to PDF, and upload to ServiceNow.

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
    :return: JSON response with the upload result.
    :rtype: JSONResponse
    """
    report = await generate_report(
        pmm_api, since=since, until=until, full=full, refresh=refresh
    )
    pdf_bytes = await generate_pdf_report(report)
    result = await upload_pdf_report(report, pdf_bytes)
    return JSONResponse(content=result)
