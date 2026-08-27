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

"""Test the Inventory app's collection settings."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.sep.apps.inventory.config import inventory_app_settings, InventoryAppSettings

DEFAULT_RETENTION_DAYS = 30


def test_the_default_retention_is_a_month() -> None:
    """Keep a tombstone for a month before it becomes eligible."""
    assert (
        timedelta(days=DEFAULT_RETENTION_DAYS)
        == inventory_app_settings.COLLECTION_RETENTION
    )


@pytest.mark.parametrize(
    "retention",
    [timedelta(0), timedelta(seconds=-1), timedelta(days=-30)],
)
def test_a_non_positive_retention_is_rejected(retention: timedelta) -> None:
    """Refuse a retention that would put the cutoff at or after the present.

    A non-positive retention collects every tombstone in a single pass, so the
    bound is a safety guard rather than a formality.
    """
    with pytest.raises(ValidationError):
        InventoryAppSettings(COLLECTION_RETENTION=retention)


@pytest.mark.parametrize("field", ["COLLECTION_BATCH_SIZE", "COLLECTION_MAX_BATCHES"])
def test_the_batch_bounds_reject_zero(field: str) -> None:
    """Refuse a zero batch bound — an unset interval is how you disable the job."""
    with pytest.raises(ValidationError):
        InventoryAppSettings(**{field: 0})
