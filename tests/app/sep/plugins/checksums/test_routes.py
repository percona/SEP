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

"""Define tests for the app.sep.plugins.checksums.routes module."""

import pytest
from fastapi import status

from app.sep.connectivity import _fetch_connectivity_result, _LATEST_RESULTS
from app.sep.main import sep_app
from app.sep.plugins.checksums.deps import build_checksums_task_payload
from app.sep.plugins.checksums.models import ChecksumsCreate
from app.tasks.models import TaskBackendEnum, TaskOwner, TaskWrite


@pytest.fixture
def checksums_create():
    """Define a sample ChecksumsCreate form data."""
    return ChecksumsCreate(
        task_name="fake_checksum",
        hostname="localhost",
        service_id=1,
        recursion_method="processlist",
    )


def test_checksums_create_skips_connectivity_check_when_opted_out(
    test_client, mock_task_api_dep, checksums_create
):
    """POST /checksums/ skips the connectivity check when the checkbox is unchecked."""
    _fetch_connectivity_result.cache_clear()
    _LATEST_RESULTS.clear()

    fake_task_write = TaskWrite(
        name="fake_checksum",
        backend=TaskBackendEnum.PROXY,
        owner=TaskOwner.CHECKSUMS,
        data={
            "task": "run-command",
            "meta": {
                "command": "pt-table-checksum",
                "args": "--recursion-method=processlist",
                "target": "node1",
                "_connectivity_host": "10.0.0.1",
                "_connectivity_port": 3306,
                "_connectivity_service_type": "mysql",
            },
        },
    )

    sep_app.dependency_overrides[build_checksums_task_payload] = lambda: fake_task_write

    response = test_client.post(
        "/checksums/", data=checksums_create.model_dump(), follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert (
        response.headers["location"]
        == f"{test_client.base_url}/checksums/{checksums_create.task_name}"
    )

    assert mock_task_api_dep.post.call_count == 1
    call = mock_task_api_dep.post.call_args_list[0]
    assert call.args[0] == "/"
    assert call.kwargs["json"] == fake_task_write.model_dump()
    assert _LATEST_RESULTS == {}

    _fetch_connectivity_result.cache_clear()
    _LATEST_RESULTS.clear()
    sep_app.dependency_overrides = {}
