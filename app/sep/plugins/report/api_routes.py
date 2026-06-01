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
level and redeclared per route for safety. Route layout:

* ``GET  /config``          — return upload configuration status
* ``GET  /generate/json``   — generate report and return as JSON
* ``POST /generate/pdf``    — generate report and return as PDF download
* ``POST /upload``          — generate report, convert to PDF, upload to ServiceNow
"""

from typing import Annotated

from fastapi import APIRouter, Form, Query, Response
from fastapi.responses import JSONResponse

from app.sep.config import sep_settings
from app.sep.deps import IsApiAuthenticated
from app.sep.plugins.report.deps import IsUploadConfigured, RequiredPMMAPIDep
from app.sep.plugins.report.models import REPORT_SECTIONS
from app.sep.plugins.report.service import (
    generate_pdf_report,
    generate_report,
    upload_pdf_report,
)

router = APIRouter()


@router.get("/config", dependencies=[IsApiAuthenticated])
async def report_config() -> JSONResponse:
    """Return upload configuration status.

    :return: JSON with ``upload_disabled_reasons`` — empty list means upload is ready.
    :rtype: JSONResponse
    """
    return JSONResponse(
        content={
            "upload_disabled_reasons": sep_settings.HEALTH_REPORT.upload_disabled_reasons
        }
    )


@router.get("/generate/json", dependencies=[IsApiAuthenticated])
async def report_generate_json_api(
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


@router.post("/generate/pdf", dependencies=[IsApiAuthenticated])
async def report_generate_pdf_api(
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


@router.post("/upload", dependencies=[IsApiAuthenticated, IsUploadConfigured])
async def report_upload_api(
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
