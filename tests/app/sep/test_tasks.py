"""Define tests for app.sep.tasks module."""

from app.sep.tasks import EnhancedPeriodicTaskCreateRequest, PeriodicTaskRequest


def test_periodic_task_request_populates_execute_request_from_prefixed_fields() -> None:
    """Test that PeriodicTaskRequest parses execute_request_ prefixed fields."""
    data = {
        "interval_every": "5",
        "interval_period": "minutes",
        "execute_request_chain_task_names": '["other-task"]',
    }

    request = PeriodicTaskRequest.model_validate(data)

    assert request.execute_request is not None
    assert request.execute_request.chain_task_names == ["other-task"]


def test_periodic_task_request_without_execute_request_prefix_leaves_none() -> None:
    """Test that PeriodicTaskRequest leaves execute_request None when no prefix fields."""
    data = {
        "interval_every": "5",
        "interval_period": "minutes",
    }

    request = PeriodicTaskRequest.model_validate(data)

    assert request.execute_request is None


def test_enhanced_periodic_task_create_request_still_works_with_chain_task_names() -> (
    None
):
    """Test that EnhancedPeriodicTaskCreateRequest populates chain_task_names."""
    data = {
        "task": "my-task",
        "interval_every": "10",
        "interval_period": "hours",
        "execute_request_chain_task_names": '["chain-task"]',
    }

    request = EnhancedPeriodicTaskCreateRequest.model_validate(data)

    assert request.execute_request is not None
    assert request.execute_request.chain_task_names == ["chain-task"]
