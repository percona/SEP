"""Define routes for the plugin."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.sep.config import sep_settings
from app.sep.deps import (
    IsAuthenticated,
)
from app.sep.plugins.atw.deps import (
    get_app_index_context,
)

logger = logging.getLogger(__name__)
router = APIRouter()
templates = sep_settings.TEMPLATES


@router.get("/", dependencies=[IsAuthenticated], response_class=HTMLResponse)
async def app_index(
    request: Request,
    context: Annotated[dict[str, Any], Depends(get_app_index_context)],
) -> HTMLResponse:
    """Homepage of plugin."""
    return templates.TemplateResponse(
        request=request,
        name="atw/index.html",
        context=context,
    )
