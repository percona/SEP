"""
Nomad
"""
import json

import requests
import yaml

from nomad import Nomad
from tornado.options import options

from sep.core.utils import async_run


async def transform_payload(payload: str | bytes, payload_format: str, session: requests.Session) -> str:
    """Parse and validate a job spec payload

    :param payload:
    :param payload_format:
    :param session:
    :return:
    """

    backend_config = options.modules["nomad"]["backend"]
    backend_config["session"] = session
    backend = Nomad(**backend_config)

    match payload_format:
        case "hcl":
            result = await async_run(
               backend.jobs.parse,
               payload
            )
            parsed = result[0]
        case "json":
            parsed = json.loads(str(payload))
        case "yaml":
            parsed = yaml.safe_load(payload)
        case _:
            raise ValueError(f"unsupported format: {payload_format}")

    output = ""
    valid = await async_run(backend.validate.validate_job, {"job": parsed})
    if valid:
        output = json.dumps(parsed)
    return output
