"""Define test cases for the Tasks API app and exception handlers."""

import pytest
from fastapi import HTTPException, status

from app.tasks.execution.exceptions import TaskDataNotFoundInExecutorError
from app.tasks.execution.executors.nomad.exceptions import (
    AllocationNotFoundError,
    JobNotFoundError,
)
from app.tasks.main import task_data_not_found_detail, task_data_not_found_handler


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
    assert detail["executor"] == "nomad"
    assert "No allocations found" in detail["detail"]


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
    assert detail["executor"] == "nomad"
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
    assert detail["executor"] == "nomad"
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
