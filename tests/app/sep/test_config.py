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

"""Define tests for the app.sep.config module."""

from string import Template
from unittest.mock import patch

from app.core.celery.models import CrontabSchedule, IntervalSchedule
from app.core.config import PMMSettings
from app.sep.config import (
    _DeprecatedPMMConfig,
    HealthReportSettings,
    PMMSettings,
    ReportScheduleEntry,
    SEPSettings,
)

PMM_ENDPOINT = "https://pmm.example.com"
CORE_PMM_ENDPOINT = "https://core.example.com"


class TestFooterTemplate:
    """Define tests for the FOOTER_TEMPLATE setting."""

    def test_footer_template_default(self):
        """Assert FOOTER_TEMPLATE defaults to `$summary $version`."""
        settings = SEPSettings()
        assert settings.FOOTER_TEMPLATE.template == "$summary $version"

    def test_footer_template_coerced_from_string(self):
        """Assert a plain string is coerced to a Template object."""
        settings = SEPSettings(FOOTER_TEMPLATE="$version only")
        assert isinstance(settings.FOOTER_TEMPLATE, Template)
        assert settings.FOOTER_TEMPLATE.template == "$version only"

    def test_footer_template_accepts_template_object(self):
        """Assert a Template object is accepted as-is."""
        tmpl = Template("custom $summary")
        settings = SEPSettings(FOOTER_TEMPLATE=tmpl)
        assert settings.FOOTER_TEMPLATE is tmpl

    @patch("app.sep.config.__version__", "9.8.7")
    @patch("app.sep.config.__summary__", "TestApp")
    def test_footer_text_renders_default_template(self):
        """Assert FOOTER_TEXT renders the default template with version and summary."""
        settings = SEPSettings()
        assert settings.FOOTER_TEXT == "TestApp 9.8.7"

    @patch("app.sep.config.__version__", "1.2.3")
    @patch("app.sep.config.__summary__", "MySEP")
    def test_footer_text_renders_custom_template(self):
        """Assert FOOTER_TEXT renders a custom template with substituted placeholders."""
        settings = SEPSettings(FOOTER_TEMPLATE="$summary v$version (custom)")
        assert settings.FOOTER_TEXT == "MySEP v1.2.3 (custom)"

    @patch("app.sep.config.__version__", "0.0.1")
    @patch("app.sep.config.__summary__", "App")
    def test_footer_text_ignores_unknown_placeholders(self):
        """Assert FOOTER_TEXT safely ignores unknown placeholders."""
        settings = SEPSettings(FOOTER_TEMPLATE="$summary $unknown $version")
        assert settings.FOOTER_TEXT == "App $unknown 0.0.1"


class TestForwardDeprecatedPMMFields:
    """Test the ``_forward_deprecated_pmm_fields`` model validator."""

    def test_forwards_fields_to_core_settings(self):
        """Assert deprecated ``SEP.PMM`` fields are forwarded to ``settings.PMM``."""
        core_pmm = PMMSettings()
        with patch("app.sep.config.settings") as mock_settings:
            mock_settings.PMM = core_pmm
            SEPSettings(PMM={"ENDPOINT": PMM_ENDPOINT})
        assert mock_settings.PMM.endpoint == PMM_ENDPOINT

    def test_core_settings_take_precedence(self):
        """Assert top-level ``PMM`` fields are not overwritten by ``SEP.PMM``."""
        core_pmm = PMMSettings(endpoint=CORE_PMM_ENDPOINT)
        with patch("app.sep.config.settings") as mock_settings:
            mock_settings.PMM = core_pmm
            SEPSettings(PMM={"ENDPOINT": PMM_ENDPOINT})
        assert mock_settings.PMM.endpoint == CORE_PMM_ENDPOINT

    def test_deprecation_warning_logged(self):
        """Assert a deprecation warning is logged when fields are forwarded."""
        core_pmm = PMMSettings()
        with (
            patch("app.sep.config.settings") as mock_settings,
            patch("app.sep.config.logger") as mock_logger,
        ):
            mock_settings.PMM = core_pmm
            SEPSettings(PMM={"ENDPOINT": PMM_ENDPOINT})
        mock_logger.warning.assert_called_once()

    def test_no_op_when_no_deprecated_fields_set(self):
        """Assert ``settings.PMM`` is not modified when no deprecated fields are set."""
        core_pmm = PMMSettings()
        with patch("app.sep.config.settings") as mock_settings:
            mock_settings.PMM = core_pmm
            SEPSettings(PMM=_DeprecatedPMMConfig())
        assert mock_settings.PMM is core_pmm
