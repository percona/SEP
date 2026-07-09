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

"""Define tests for app.sep.apps.inventory.models module."""

import pytest
from pydantic import ValidationError

from app.sep.apps.inventory.deps import AvailableSyncer
from app.sep.apps.inventory.models import (
    InventorySyncScheduleCreateForm,
    PluginTaskResponse,
)


class TestPluginTaskResponse:
    """Tests for the PluginTaskResponse model."""

    def test_accepts_valid_data(self) -> None:
        """Ensure model instantiates from valid name and display_name."""
        task = PluginTaskResponse(name="inventory-sync", display_name="Inventory Sync")
        assert task.name == "inventory-sync"
        assert task.display_name == "Inventory Sync"

    def test_rejects_missing_name(self) -> None:
        """Ensure missing ``name`` raises ValidationError."""
        with pytest.raises(ValidationError):
            PluginTaskResponse(display_name="Inventory Sync")

    def test_rejects_missing_display_name(self) -> None:
        """Ensure missing ``display_name`` raises ValidationError."""
        with pytest.raises(ValidationError):
            PluginTaskResponse(name="inventory-sync")

    def test_name_must_be_string(self) -> None:
        """Ensure non-string ``name`` raises ValidationError."""
        with pytest.raises(ValidationError):
            PluginTaskResponse(name=123, display_name="Inventory Sync")

    def test_display_name_must_be_string(self) -> None:
        """Ensure non-string ``display_name`` raises ValidationError."""
        with pytest.raises(ValidationError):
            PluginTaskResponse(name="inventory-sync", display_name=123)

    def test_serializes_to_dict(self) -> None:
        """Ensure model_dump returns expected keys."""
        task = PluginTaskResponse(name="inventory-sync", display_name="Inventory Sync")
        dumped = task.model_dump()
        assert dumped == {"name": "inventory-sync", "display_name": "Inventory Sync"}


class TestAvailableSyncer:
    """Tests for the AvailableSyncer model."""

    def test_accepts_valid_data(self) -> None:
        """Ensure model instantiates from valid name and display_name."""
        syncer = AvailableSyncer(
            name="app.sep.sync.syncers.pmm.PMMSyncer",
            display_name="PMM",
        )
        assert syncer.name == "app.sep.sync.syncers.pmm.PMMSyncer"
        assert syncer.display_name == "PMM"

    def test_rejects_missing_name(self) -> None:
        """Ensure missing ``name`` raises ValidationError."""
        with pytest.raises(ValidationError):
            AvailableSyncer(display_name="PMM")

    def test_rejects_missing_display_name(self) -> None:
        """Ensure missing ``display_name`` raises ValidationError."""
        with pytest.raises(ValidationError):
            AvailableSyncer(name="app.sep.sync.syncers.pmm.PMMSyncer")

    def test_name_must_be_string(self) -> None:
        """Ensure non-string ``name`` raises ValidationError."""
        with pytest.raises(ValidationError):
            AvailableSyncer(name=42, display_name="PMM")

    def test_display_name_must_be_string(self) -> None:
        """Ensure non-string ``display_name`` raises ValidationError."""
        with pytest.raises(ValidationError):
            AvailableSyncer(name="app.sep.sync.syncers.pmm.PMMSyncer", display_name=42)

    def test_serializes_to_dict(self) -> None:
        """Ensure model_dump returns expected keys."""
        syncer = AvailableSyncer(
            name="app.sep.sync.syncers.pmm.PMMSyncer",
            display_name="PMM",
        )
        assert syncer.model_dump() == {
            "name": "app.sep.sync.syncers.pmm.PMMSyncer",
            "display_name": "PMM",
        }


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
