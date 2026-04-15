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

import asyncio
import importlib
import io
import logging
import traceback
from collections.abc import AsyncGenerator
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.utils import utc_now
from app.tasks.crud import TaskHistoryManager
from app.tasks.execution.models import BaseExecutor
from app.tasks.logs.log_writer import TaskHistoryLogWriter
from app.tasks.models import (
    FileMetadata,
    Task,
    TaskHistory,
    TaskHistoryStatusEnum,
    TaskLog,
    TaskLogType,
)

logger = logging.getLogger(__name__)

CELERY_CALLABLE_ALLOWED_PREFIX = "app."


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

        Captured ``stdout`` and ``stderr`` are persisted into the
        ``taskhistory_log`` chunk store via
        :class:`~app.tasks.logs.log_writer.TaskHistoryLogWriter` instead of
        being stuffed into ``execution_request.tracking``.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param queue_item: The task history record for tracking this execution.
        :type queue_item: TaskHistory
        :param task: The task to be executed. If ``None``, the queue_item's
            task will be used.
        :type task: Task | None
        :return: The updated task history with execution details.
        :rtype: TaskHistory
        """
        task = task or queue_item.task
        queue_item.started_at = utc_now()
        queue_item.status = TaskHistoryStatusEnum.RUNNING

        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        try:
            result = await self._run_callable(task, stdout_buffer, stderr_buffer)
            stdout_buffer.write(f"\nResult: {result}\n")
            queue_item.status = TaskHistoryStatusEnum.SUCCESS
        except Exception:
            logger.exception("Celery task %s failed", task.name)
            stderr_buffer.write(f"\nError:\n{traceback.format_exc()}")
            queue_item.status = TaskHistoryStatusEnum.FAILED
        finally:
            queue_item.finished_at = utc_now()

        saved = await TaskHistoryManager.save(
            session,
            queue_item,
            flag_modified_fields=["execution_request"],
        )
        stdout_value = stdout_buffer.getvalue()
        stderr_value = stderr_buffer.getvalue()
        if stdout_value:
            await TaskHistoryLogWriter.append(
                session,
                saved.id,
                source="execution",
                stream=TaskLogType.STDOUT,
                new_bytes=stdout_value.encode("utf-8"),
                force_flush=True,
            )
        if stderr_value:
            await TaskHistoryLogWriter.append(
                session,
                saved.id,
                source="execution",
                stream=TaskLogType.STDERR,
                new_bytes=stderr_value.encode("utf-8"),
                force_flush=True,
            )
        return saved

    async def _run_callable(
        self, task: Task, stdout_buffer: io.StringIO, stderr_buffer: io.StringIO
    ) -> Any:
        """Import and invoke the callable specified in the task data.

        Redirect ``sys.stdout`` and ``sys.stderr`` into the provided buffers
        so that output produced by the callable is captured in task logs.
        Support both async and sync callables: async callables are awaited
        directly while sync callables are executed via :func:`asyncio.to_thread`.

        :param task: The task containing the callable path in its data dict.
        :type task: Task
        :param stdout_buffer: A StringIO buffer for capturing standard output.
        :type stdout_buffer: io.StringIO
        :param stderr_buffer: A StringIO buffer for capturing standard error.
        :type stderr_buffer: io.StringIO
        :return: The return value of the callable.
        :rtype: Any
        """
        callable_path = task.data["callable"]
        module_path, func_name = callable_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        func = getattr(module, func_name)
        if not callable(func):
            raise TypeError(f"'{callable_path}' is not callable")
        stdout_buffer.write(f"Executing {callable_path}\n")
        with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
            if asyncio.iscoroutinefunction(func):
                return await func()
            return await asyncio.to_thread(func)

    async def _sync_task_history(
        self,
        queue_item: TaskHistory,
        writer_session: AsyncSession | None = None,  # noqa: ARG002
    ) -> TaskHistory:
        """Return the queue_item unchanged.

        Celery tasks run synchronously within ``dispatch_task``, so no
        additional synchronization is needed. The ``writer_session`` parameter
        is accepted to satisfy the base class contract and intentionally
        ignored.

        :param queue_item: The task history record.
        :type queue_item: TaskHistory
        :param writer_session: Ignored. Present only to match the
            ``BaseExecutor`` signature.
        :type writer_session: AsyncSession | None
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
        """Validate that the job contains a safe, importable callable path.

        Enforce that the callable path starts with the allowed namespace prefix
        to prevent arbitrary code execution.

        :param job: The job specification containing a ``callable`` key.
        :type job: dict[str, Any]
        :return: The original job specification if validation is successful.
        :rtype: dict[str, Any]
        :raises ValueError: If ``callable`` is missing, outside the allowed
            namespace, or not importable.
        """
        callable_path = job.get("callable")
        if not callable_path:
            raise ValueError("Job must contain a 'callable' key")
        if not callable_path.startswith(CELERY_CALLABLE_ALLOWED_PREFIX):
            raise ValueError(
                f"Callable '{callable_path}' is not in the allowed namespace "
                f"'{CELERY_CALLABLE_ALLOWED_PREFIX}'"
            )
        try:
            module_path, func_name = callable_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            func = getattr(module, func_name)
        except (ImportError, AttributeError, ValueError) as exc:
            raise ValueError(f"Cannot import callable '{callable_path}'") from exc
        if not callable(func):
            raise TypeError(f"'{callable_path}' is not callable")
        return job

    def get_hosts(self) -> dict[str, str]:
        """Return the local host as the only available executor host.

        :return: A dictionary with a single ``local`` entry.
        :rtype: dict[str, str]
        """
        return {"local": "localhost"}

    async def stream_logs(
        self,
        queue_item: TaskHistory,  # noqa: ARG002
        start_offsets: dict[str, dict[str, int]] | None = None,  # noqa: ARG002
    ) -> AsyncGenerator[TaskLog, None]:
        """Return an empty live-log stream for Celery tasks.

        Celery tasks finish synchronously inside ``dispatch_task``, so the
        route's live-stream branch (``status == RUNNING``) is unreachable for
        them in practice. Finished Celery log retrieval flows through the
        route's non-``RUNNING`` branch, which now calls
        :func:`iter_task_history_logs` against the chunk store.

        :param queue_item: The task history record. Unused.
        :type queue_item: TaskHistory
        :param start_offsets: Starting offsets. Unused.
        :type start_offsets: dict[str, dict[str, int]] | None
        :return: An empty async generator — Celery live-streaming is
            unreachable.
        :rtype: AsyncGenerator[TaskLog, None]
        """
        return
        yield  # pragma: no cover

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
