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

"""Define tests for the app.tasks.main module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, status
from sqlalchemy.dialects.postgresql import JSON, JSONB

from app.tasks.db.seed import verify_taskhistory_execution_request_is_jsonb
from app.tasks.execution.exceptions import TaskDataNotFoundInExecutorError
from app.tasks.execution.executors.nomad.exceptions import (
    AllocationNotFoundError,
    JobNotFoundError,
)
from app.tasks.main import lifespan as tasks_module_lifespan
from app.tasks.main import (
    task_data_not_found_detail,
    task_data_not_found_handler,
    tasks_lifespan,
)


def test_tasks_app_lifespan_is_always_set():
    """Assert ``tasks_lifespan`` is always assigned at module level.

    The lifespan must not be gated behind a ``__name__`` check, because uvicorn
    re-imports the module with ``__name__ == "app.tasks.main"`` rather than
    ``"__main__"``, which would leave the lifespan as ``None``.
    """
    assert tasks_module_lifespan is tasks_lifespan


def test_task_data_not_found_detail_base_exception_without_structured_fields():
    """Assert response detail includes only message when exception has no structured fields."""
    exc = TaskDataNotFoundInExecutorError()
    detail = task_data_not_found_detail(exc)
    assert detail == {
        "message": "The requested task data is no longer available in the executor.",
    }


def test_task_data_not_found_detail_base_exception_with_message_only():
    """Assert response detail includes message and detail when exception has args only."""
    exc = TaskDataNotFoundInExecutorError("Custom message")
    detail = task_data_not_found_detail(exc)
    assert (
        detail["message"]
        == "The requested task data is no longer available in the executor."
    )
    assert detail["detail"] == "Custom message"


def test_task_data_not_found_detail_allocation_not_found_with_structured_fields():
    """Assert response detail includes resource_type and resource_id for AllocationNotFoundError."""
    exc = AllocationNotFoundError(
        'No allocations found with filter JobID == "my-job"',
        executor_name="nomad",
        resource_type="allocation",
        resource_id='JobID == "my-job" and EvalID == "eval-1"',
    )
    detail = task_data_not_found_detail(exc)
    assert (
        detail["message"]
        == "The requested task data is no longer available in the executor."
    )
    assert detail["resource_type"] == "allocation"
    assert detail["resource_id"] == 'JobID == "my-job" and EvalID == "eval-1"'
    assert detail["executor_name"] == "nomad"
    assert "No allocations found" in detail["detail"]
    assert "job_id" not in detail
    assert "evaluation_id" not in detail


def test_task_data_not_found_detail_allocation_includes_job_and_eval_ids():
    """Assert allocation errors can expose job_id and evaluation_id alongside resource fields."""
    exc = AllocationNotFoundError(
        "No allocations",
        executor_name="nomad",
        resource_type="allocation",
        resource_id='JobID == "j1" and EvalID == "e1"',
        job_id="j1",
        evaluation_id="e1",
    )
    detail = task_data_not_found_detail(exc)
    assert detail["job_id"] == "j1"
    assert detail["evaluation_id"] == "e1"


def test_task_data_not_found_detail_job_not_found_with_structured_fields():
    """Assert response detail includes resource_type and resource_id for JobNotFoundError."""
    exc = JobNotFoundError(
        "Job not found in Nomad",
        executor_name="nomad",
        resource_type="job",
        resource_id="job-abc-123",
    )
    detail = task_data_not_found_detail(exc)
    assert (
        detail["message"]
        == "The requested task data is no longer available in the executor."
    )
    assert detail["resource_type"] == "job"
    assert detail["resource_id"] == "job-abc-123"
    assert detail["executor_name"] == "nomad"
    assert "Job not found in Nomad" in detail["detail"]


def test_task_data_not_found_detail_job_not_found_without_resource_id():
    """Assert response detail omits resource_id when not provided (e.g. missing job_id case)."""
    exc = JobNotFoundError(
        "Missing job_id in task history tracking (queue-42)",
        executor_name="nomad",
        resource_type="job",
    )
    detail = task_data_not_found_detail(exc)
    assert detail["resource_type"] == "job"
    assert "resource_id" not in detail
    assert detail["executor_name"] == "nomad"
    assert "queue-42" in detail["detail"]


@pytest.mark.asyncio
async def test_task_data_not_found_handler_raises_410_with_allocation_context():
    """Verify handler raises HTTPException 410 with allocation context for AllocationNotFoundError."""
    exc = AllocationNotFoundError(
        "No allocations found",
        executor_name="nomad",
        resource_type="allocation",
        resource_id="alloc-xyz",
    )
    with pytest.raises(HTTPException) as exc_info:
        await task_data_not_found_handler(None, exc)
    assert exc_info.value.status_code == status.HTTP_410_GONE
    assert exc_info.value.detail["resource_type"] == "allocation"
    assert exc_info.value.detail["resource_id"] == "alloc-xyz"
    assert "message" in exc_info.value.detail


@pytest.mark.asyncio
async def test_task_data_not_found_handler_raises_410_with_job_context():
    """Verify handler raises HTTPException 410 with job context for JobNotFoundError."""
    exc = JobNotFoundError(
        "Job gone",
        executor_name="nomad",
        resource_type="job",
        resource_id="job-123",
    )
    with pytest.raises(HTTPException) as exc_info:
        await task_data_not_found_handler(None, exc)
    assert exc_info.value.status_code == status.HTTP_410_GONE
    assert exc_info.value.detail["resource_type"] == "job"
    assert exc_info.value.detail["resource_id"] == "job-123"
    assert "Job gone" in exc_info.value.detail["detail"]


@pytest.mark.asyncio
async def test_task_data_not_found_handler_raises_410_without_structured_fields():
    """Verify handler raises HTTPException 410 with only message when exception has no structured fields."""
    exc = TaskDataNotFoundInExecutorError("Generic not found")
    with pytest.raises(HTTPException) as exc_info:
        await task_data_not_found_handler(None, exc)
    assert exc_info.value.status_code == status.HTTP_410_GONE
    assert (
        exc_info.value.detail["message"]
        == "The requested task data is no longer available in the executor."
    )
    assert exc_info.value.detail["detail"] == "Generic not found"
    assert "resource_type" not in exc_info.value.detail
    assert "resource_id" not in exc_info.value.detail


def _make_schema_check_engine_mock(dialect_name: str, columns):
    """Build a mock async engine whose inspector returns ``columns``.

    :param dialect_name: The dialect name reported by ``engine.dialect.name``.
    :type dialect_name: str
    :param columns: The list of column dicts returned by
        ``inspect(sync_conn).get_columns("taskhistory")``.
    :type columns: list[dict] | None
    :return: A ``(engine_mock, run_sync_mock)`` pair suitable for patching
        ``app.tasks.db.seed.engine``.
    :rtype: tuple
    """
    engine_mock = MagicMock()
    engine_mock.dialect.name = dialect_name
    conn = AsyncMock()
    run_sync_mock = AsyncMock(return_value=columns)
    conn.run_sync = run_sync_mock
    conn_cm = AsyncMock()
    conn_cm.__aenter__ = AsyncMock(return_value=conn)
    conn_cm.__aexit__ = AsyncMock(return_value=False)
    engine_mock.connect = MagicMock(return_value=conn_cm)
    return engine_mock, run_sync_mock


class TestVerifyTaskHistoryExecutionRequestIsJsonb:
    """Test the SEP-988 startup schema validation guard."""

    @pytest.mark.asyncio
    async def test_raises_when_pg_column_is_plain_json(self):
        """Assert ``RuntimeError`` when PostgreSQL still reports plain ``JSON``.

        Defend against a deploy that ships SEP-988 code without running the
        Alembic migration that converts the column to ``jsonb``.
        """
        engine_mock, run_sync_mock = _make_schema_check_engine_mock(
            "postgresql",
            [{"name": "execution_request", "type": JSON()}],
        )
        with (
            patch("app.tasks.db.seed.engine", engine_mock),
            pytest.raises(RuntimeError, match="JSONB") as exc_info,
        ):
            await verify_taskhistory_execution_request_is_jsonb()
        assert "SEP-988" in str(exc_info.value)
        run_sync_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_passes_when_pg_column_is_jsonb(self):
        """Assert no exception when PostgreSQL reports ``JSONB`` for the column."""
        engine_mock, run_sync_mock = _make_schema_check_engine_mock(
            "postgresql",
            [{"name": "execution_request", "type": JSONB()}],
        )
        with patch("app.tasks.db.seed.engine", engine_mock):
            await verify_taskhistory_execution_request_is_jsonb()
        run_sync_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_is_noop_on_sqlite(self):
        """Assert the guard short-circuits on SQLite without inspecting the schema.

        SEP-988's migration is a no-op on SQLite, and the JSONB type only
        exists in the PostgreSQL dialect, so the function must return before
        running reflection.
        """
        engine_mock, run_sync_mock = _make_schema_check_engine_mock("sqlite", [])
        with patch("app.tasks.db.seed.engine", engine_mock):
            await verify_taskhistory_execution_request_is_jsonb()
        run_sync_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_raises_when_pg_column_missing(self):
        """Assert ``RuntimeError`` when the inspector returns no matching column.

        Cover the case where the table is missing entirely (e.g. migrations
        never ran on a fresh database).
        """
        engine_mock, _ = _make_schema_check_engine_mock("postgresql", [])
        with (
            patch("app.tasks.db.seed.engine", engine_mock),
            pytest.raises(RuntimeError, match="not found"),
        ):
            await verify_taskhistory_execution_request_is_jsonb()
