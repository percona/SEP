"""Define tests for the app.core.utils.async_run module."""

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
async def test_async_run():
    """Test async_run utility with different function scenarios."""
    result = await async_run(sample_func, 2, 3)
    expected_result = 5
    assert result[0] == expected_result

    with pytest.raises(ValueError, match="Test error"):
        await async_run(error_func)


@pytest.mark.asyncio
async def test_async_run_timeout(mocker):
    """Test that async_run returns None when a TimeoutError is raised."""
    mocker.patch("asyncio.get_running_loop", new=MagicMock(side_effect=TimeoutError))
    result = await async_run(lambda: None)
    assert result is None
