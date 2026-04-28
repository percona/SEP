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

"""Define tests for app.sep.tasks module."""

import pytest
from pydantic import ValidationError

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


def test_periodic_task_request_rejects_cron_with_too_few_tokens() -> None:
    """Test that PeriodicTaskRequest raises ValidationError when cron_expression has fewer than five fields."""
    data = {
        "cron_expression": "0 0 * *",
        "cron_timezone": "UTC",
    }

    with pytest.raises(ValidationError) as exc_info:
        PeriodicTaskRequest.model_validate(data)

    assert "5" in str(exc_info.value) or "invalid" in str(exc_info.value).lower()


def test_periodic_task_request_rejects_cron_with_too_many_tokens() -> None:
    """Test that PeriodicTaskRequest raises ValidationError when cron_expression has more than five fields."""
    data = {
        "cron_expression": "0 0 * * * extra",
        "cron_timezone": "UTC",
    }

    with pytest.raises(ValidationError):
        PeriodicTaskRequest.model_validate(data)


def test_periodic_task_request_rejects_cron_with_invalid_token() -> None:
    """Test that PeriodicTaskRequest raises ValidationError when cron_expression has a syntactically invalid field."""
    data = {
        "cron_expression": "not-a-field * * * *",
        "cron_timezone": "UTC",
    }

    with pytest.raises(ValidationError):
        PeriodicTaskRequest.model_validate(data)


def test_periodic_task_request_accepts_valid_five_field_cron() -> None:
    """Test that PeriodicTaskRequest parses a valid five-field cron_expression into crontab fields."""
    data = {
        "cron_expression": "15 9-17 * * MON-FRI",
        "cron_timezone": "America/New_York",
    }

    request = PeriodicTaskRequest.model_validate(data)

    assert request.interval is None
    assert request.crontab is not None
    assert request.crontab.minute == "15"
    assert request.crontab.hour == "9-17"
    assert request.crontab.day_of_month == "*"
    assert request.crontab.month_of_year == "*"
    assert request.crontab.day_of_week == "MON-FRI"
    assert request.crontab.timezone == "America/New_York"
