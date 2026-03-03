# Copyright 2026 Percona LLC
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

"""Define tests for base SEP dependencies."""

from unittest.mock import AsyncMock

import pytest

from app.sep.deps import get_tasks_context


@pytest.mark.asyncio
async def test_get_tasks_context(created_service, created_schema, mock_remote_api):
    """Test for assembling the template context for task-dependent plugins."""
    task_data = {
        "name": "fakeTask",
        "id": 1,
        "created_by": None,
        "last_updated_by": None,
    }
    extra_data = {"success": True, "extra": "extra_data"}
    mock_remote_api.get = AsyncMock(
        side_effect=[
            [created_service.model_dump()],
            created_schema.model_dump(),
            [task_data],  # for /
            [],  # for /{task_name}/history/
            [],  # for /{task_name}/periodic/
        ]
    )

    def get_task_info(_task):
        return extra_data

    context = await get_tasks_context(
        mock_remote_api,
        mock_remote_api,
        get_task_info,
        {"host1": "address1", "host2": "address2"},
    )
    assert context["services"][0]["id"] == created_service.id
    assert context["executor_hosts"] == ["host1", "host2"]
    assert len(context["tasks"]) == 1
    task = context["tasks"][0]
    assert task == task_data | extra_data
