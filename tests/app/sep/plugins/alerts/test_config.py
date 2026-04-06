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

"""Define tests for the alerts plugin configuration."""

from unittest.mock import MagicMock, patch

from app.core.celery.models import IntervalSchedule, Period
from app.sep.plugins.alerts.config import _create_alerts_pmm_config, AlertsPMMConfig

DEFAULT_BACKUP_RETENTION = 10
CUSTOM_BACKUP_RETENTION = 5


class TestAlertsPMMConfig:
    """Test the ``AlertsPMMConfig`` model."""

    def test_defaults(self):
        """Assert default values for alerts-specific PMM config."""
        config = AlertsPMMConfig()
        assert config.backup_interval == IntervalSchedule(every=24, period=Period.HOURS)
        assert config.backup_retention == DEFAULT_BACKUP_RETENTION
        assert config.alert_folder_name == "SEP Alerts"

    def test_custom_values(self):
        """Assert custom values are accepted."""
        config = AlertsPMMConfig(
            backup_retention=CUSTOM_BACKUP_RETENTION,
            alert_folder_name="Custom Alerts",
        )
        assert config.backup_retention == CUSTOM_BACKUP_RETENTION
        assert config.alert_folder_name == "Custom Alerts"


class TestCreateAlertsPMMConfig:
    """Test the ``_create_alerts_pmm_config`` factory function."""

    def test_reads_fields_from_deprecated_config(self):
        """Assert alerts fields are read from ``sep_settings.PMM``."""
        mock_pmm = MagicMock()
        mock_pmm.backup_retention = CUSTOM_BACKUP_RETENTION
        mock_pmm.alert_folder_name = "Custom"
        mock_pmm.backup_interval = IntervalSchedule(every=12, period=Period.HOURS)
        mock_pmm.model_fields_set = {"backup_retention", "alert_folder_name"}

        with patch("app.sep.config.sep_settings") as mock_settings:
            mock_settings.PMM = mock_pmm
            result = _create_alerts_pmm_config()

        assert result.backup_retention == CUSTOM_BACKUP_RETENTION
        assert result.alert_folder_name == "Custom"

    def test_defaults_when_no_alerts_fields_set(self):
        """Assert defaults used when no alerts fields explicitly set."""
        mock_pmm = MagicMock()
        mock_pmm.backup_retention = 10
        mock_pmm.alert_folder_name = "SEP Alerts"
        mock_pmm.backup_interval = IntervalSchedule(every=24, period=Period.HOURS)
        mock_pmm.model_fields_set = set()

        with patch("app.sep.config.sep_settings") as mock_settings:
            mock_settings.PMM = mock_pmm
            result = _create_alerts_pmm_config()

        assert result.backup_retention == DEFAULT_BACKUP_RETENTION
        assert result.alert_folder_name == "SEP Alerts"
