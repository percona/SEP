"""Define tests for Nomad executor security-sensitive helpers."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException, status

from app.tasks.execution.executors.nomad.models import NomadExecutor


@pytest.fixture
def nomad_executor() -> NomadExecutor:
    """Create a NomadExecutor instance for helper-level tests."""
    return NomadExecutor(endpoint="http://127.0.0.1:4646")


def _queue_item_with_nomad_variable(path: str = "sep/runtime/mum/job-1") -> SimpleNamespace:
    return SimpleNamespace(
        execution_request=SimpleNamespace(
            meta={
                "config_nomad_variable": path,
                "config_nomad_variable_namespace": "default",
            }
        )
    )


@pytest.mark.asyncio
async def test_cleanup_nomad_variable_clears_meta_after_success(nomad_executor, mocker):
    """Cleanup should remove variable references after successful deletion."""
    queue_item = _queue_item_with_nomad_variable()
    mock_delete = mocker.AsyncMock(return_value=None)
    mocker.patch.object(NomadExecutor, "delete_nomad_variable", mock_delete)

    await nomad_executor._cleanup_nomad_variable(queue_item)

    mock_delete.assert_awaited_once()
    assert mock_delete.await_args.kwargs == {
        "path": "sep/runtime/mum/job-1",
        "namespace": "default",
    }
    assert queue_item.execution_request.meta.get("config_nomad_variable") is None
    assert (
        queue_item.execution_request.meta.get("config_nomad_variable_namespace")
        is None
    )


@pytest.mark.asyncio
async def test_cleanup_nomad_variable_keeps_meta_when_delete_fails(
    nomad_executor, mocker
):
    """Cleanup should keep variable references when deletion fails."""
    queue_item = _queue_item_with_nomad_variable()
    mock_delete = mocker.AsyncMock(
        side_effect=HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="boom",
        )
    )
    mocker.patch.object(NomadExecutor, "delete_nomad_variable", mock_delete)

    await nomad_executor._cleanup_nomad_variable(queue_item)

    assert queue_item.execution_request.meta["config_nomad_variable"] == (
        "sep/runtime/mum/job-1"
    )
    assert queue_item.execution_request.meta["config_nomad_variable_namespace"] == (
        "default"
    )


def test_task_context_started_detection():
    """Task context should be considered started once tasks move past pending."""
    assert not NomadExecutor._task_context_started(
        {"run-script": {"State": "pending", "StartedAt": None}}
    )
    assert NomadExecutor._task_context_started(
        {"run-script": {"State": "running", "StartedAt": None}}
    )
