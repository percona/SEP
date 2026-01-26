"""Dependencies for the Dipper plugin."""

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request
from pydantic import ValidationError
from starlette import status

from app.core.exceptions import HTTPBadRequestException, HTTPNotFoundException
from app.core.utils import remove_falsy_values_from_dict
from app.inventory.models import ServiceTypeEnum
from app.sep.deps import CreatedServiceDep, CurrentUser, ExecutorHosts, get_base_url
from app.sep.plugins.dipper.constants import (
    CollectorTypeEnum,
    DIPPER_PMM_SCRIPT_BY_SERVICE_TYPE,
    DIPPER_SCRIPT_BY_SERVICE_TYPE,
)
from app.sep.plugins.dipper.models import DipperScript
from app.sep.snippets.config import snippets_settings
from app.sep.snippets.models.snippet import BaseSnippetArgs, SnippetExecutionMeta

logger = logging.getLogger(__name__)


def get_dipper_script_filename(
    service_type: ServiceTypeEnum,
    collector_type: CollectorTypeEnum = CollectorTypeEnum.ENVIRONMENT,
) -> str:
    """Return the payload script filename for a given service type and collector type.

    :param service_type: The service type enum.
    :type service_type: ServiceTypeEnum
    :param collector_type: The collector type (environment or pmm).
    :type collector_type: CollectorTypeEnum
    :return: The filename of the corresponding Dipper payload script.
    :rtype: str
    :raises HTTPNotFoundException: If no script is found for the given service type.
    """
    script_map = (
        DIPPER_PMM_SCRIPT_BY_SERVICE_TYPE
        if collector_type == CollectorTypeEnum.PMM
        else DIPPER_SCRIPT_BY_SERVICE_TYPE
    )
    try:
        return script_map[service_type]
    except KeyError as exc:
        raise HTTPNotFoundException from exc


def has_pmm_script(service_type: ServiceTypeEnum) -> bool:
    """Check if a PMM collector script exists for the given service type.

    :param service_type: The service type enum.
    :type service_type: ServiceTypeEnum
    :return: True if a PMM script exists for the service type, False otherwise.
    :rtype: bool
    """
    return service_type in DIPPER_PMM_SCRIPT_BY_SERVICE_TYPE


async def get_dipper_script(
    service: CreatedServiceDep,
    collector_type: Annotated[
        CollectorTypeEnum, Query()
    ] = CollectorTypeEnum.ENVIRONMENT,
) -> DipperScript:
    """Resolve and load the payload script for the selected service.

    :param service: The selected service.
    :type service: CreatedServiceDep
    :param collector_type: The collector type (environment or pmm).
    :type collector_type: CollectorTypeEnum
    :return: The DipperScript instance for the selected service.
    :rtype: DipperScript
    """
    filename = get_dipper_script_filename(service.type, collector_type)
    try:
        return await DipperScript.from_path(filename)
    except FileNotFoundError as exc:
        logger.warning("Missing dipper payload script %r", filename)
        raise HTTPNotFoundException from exc


DipperScriptDep = Annotated[DipperScript, Depends(get_dipper_script)]


async def get_dipper_script_with_meta(script: DipperScriptDep) -> DipperScript:
    """Load the payload script along with its metadata.

    This dependency ensures that the script's metadata is retrieved and up to date.

    :return The DipperScript instance with updated metadata.
    :rtype: DipperScript
    """
    await script.update_meta()
    return script


DipperScriptWithMetaDep = Annotated[DipperScript, Depends(get_dipper_script_with_meta)]


def get_dipper_script_source(request: Request, script: DipperScriptDep) -> str:
    """Build the absolute URL used by Nomad hosts to download the payload script."""
    dipper_path = request.url_for("dipper_files", path=script.filename).path
    base_url = snippets_settings.SNIPPETS_BASE_URL or get_base_url(request)
    return str(base_url.replace(path=dipper_path))


async def get_dipper_execution_args(
    request: Request, script: DipperScriptWithMetaDep
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
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid execution parameters",
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
    script: DipperScriptWithMetaDep,
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
        requirements=script.requirements,
    )
