"""Define utilities for interacting with Nomad."""

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
    """Validate a Nomad job specification.

    This function sends a job specification to the Nomad backend for validation.
    If validation fails, it raises an HTTPException with the corresponding status code.

    Parameters
    ----------
    job : dict[str, Any]
        The Nomad job specification to validate.

    Returns
    -------
    dict[str, Any]
        The original job specification if validation is successful.

    Raises
    ------
    HTTPException
        If validation fails or Nomad returns an error status code.

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
    """Parse and validate a job spec payload based on its format.

    This function parses the payload according to the specified format
    (HCL, JSON, or YAML) and validates it using the Nomad backend.

    Parameters
    ----------
    payload : str or bytes
        The job specification payload to be parsed.
    payload_format : str
        The format of the payload, which can be "hcl", "json", or "yaml".

    Returns
    -------
    dict[str, Any]
        The parsed and validated job specification.

    Raises
    ------
    ValueError
        If the provided payload format is unsupported.
    HTTPException
        If validation of the job specification fails.

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
