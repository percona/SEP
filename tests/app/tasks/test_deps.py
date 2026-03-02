"""Define tests for the task dependencies."""

import pytest

from app.tasks.deps import prepare_task_history
from app.tasks.models import Task, TaskBackendEnum, TaskExecuteRequest
from tests.app.factories import TaskFactory


@pytest.fixture
def proxy_task() -> Task:
    """Return a fake PROXY task (not persisted)."""
    return TaskFactory.build(
        name="test-task",
        backend=TaskBackendEnum.PROXY,
        data={"meta": {"target": "host1"}, "payload": None},
    )


def test_prepare_task_history_injects_chain_task_name(proxy_task: Task) -> None:
    """Test that prepare_task_history stores chain_task_name in meta when set."""
    execution_data = TaskExecuteRequest(chain_task_name="other-task")

    history = prepare_task_history(
        task=proxy_task,
        executed_by="test-user",
        execution_data=execution_data,
    )

    assert history.execution_request.meta.get("chain_task_name") == "other-task"


def test_prepare_task_history_no_chain_task_name_not_injected(proxy_task: Task) -> None:
    """Test that prepare_task_history does not add chain_task_name when not set."""
    execution_data = TaskExecuteRequest()

    history = prepare_task_history(
        task=proxy_task,
        executed_by="test-user",
        execution_data=execution_data,
    )

    assert "chain_task_name" not in history.execution_request.meta


def test_prepare_task_history_chain_task_name_overrides_task_meta(
    proxy_task: Task,
) -> None:
    """Test that per-execution chain_task_name overrides the task's meta chain_task_name."""
    proxy_task.data["meta"]["chain_task_name"] = "meta-task"
    execution_data = TaskExecuteRequest(chain_task_name="override-task")

    history = prepare_task_history(
        task=proxy_task,
        executed_by="test-user",
        execution_data=execution_data,
    )

    assert history.execution_request.meta.get("chain_task_name") == "override-task"
