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

"""Define the Inventory app settings section."""

__all__ = ["InventoryAppSettings", "inventory_app_settings"]

from datetime import timedelta
from typing import Annotated, ClassVar

from annotated_types import Gt
from pydantic import PositiveInt

from app.core.celery.models import IntervalSchedule
from app.core.config import BaseYamlSettings
from app.core.settings_override.proxy import OverridableSettingsProxy
from app.core.settings_override.registry import hot_field


class InventoryAppSettings(BaseYamlSettings):
    """Define the tombstone-collection job's schedule and runtime knobs.

    The whole feature configures from this one section: every field below is
    read by ``app.sep.apps.inventory.collection`` or by the SEP seeder that
    builds the job's beat entry, and all of them are hot-reloadable.

    :cvar SETTINGS_PREFIXES: The prefixes for Inventory-app settings in the
        configuration file, placing the section under ``SEP.INVENTORY``.
    :param COLLECTION_INTERVAL: The schedule on which the collection job runs.
        ``None`` seeds no beat entry, which is the shipped default: collection
        deletes rows irreversibly, so a deployment carrying that default does
        not start doing so on upgrade. The PMM sidecar profile overrides it to
        ``1 days``, so a PMM-embedded deployment does.
    :param COLLECTION_RETENTION: How long a tombstone is kept before it becomes
        eligible for deletion. The positive lower bound is load-bearing: a
        non-positive retention would put the cutoff at or after the present and
        collect every tombstone in a single pass.
    :param COLLECTION_BATCH_SIZE: The most entities of each type one call to the
        Inventory API may collect.
    :param COLLECTION_MAX_BATCHES: The most batches one scheduled run issues.
        Reaching the cap ends the run normally and leaves the rest to the next
        tick, so a first run against years of accumulated tombstones cannot hold
        the worker for an unbounded time.
    """

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["SEP", "INVENTORY"]
    COLLECTION_INTERVAL: IntervalSchedule | None = hot_field(None)
    COLLECTION_RETENTION: Annotated[timedelta, Gt(timedelta(0))] = hot_field(
        timedelta(days=30)
    )
    COLLECTION_BATCH_SIZE: PositiveInt = hot_field(500, advanced=True)
    COLLECTION_MAX_BATCHES: PositiveInt = hot_field(20, advanced=True)


inventory_app_settings: InventoryAppSettings = OverridableSettingsProxy(
    InventoryAppSettings, setting_class=InventoryAppSettings.__name__
)
