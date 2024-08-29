"""Nomad"""

import json
import logging
from http import HTTPStatus

import yaml
from fastapi import HTTPException

from app.core.utils import async_run
from app.tasks.config import tasks_settings
from nomad import Nomad

logger = logging.getLogger(__name__)


async def transform_payload(payload: str | bytes, payload_format: str) -> str:
    """Parse and validate a job spec payload

    :param payload:
    :param payload_format:
    :return:
    """
    backend = Nomad(
        address=tasks_settings.NOMAD.ENDPOINT,
        secure=tasks_settings.NOMAD.SECURE,
        timeout=tasks_settings.NOMAD.TIMEOUT,
        verify=tasks_settings.NOMAD.VERIFY,
    )

    match payload_format:
        case "hcl":
            result = await async_run(backend.jobs.parse, payload)
            parsed = result[0]
        case "json":
            parsed = json.loads(str(payload))
        case "yaml":
            parsed = yaml.safe_load(payload)
        case _:
            raise ValueError(f"unsupported format: {payload_format}")

    logger.debug("Parsed payload: %s", parsed)

    valid = await async_run(backend.validate.validate_job, {"Job": parsed})
    if valid[0].status_code != 200:
        raise HTTPException(status_code=valid[0].status_code)
    resp = json.loads(valid[0].text)
    if not resp.get("ValidationErrors", []):
        return json.dumps(parsed)
    logger.error(valid[0].text)
    raise HTTPException(status_code=HTTPStatus.BAD_REQUEST)
