"""Nomad"""

import json
import logging
from http import HTTPStatus
from typing import Any

import yaml
from fastapi import HTTPException

from app.core.utils import async_run
from app.tasks.config import tasks_settings
from nomad import Nomad

logger = logging.getLogger(__name__)


# TODO: Use pydantic models instead of dict for job validation
async def validate_job(job: dict[str, Any]) -> dict[str, Any]:
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
        cert=tasks_settings.NOMAD.CERT,
    )
    valid = await async_run(backend.validate.validate_job, {"Job": job})
    if valid[0].status_code != 200:
        raise HTTPException(status_code=valid[0].status_code)
    resp = json.loads(valid[0].text)
    if not resp.get("ValidationErrors", []):
        return job
    logger.error(valid[0].text)
    raise HTTPException(status_code=HTTPStatus.BAD_REQUEST)


async def transform_payload(
    payload: str | bytes,
    payload_format: str,
) -> dict[str, Any]:
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
        cert=tasks_settings.NOMAD.CERT,
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
    return await validate_job(parsed)
