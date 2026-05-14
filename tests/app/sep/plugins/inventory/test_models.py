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

"""Define tests for app.sep.plugins.inventory.models module."""

import pytest
from pydantic import ValidationError

from app.sep.plugins.inventory.models import InventorySyncScheduleCreateForm


def test_inventory_sync_schedule_form_rejects_cron_with_too_few_tokens() -> None:
    """Test that InventorySyncScheduleCreateForm rejects a cron with fewer than five fields."""
    data = {
        "cron_expression": "0 0 * *",
        "cron_timezone": "UTC",
    }

    with pytest.raises(ValidationError) as exc_info:
        InventorySyncScheduleCreateForm.model_validate(data)

    assert "expected 5 whitespace-separated fields" in str(exc_info.value)


def test_inventory_sync_schedule_form_rejects_cron_with_too_many_tokens() -> None:
    """Test that InventorySyncScheduleCreateForm rejects a cron with more than five fields."""
    data = {
        "cron_expression": "0 0 * * * *",
        "cron_timezone": "UTC",
    }

    with pytest.raises(ValidationError) as exc_info:
        InventorySyncScheduleCreateForm.model_validate(data)

    assert "expected 5 whitespace-separated fields" in str(exc_info.value)


def test_inventory_sync_schedule_form_rejects_empty_cron_expression() -> None:
    """Test that InventorySyncScheduleCreateForm rejects an empty / whitespace cron."""
    data = {
        "cron_expression": "   ",
        "cron_timezone": "UTC",
    }

    with pytest.raises(ValidationError) as exc_info:
        InventorySyncScheduleCreateForm.model_validate(data)

    assert "expression is empty" in str(exc_info.value).lower()


def test_inventory_sync_schedule_form_rejects_cron_with_invalid_token() -> None:
    """Test that InventorySyncScheduleCreateForm rejects a syntactically invalid cron field."""
    data = {
        "cron_expression": "not-a-field * * * *",
        "cron_timezone": "UTC",
    }

    with pytest.raises(ValidationError):
        InventorySyncScheduleCreateForm.model_validate(data)


def test_inventory_sync_schedule_form_accepts_valid_five_field_cron() -> None:
    """Test that InventorySyncScheduleCreateForm parses a valid five-field cron into crontab fields."""
    data = {
        "cron_expression": "15 9-17 * * MON-FRI",
        "cron_timezone": "America/New_York",
    }

    form = InventorySyncScheduleCreateForm.model_validate(data)

    assert form.interval is None
    assert form.crontab is not None
    assert form.crontab.minute == "15"
    assert form.crontab.hour == "9-17"
    assert form.crontab.day_of_month == "*"
    assert form.crontab.month_of_year == "*"
    assert form.crontab.day_of_week == "MON-FRI"
    assert form.crontab.timezone == "America/New_York"
