"""Define tests for app.tasks.execution.executors.nomad.models._sync_task_history."""

from unittest.mock import call, MagicMock

import pytest

from app.tasks.execution.executors.nomad.models import (
    NOMAD_DEAD_JOB_STATUS,
    NomadExecutor,
)
from app.tasks.models import TaskHistoryStatusEnum


def _make_alloc(job_id: str = "job-1", client_status: str = "complete") -> dict:
    """Return a minimal Nomad allocation dict."""
    return {
        "ID": "alloc-1",
        "JobID": job_id,
        "EvalID": "eval-1",
        "TaskStates": {"step1": {}},
        "ClientStatus": client_status,
        "ModifyTime": 1700000000000000000,
    }


def _make_queue_item() -> MagicMock:
    """Return a minimal TaskHistory-like mock in RUNNING state."""
    queue_item = MagicMock()
    queue_item.status = TaskHistoryStatusEnum.RUNNING
    queue_item.task_logs = {}
    queue_item.anonymized_entities = set()
    queue_item.execution_request.tracking = {}
    return queue_item


@pytest.mark.asyncio
async def test_dead_job_calls_get_logs_for_allocation_twice():
    """When the Nomad job is dead, get_logs_for_allocation must be called twice.

    The second call receives the first call's result as ``initial_logs`` so that
    any stdout bytes still in Nomad's buffer at task completion are captured.
    """
    alloc = _make_alloc()
    first_logs = {"step1": {"stdout": "initial log lines\n"}}
    second_logs = {"step1": {"stdout": "initial log lines\nfinal buffered lines\n"}}

    executor = MagicMock()
    executor.get_allocation_for_task_history.return_value = alloc
    executor.get_logs_for_allocation.side_effect = [first_logs, second_logs]
    executor.get_job.return_value = {"Status": NOMAD_DEAD_JOB_STATUS, "Stop": False}
    executor.get_task_history_status_from_alloc_status.return_value = (
        TaskHistoryStatusEnum.SUCCESS
    )
    executor.timestamp_to_datetime.return_value = MagicMock()

    queue_item = _make_queue_item()
    await NomadExecutor._sync_task_history(executor, queue_item)

    assert executor.get_logs_for_allocation.call_count == 2  # noqa: PLR2004
    _, second_call = executor.get_logs_for_allocation.call_args_list
    # The second call must pass the first call's result as initial_logs.
    assert second_call == call(alloc, first_logs, queue_item.anonymized_entities)


@pytest.mark.asyncio
async def test_running_job_calls_get_logs_for_allocation_once():
    """When the Nomad job is still running, get_logs_for_allocation is called once."""
    alloc = _make_alloc()
    logs = {"step1": {"stdout": "partial logs\n"}}

    executor = MagicMock()
    executor.get_allocation_for_task_history.return_value = alloc
    executor.get_logs_for_allocation.return_value = logs
    executor.get_job.return_value = {"Status": "running"}

    queue_item = _make_queue_item()
    await NomadExecutor._sync_task_history(executor, queue_item)

    executor.get_logs_for_allocation.assert_called_once()
