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

import contextlib
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core.utils import async_run


def sample_func(x, y):
    """Return the sum of two numbers."""
    return x + y


def sample_kwargs_func(x, *, multiplier=1):
    """Return `x` multiplied by `multiplier`."""
    return x * multiplier


def error_func():
    """Raise a ValueError."""
    raise ValueError("Test error")


@pytest.mark.parametrize(
    ("func", "args", "expected", "expectation"),
    [
        (sample_func, (2, 3), 5, contextlib.nullcontext()),
        (
            error_func,
            (),
            None,
            pytest.raises(ValueError, match="Test error"),
        ),
    ],
    ids=["happy-path", "error"],
)
@pytest.mark.asyncio
async def test_async_run(mocker, func, args, expected, expectation):
    """Assert async_run returns the direct result of the callable."""
    mocker.patch(
        "app.core.utils.async_run.ProcessPoolExecutor",
        ThreadPoolExecutor,
    )
    with expectation:
        assert await async_run(func, *args) == expected


@pytest.mark.asyncio
async def test_async_run_with_kwargs(mocker):
    """Assert async_run forwards keyword arguments to the callable."""
    mocker.patch(
        "app.core.utils.async_run.ProcessPoolExecutor",
        ThreadPoolExecutor,
    )
    result = await async_run(sample_kwargs_func, 4, multiplier=3)
    expected_result = 12
    assert result == expected_result
