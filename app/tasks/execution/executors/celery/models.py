# Copyright (C) 2026 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Provide task execution management for Celery-based tasks."""

import importlib
import io
import logging
import traceback
from collections.abc import AsyncGenerator
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.utils import utc_now
from app.tasks.crud import TaskHistoryManager
from app.tasks.execution.models import BaseExecutor
from app.tasks.models import (
    FileMetadata,
    Task,
    TaskHistory,
    TaskHistoryStatusEnum,
    TaskLog,
)

logger = logging.getLogger(__name__)


class CeleryExecutor(BaseExecutor):
    """Execute tasks as Python callables directly in the Celery worker process.

    Unlike the NomadExecutor which dispatches jobs to a remote Nomad cluster,
    the CeleryExecutor imports and calls a Python callable synchronously within
    ``dispatch_task``, updating the TaskHistory to SUCCESS or FAILED before
    returning.

    :param wait_interval: The interval in seconds between status checks.
        Defaults to 5 seconds.
    :type wait_interval: int
    """

    async def dispatch_task(
        self,
        session: AsyncSession,
        queue_item: TaskHistory,
        task: Task | None = None,
    ) -> TaskHistory:
        """Import and execute the callable specified in the task data.

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
        task = task or queue_item.task
        queue_item.started_at = utc_now()
        queue_item.status = TaskHistoryStatusEnum.RUNNING

        log_buffer = io.StringIO()
        try:
            result = await self._run_callable(task, log_buffer)
            log_buffer.write(f"\nResult: {result}\n")
            queue_item.status = TaskHistoryStatusEnum.SUCCESS
        except Exception:
            logger.exception("Celery task %s failed", task.name)
            log_buffer.write(f"\nError:\n{traceback.format_exc()}")
            queue_item.status = TaskHistoryStatusEnum.FAILED
        finally:
            queue_item.finished_at = utc_now()
            queue_item.execution_request.tracking["task_logs"] = {
                "execution": {
                    "stdout": log_buffer.getvalue(),
                    "stderr": "",
                }
            }

        return await TaskHistoryManager.save(
            session,
            queue_item,
            flag_modified_fields=["execution_request"],
        )

    async def _run_callable(self, task: Task, log_buffer: io.StringIO) -> Any:
        """Import and invoke the callable specified in the task data.

        :param task: The task containing the callable path in its data dict.
        :type task: Task
        :param log_buffer: A StringIO buffer for capturing log output.
        :type log_buffer: io.StringIO
        :return: The return value of the callable.
        :rtype: Any
        """
        callable_path = task.data["callable"]
        module_path, func_name = callable_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        func = getattr(module, func_name)
        log_buffer.write(f"Executing {callable_path}\n")
        return await func()

    async def _sync_task_history(
        self,
        queue_item: TaskHistory,
    ) -> TaskHistory:
        """Return the queue_item unchanged.

        Celery tasks run synchronously within ``dispatch_task``, so no
        additional synchronization is needed.

        :param queue_item: The task history record.
        :type queue_item: TaskHistory
        :return: The unchanged task history.
        :rtype: TaskHistory
        """
        return queue_item

    async def _stop_task(self, queue_item: TaskHistory) -> None:
        """No-op for Celery tasks.

        Celery tasks run synchronously and cannot be stopped mid-execution.

        :param queue_item: The task history record.
        :type queue_item: TaskHistory
        """

    async def validate_job(self, job: dict[str, Any]) -> dict[str, Any]:
        """Validate that the job contains an importable callable path.

        :param job: The job specification containing a ``callable`` key.
        :type job: dict[str, Any]
        :return: The original job specification if validation is successful.
        :rtype: dict[str, Any]
        :raises ValueError: If ``callable`` is missing or not importable.
        """
        callable_path = job.get("callable")
        if not callable_path:
            raise ValueError("Job must contain a 'callable' key")
        try:
            module_path, func_name = callable_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            getattr(module, func_name)
        except (ImportError, AttributeError, ValueError) as exc:
            raise ValueError(f"Cannot import callable '{callable_path}'") from exc
        return job

    def get_hosts(self) -> dict[str, str]:
        """Return the local host as the only available executor host.

        :return: A dictionary with a single ``local`` entry.
        :rtype: dict[str, str]
        """
        return {"local": "localhost"}

    async def stream_logs(
        self,
        queue_item: TaskHistory,
        start_offsets: dict[str, dict[str, int]] | None = None,
    ) -> AsyncGenerator[TaskLog, None]:
        """Yield task logs from the stored task_logs in the execution request.

        :param queue_item: The task history record.
        :type queue_item: TaskHistory
        :param start_offsets: Starting offsets for each step and log type.
        :type start_offsets: dict[str, dict[str, int]] | None
        :yield: TaskLog instances containing log chunks.
        :rtype: AsyncGenerator[TaskLog, None]
        """
        for log in queue_item.iter_logs(start_offsets=start_offsets):
            yield log

    async def stream_file(
        self,
        queue_item: TaskHistory,  # noqa: ARG002
        path: str,  # noqa: ARG002
        chunk_size: int = 1024 * 1024,  # noqa: ARG002
    ) -> AsyncGenerator[bytes, None]:
        """Raise NotImplementedError.

        Celery tasks do not produce downloadable files.

        :param queue_item: The task history record.
        :type queue_item: TaskHistory
        :param path: The path to the file.
        :type path: str
        :param chunk_size: The chunk size in bytes.
        :type chunk_size: int
        :raises NotImplementedError: Always.
        """
        raise NotImplementedError("File streaming is not supported for Celery tasks")
        yield  # pragma: no cover

    async def list_files(
        self,
        queue_item: TaskHistory,
        path: str,
    ) -> dict[str, FileMetadata]:
        """Raise NotImplementedError.

        Celery tasks do not produce downloadable files.

        :param queue_item: The task history record.
        :type queue_item: TaskHistory
        :param path: The path to list files from.
        :type path: str
        :raises NotImplementedError: Always.
        """
        raise NotImplementedError("File listing is not supported for Celery tasks")
