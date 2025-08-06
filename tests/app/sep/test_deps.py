"""Define tests for base SEP dependencies."""

from unittest.mock import AsyncMock

import pytest

from app.sep.deps import get_tasks_context


@pytest.mark.asyncio
async def test_get_tasks_context(
    dummy_request, created_service, created_schema, mock_remote_api
):
    """Test for assembling the template context for task-dependent plugins."""
    task_data = {"name": "fakeTask", "id": 1}
    extra_data = {"success": True, "extra": "extra_data"}
    mock_remote_api.get = AsyncMock(
        side_effect=[
            [created_service.model_dump()],
            created_schema.model_dump(),
            [task_data],  # for /
            [],  # for /{task_name}/history/
            [],  # for /{task_name}/periodic/
            {"address1": "host1", "address2": "host2"},  # for /hosts/
        ]
    )

    def get_task_info(_task):
        return extra_data

    context = await get_tasks_context(
        dummy_request, mock_remote_api, mock_remote_api, get_task_info
    )
    assert context["services"][0]["id"] == created_service.id
    assert context["executor_hosts"] == ["host1", "host2"]
    assert len(context["tasks"]) == 1
    task = context["tasks"][0]
    assert task == task_data | extra_data
