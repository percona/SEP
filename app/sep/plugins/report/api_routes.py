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

"""Define the JSON API router for the report plugin.

Mounted at ``/api/plugins/report/`` via ``plugins_router`` in
``app/sep/api/router.py``. Authentication is enforced at the ``api_router``
level. Route layout:

* ``GET /generate`` — return report data as JSON (cookie or Bearer)
* ``POST /generate/pdf`` — generate report and return PDF bytes (Bearer required)
* ``POST /upload`` — generate report, render PDF, upload to ServiceNow (Bearer required)
"""

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.sep.deps import RequireBearerAuth
from app.sep.plugins.report.deps import IsUploadConfigured, RequiredPMMAPIDep
from app.sep.plugins.report.models import REPORT_SECTIONS, ReportData
from app.sep.plugins.report.schemas import ReportGenerateWrite, ReportUploadResponse
from app.sep.plugins.report.service import (
    generate_pdf_report,
    generate_report,
    upload_pdf_report,
)

router = APIRouter()


def _filter_sections(sections: list[str] | None) -> list[str] | None:
    """Return only section names that exist in ``REPORT_SECTIONS``.

    :param sections: Optional list of requested section names.
    :type sections: list[str] | None
    :return: Filtered list, or ``None`` when no sections were requested.
    :rtype: list[str] | None
    """
    if sections:
        return [s for s in sections if s in REPORT_SECTIONS]
    return sections


@router.get("/generate")
async def report_api_generate(
    pmm_api: RequiredPMMAPIDep,
    since: Annotated[str, Query()] = "now-7d",
    until: Annotated[str, Query()] = "now",
    *,
    full: Annotated[bool, Query()] = True,
    refresh: Annotated[bool, Query()] = False,
    sections: Annotated[list[str] | None, Query()] = None,
) -> ReportData:
    """Generate a report and return it as JSON.

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
    :return: Complete report data.
    :rtype: ReportData
    """
    return await generate_report(
        pmm_api,
        since=since,
        until=until,
        full=full,
        refresh=refresh,
        sections=_filter_sections(sections),
    )


@router.post("/generate/pdf", dependencies=[RequireBearerAuth])
async def report_api_generate_pdf(
    pmm_api: RequiredPMMAPIDep,
    body: ReportGenerateWrite,
) -> Response:
    """Generate a report and return it as a downloadable PDF.

    :param pmm_api: The PMM API client.
    :type pmm_api: PMMRemoteAPI
    :param body: Report generation parameters.
    :type body: ReportGenerateWrite
    :return: PDF file response.
    :rtype: Response
    """
    report = await generate_report(
        pmm_api,
        since=body.since,
        until=body.until,
        full=body.full,
        refresh=body.refresh,
    )
    pdf_bytes = await generate_pdf_report(report)
    filename = f"Health_and_Security_Report_{report.metadata.generated_at:%Y-%m-%d}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/upload", dependencies=[RequireBearerAuth, IsUploadConfigured])
async def report_api_upload(
    pmm_api: RequiredPMMAPIDep,
    body: ReportGenerateWrite,
) -> ReportUploadResponse:
    """Generate a report, convert to PDF, and upload to ServiceNow.

    :param pmm_api: The PMM API client.
    :type pmm_api: PMMRemoteAPI
    :param body: Report generation parameters.
    :type body: ReportGenerateWrite
    :return: ServiceNow upload API response.
    :rtype: ReportUploadResponse
    """
    report = await generate_report(
        pmm_api,
        since=body.since,
        until=body.until,
        full=body.full,
        refresh=body.refresh,
    )
    pdf_bytes = await generate_pdf_report(report)
    result = await upload_pdf_report(report, pdf_bytes)
    return ReportUploadResponse.model_validate(result)
