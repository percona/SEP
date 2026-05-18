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

"""Define tests for the app.sep.plugins.gascan.routes module."""

from unittest.mock import AsyncMock

from fastapi import status

from app.sep.plugins.gascan.models import GascanCreate
from app.tasks.models import TaskOwner


def test_gascan_create_posts_task_with_gascan_owner(
    test_client,
    mock_task_api_dep,
):
    """Test POST /gascan/ creates a task owned by GASCAN."""
    gascan_create = GascanCreate(
        task_name="gascan_full_chain",
        hostname="localhost",
        playbook="site.yml",
        limit="all",
        override="foo=bar",
    )
    mock_task_api_dep.post.return_value = AsyncMock()

    response = test_client.post(
        "/gascan/",
        data=gascan_create.model_dump(exclude_none=True),
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"].endswith("/gascan/gascan_full_chain")
    mock_task_api_dep.post.assert_awaited_once()
    posted = mock_task_api_dep.post.await_args.kwargs["json"]
    assert posted["name"] == "gascan_full_chain"
    assert posted["owner"] == TaskOwner.GASCAN.value
    assert posted["data"]["meta"]["command"] == "gascan"
