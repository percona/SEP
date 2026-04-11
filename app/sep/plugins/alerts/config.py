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

"""Define alerts plugin PMM configuration."""

import logging

from pydantic import PositiveInt

from app.core.celery.models import IntervalSchedule, Period
from app.core.models import BaseLowercaseModel
from app.core.utils.lazy import LazyProxy

logger = logging.getLogger(__name__)


class AlertsPMMConfig(BaseLowercaseModel):
    """Define alerts-specific PMM configuration.

    :param backup_interval: Interval between alert configuration backups.
    :type backup_interval: IntervalSchedule
    :param backup_retention: Maximum number of alert backups to retain.
    :type backup_retention: PositiveInt
    :param alert_folder_name: Display name of the PMM folder used for SEP-managed
        alert rules. Defaults to ``"SEP Alerts"``.
    :type alert_folder_name: str
    """

    backup_interval: IntervalSchedule = IntervalSchedule(every=24, period=Period.HOURS)
    backup_retention: PositiveInt = 10
    alert_folder_name: str = "SEP Alerts"


def _create_alerts_pmm_config() -> AlertsPMMConfig:
    """Create an ``AlertsPMMConfig`` from the deprecated ``SEP.PMM`` YAML section.

    Read alerts-specific fields from ``sep_settings.PMM`` (a ``_DeprecatedPMMConfig``
    instance that includes both connection and alerts fields) and validate them
    into an ``AlertsPMMConfig`` instance.

    :return: The validated alerts PMM configuration.
    :rtype: AlertsPMMConfig
    """
    from app.sep.config import sep_settings

    pmm = sep_settings.PMM
    alerts_fields = {"backup_interval", "backup_retention", "alert_folder_name"}
    deprecated_set = pmm.model_fields_set & alerts_fields
    if deprecated_set:
        logger.info(
            "Alerts fields are being read from SEP.PMM. "
            "These fields will move to a dedicated alerts config section "
            "in a future release. Fields found: %s",
            ", ".join(sorted(deprecated_set)),
        )
    return AlertsPMMConfig(
        backup_interval=pmm.backup_interval,
        backup_retention=pmm.backup_retention,
        alert_folder_name=pmm.alert_folder_name,
    )


alerts_pmm_config: AlertsPMMConfig = LazyProxy(_create_alerts_pmm_config)
