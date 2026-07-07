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

"""Define dependencies for the report plugin."""

import logging
from typing import Annotated, Any

from fastapi import Depends

from app.core.exceptions import HTTPServiceUnavailableException
from app.sep.apps.report.models import REPORT_SECTION_LABELS
from app.sep.clients.pmm import PMMRemoteAPI
from app.sep.config import sep_settings
from app.sep.deps import (
    DefaultContext,
    get_pmm_api,  # noqa: F401 -- re-exported for existing importers
    PMMAPIDep,
)

logger = logging.getLogger(__name__)


async def require_pmm_api(pmm_api: PMMAPIDep) -> PMMRemoteAPI:
    """Return the PMM API client or raise if PMM is not configured.

    :param pmm_api: The PMM API client dependency.
    :type pmm_api: PMMRemoteAPI | None
    :return: The PMM API client.
    :rtype: PMMRemoteAPI
    :raises HTTPServiceUnavailableException: If PMM is not configured.
    """
    if pmm_api is None:
        raise HTTPServiceUnavailableException(detail="PMM is not configured")
    return pmm_api


RequiredPMMAPIDep = Annotated[PMMRemoteAPI, Depends(require_pmm_api)]


async def require_upload_configured() -> None:
    """Raise if report upload to ServiceNow is not configured.

    :raises HTTPServiceUnavailableException: If any required upload setting is
        missing.
    """
    if not sep_settings.HEALTH_REPORT.is_upload_configured:
        raise HTTPServiceUnavailableException(detail="Report upload is not configured")


IsUploadConfigured = Depends(require_upload_configured)


async def get_report_index_context(
    context: DefaultContext,
    pmm_api: PMMAPIDep,
) -> dict[str, Any]:
    """Assemble the template context for the report plugin index view.

    :param context: The default template context.
    :type context: DefaultContext
    :param pmm_api: The PMM API client or ``None`` (injected via ``PMMAPIDep``).
    :type pmm_api: PMMRemoteAPI | None
    :return: The updated context dictionary.
    :rtype: dict[str, Any]
    """
    context.update(
        {
            "pmm_configured": pmm_api is not None,
            "sections": REPORT_SECTION_LABELS,
        }
    )
    return context


ReportIndexContext = Annotated[dict[str, Any], Depends(get_report_index_context)]
