
"""Define dependencies for MUM plugin."""

import logging
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request
from fastapi.encoders import jsonable_encoder

from app.tasks.models import (
    TaskBackendEnum,
    TaskWrite,
)

logger = logging.getLogger(__name__)

async def get_users(
    request: Request,
) -> TaskWrite:

    requirements = "PyMongo"

    payload_path = Path(__file__).parent / "mum_payload"


    return TaskWrite(
        name="MUM",
        backend=TaskBackendEnum.PROXY,
        owner="MUM",
        data={
            "task": "run-python",
            "meta": {
                "config":
                    jsonable_encoder(request.body, by_alias=False, exclude_none=True),
                "target": "mysql-host",
                "requirements": requirements,
            },
            "payload": f"file://{payload_path}",
        },
    )


GetUserTask = Annotated[TaskWrite, Depends(get_users)]
