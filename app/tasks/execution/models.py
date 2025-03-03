"""Define base executor models for the Tasks API."""

import json
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any

import yaml
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils import async_run
from app.tasks.models import Task, TaskHistory, TaskLog

logger = logging.getLogger(__name__)


class BaseExecutor(BaseCaseInsensitiveModel, ABC):
    """Define the blueprint of a task executor.

    :param wait_interval: The interval in seconds between status checks.
        Defaults to 5 seconds.
    :type wait_interval: int
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
        task: Task | None = None,
    ) -> TaskHistory:
        """Run a task and update the related task history.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param queue_item: The task history record for tracking this execution.
        :type queue_item: TaskHistory
        :param task: The task to be executed. If None, the queue_item's task will be
            used.
        :type task: Task | None
        :return: The updated task history with execution details.
        :rtype: TaskHistory
        """

    # TODO: Use pydantic models instead of dict for job validation  # noqa: TD002, TD003
    @abstractmethod
    async def validate_job(self, job: dict[str, Any]) -> dict[str, Any]:
        """Validate a job specification.

        :param job: The job specification to validate.
        :type job: dict[str, Any]
        :return: The original job specification if validation is successful.
        :rtype: dict[str, Any]
        """

    @abstractmethod
    def get_hosts(self) -> dict[str, str]:
        """Get the list of valid executor hosts.

        :return: A dictionary with host addresses as key and the respective hostnames
            as values.
        :rtype: list[str]
        """

    @abstractmethod
    async def stream_logs(
        self, queue_item: TaskHistory
    ) -> AsyncGenerator[TaskLog, None]:
        """Stream logs from a task history record.

        Retrieves the allocation details and concurrently streams stdout and stderr logs
        for each task step. Yields `TaskLog` instances as log lines are received.

        :param queue_item: The task history record for tracking the logs.
        :type queue_item: TaskHistory
        :yield: `TaskLog` instances containing log messages.
        :rtype: TaskLog
        """

    @abstractmethod
    async def is_task_running(self, queue_item: TaskHistory) -> bool:
        """Check if a TaskHistory is currently running.

        :param queue_item: The task history record to check.
        :type queue_item: TaskHistory
        :return: A boolean indicating if the task history is currently running.
        :rtype: bool
        """
