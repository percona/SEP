"""
Auditing
"""
from typing import Annotated
from fastapi import (
    BackgroundTasks,
    Body,
    FastAPI,
)
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
)
from tornado.log import app_log

__all__ = ["auditor_app"]

auditor_app = FastAPI()


class AuditItem(BaseModel):
    """AuditItem model"""

    model_config = ConfigDict(strict=True)

    data: dict


def record_item(item: AuditItem):
    """Record an item"""
    # TODO: decide where to store the audit information
    app_log.debug("recording item: %r", item)


@auditor_app.post(path="/", response_class=JSONResponse)
async def record(item: Annotated[AuditItem, Body()], background_tasks: BackgroundTasks):
    """Record an audit event"""
    background_tasks.add_task(record_item, item)
    return {"message": "item in queue"}
