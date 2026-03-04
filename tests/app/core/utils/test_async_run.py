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

"""Define tests for the app.core.utils.async_run module."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from app.core.utils import async_run


def sample_func(x, y):
    """Sample function that returns the sum of two numbers."""
    return x + y


def error_func():
    """Sample function that raises a ValueError."""
    raise ValueError("Test error")


@pytest.mark.asyncio
async def test_async_run(mocker):
    """Test async_run utility with different function scenarios."""
    # Use ThreadPoolExecutor so tests do not spawn processes (avoids sandbox/CI limits).
    mocker.patch(
        "app.core.utils.async_run.ProcessPoolExecutor",
        ThreadPoolExecutor,
    )
    result = await async_run(sample_func, 2, 3)
    expected_result = 5
    assert result[0] == expected_result

    with pytest.raises(ValueError, match="Test error"):
        await async_run(error_func)


@pytest.mark.asyncio
async def test_async_run_timeout(mocker):
    """Test that async_run returns None when a TimeoutError is raised."""
    mocker.patch(
        "app.core.utils.async_run.ProcessPoolExecutor",
        ThreadPoolExecutor,
    )
    mocker.patch("asyncio.get_running_loop", new=MagicMock(side_effect=TimeoutError))
    result = await async_run(lambda: None)
    assert result is None
