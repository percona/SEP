"""Define base executor models for the Tasks API."""

import json
import logging
from abc import ABC
from abc import abstractmethod
from typing import Any

import yaml
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.utils import async_run
from app.tasks.models import TaskHistory

logger = logging.getLogger(__name__)


class BaseExecutor(BaseModel, ABC):
    """Define the blueprint of a task executor.

    Attributes
    ----------
    wait_interval : int, optional
        The interval in seconds between status checks. Defaults to 5 seconds.

    """

    wait_interval: int = 5

    async def transform_payload(
        self,
        payload: str | bytes,
        payload_format: str,
    ) -> dict[str, Any]:
        """Parse and validate a job spec payload based on its format.

        This function parses the payload according to the specified format
        (HCL, JSON, or YAML) and validates it using the backend.

        :param payload: The job specification payload to be parsed.
        :type payload: str | bytes
        :param payload_format: The format of the payload, which can be "hcl", "json",
            or "yaml".
        :type payload_format: str
        :return: The parsed and validated job specification.
        :rtype: dict[str, Any]
        :raises ValueError: If the provided payload format is unsupported.
        :raises HTTPException: If validation of the job specification fails.
        """
        match payload_format:
            case "hcl":
                result = await async_run(self.backend.jobs.parse, payload)
                parsed = result[0]
            case "json":
                parsed = json.loads(str(payload))
            case "yaml":
                parsed = yaml.safe_load(payload)
            case _:
                raise ValueError(f"unsupported format: {payload_format}")

        logger.debug("Parsed payload: %s", parsed)
        return await self.validate_job(parsed)

    @abstractmethod
    async def run(
        self,
        session: AsyncSession,
        queue_item: TaskHistory,
    ) -> TaskHistory:
        """Run a task and update the related task history.

        Parameters
        ----------
        session : AsyncSession
            The SQLAlchemy asynchronous session to use for database operations.
        queue_item : TaskHistory
            The task history record for tracking this execution.

        Returns
        -------
        TaskHistory
            The updated task history with execution details.

        """

    # TODO: Use pydantic models instead of dict for job validation
    @abstractmethod
    async def validate_job(self, job: dict[str, Any]) -> dict[str, Any]:
        """Validate a job specification.

        Parameters
        ----------
        job : dict[str, Any]
            The job specification to validate.

        Returns
        -------
        dict[str, Any]
            The original job specification if validation is successful.

        """

    @abstractmethod
    def get_hosts(self) -> list[str]:
        """Get the list of valid executor hosts."""
