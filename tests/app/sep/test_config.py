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

from app.sep.config import PMMSettings, SEPSettings


def test_pmm_api_key_masked_in_repr():
    """Test that api_key is masked in repr output."""
    pmm = PMMSettings(api_key="my-pmm-api-key")
    assert "my-pmm-api-key" not in repr(pmm)


def test_pmm_api_key_accepts_secretstr():
    """Test that PMMSettings accepts SecretStr for api_key."""
    pmm = PMMSettings(api_key="test-key")
    assert pmm.api_key.get_secret_value() == "test-key"


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
