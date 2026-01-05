"""Dependencies for the Dipper plugin."""

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from pydantic import ValidationError

from app.core.exceptions import HTTPBadRequestException, HTTPNotFoundException
from app.core.utils import remove_falsy_values_from_dict
from app.inventory.models import ServiceTypeEnum
from app.sep.deps import CreatedServiceDep, CurrentUser, ExecutorHosts, get_base_url
from app.sep.plugins.dipper.constants import (
    DIPPER_SCRIPT_BY_SERVICE_TYPE,
    DIPPER_SUPPORTED_SERVICE_TYPES,
)
from app.sep.plugins.dipper.models import DipperScript
from app.sep.snippets.config import snippets_settings
from app.sep.snippets.models.snippet import BaseSnippetArgs, SnippetExecutionMeta

logger = logging.getLogger(__name__)


def get_dipper_script_filename(service_type: ServiceTypeEnum) -> str:
    """Return the payload script filename for a given service type."""
    if service_type not in DIPPER_SUPPORTED_SERVICE_TYPES:
        raise HTTPNotFoundException
    try:
        return DIPPER_SCRIPT_BY_SERVICE_TYPE[service_type]
    except KeyError as exc:
        raise HTTPNotFoundException from exc


async def get_dipper_script(service: CreatedServiceDep) -> DipperScript:
    """Resolve and load the payload script for the selected service."""
    filename = get_dipper_script_filename(service.type)
    try:
        return await DipperScript.from_filename(filename)
    except FileNotFoundError as exc:
        logger.warning("Missing dipper payload script %r", filename)
        raise HTTPNotFoundException from exc


DipperScriptDep = Annotated[DipperScript, Depends(get_dipper_script)]


def get_dipper_script_source(request: Request, script: DipperScriptDep) -> str:
    """Build the absolute URL used by Nomad hosts to download the payload script."""
    dipper_path = request.url_for("dipper_files", path=script.filename).path
    base_url = snippets_settings.SNIPPETS_BASE_URL or get_base_url(request)
    return str(base_url.replace(path=dipper_path))


async def get_dipper_execution_args(
    request: Request, script: DipperScriptDep
) -> BaseSnippetArgs:
    """Validate execution parameters for the selected payload script."""
    execution_model = script.get_execution_model()
    async with request.form() as form:
        form_data = dict(form)
    logger.info("Form data: %s", form_data)
    try:
        return execution_model.model_validate(remove_falsy_values_from_dict(form_data))
    except ValidationError as exc:
        logger.debug("Invalid execution args: %s", exc.errors())
        raise HTTPException(
            status_code=422, detail="Invalid execution parameters"
        ) from None


def resolve_executor_host_for_service(
    executor_hosts: ExecutorHosts, service: CreatedServiceDep
) -> str | None:
    """Best-effort mapping between an inventory service and a Nomad client hostname."""
    hostnames = set(executor_hosts.keys())
    candidates = []
    if service.node:
        candidates.extend([service.node.name, service.node.address])
    candidates.append(service.name)
    for candidate in candidates:
        if candidate and candidate in hostnames:
            return candidate
    return None


def get_dipper_execution_meta(
    user: CurrentUser,
    service: CreatedServiceDep,
    executor_hosts: ExecutorHosts,
    script: DipperScriptDep,
    script_source: Annotated[str, Depends(get_dipper_script_source)],
    execution_args: Annotated[BaseSnippetArgs, Depends(get_dipper_execution_args)],
) -> SnippetExecutionMeta:
    """Create the exec-artifact task metadata payload for Dipper executions."""
    resolved_host = resolve_executor_host_for_service(executor_hosts, service)
    snippet_filename = f"dipper/{service.id}/{script.filename}"
    target = resolved_host or execution_args.executor_host
    interpreter = script.execution_interpreter
    if interpreter is None:
        raise HTTPBadRequestException(detail="No interpreter configured for script")
    return SnippetExecutionMeta(
        target=target,
        interpreter=interpreter,
        snippet_source=script_source,
        access_token=user.access_token,
        snippet_filename=snippet_filename,
        md5_checksum=script.md5_digest,
        args=execution_args.to_args_string(),
    )
