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

"""Define tests for the app.sep.plugins.checksums.deps module."""

import shlex
from unittest.mock import AsyncMock

import pytest

from app.sep.plugins.checksums.deps import (
    build_checksums_task_payload,
    DEFAULT_RECURSION_DSN_TABLE,
)
from app.sep.plugins.checksums.models import ChecksumsCreate
from app.tasks.models import TaskOwner, TaskWrite


@pytest.mark.asyncio
async def test_build_checksums_task_payload_dsn_recursion_defaults_empty_dsn_table(
    created_service,
    mock_remote_api,
):
    """Assert blank dsn_table defaults to D=percona,t=dsns in checksums command."""
    mock_remote_api.get = AsyncMock(return_value=created_service.model_dump())
    created_checksums = ChecksumsCreate(
        task_name="checksums-test",
        hostname="localhost",
        service_id=created_service.id,
        recursion_method="dsn",
        dsn_table="",
    )

    generated_task = await build_checksums_task_payload(
        created_checksums,
        mock_remote_api,
    )

    assert isinstance(generated_task, TaskWrite)
    assert generated_task.owner == TaskOwner.CHECKSUMS
    args = shlex.split(generated_task.data["meta"]["args"])
    recursion_arg = next(
        (arg for arg in args if arg.startswith("--recursion-method=")),
        "",
    )
    assert recursion_arg
    assert DEFAULT_RECURSION_DSN_TABLE in recursion_arg
