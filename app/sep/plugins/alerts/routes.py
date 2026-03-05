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

"""Define routes for the alerts plugin."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.sep.config import sep_settings
from app.sep.deps import IsAuthenticated
from app.sep.plugins.alerts.deps import get_alerts_index_context

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def alerts_index(
    request: Request,
    context: Annotated[dict[str, Any], Depends(get_alerts_index_context)],
) -> HTMLResponse:
    """Render the alert templates list page."""
    return templates.TemplateResponse(
        request=request,
        name="alerts/index.html.j2",
        context=context,
    )
