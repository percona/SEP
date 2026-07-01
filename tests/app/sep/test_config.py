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

from datetime import timedelta
from string import Template
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.core.config import PMMSettings
from app.sep.config import (
    App,
    AppDrainSettings,
    DeprecatedPMMConfig,
    SEPSettings,
    SessionOptions,
)

PMM_ENDPOINT = "https://pmm.example.com"
CORE_PMM_ENDPOINT = "https://core.example.com"


class TestSessionOptions:
    """Define tests for the SessionOptions model."""

    def test_default_dump_has_none_path(self):
        """Assert legacy SessionOptions dump keeps ``path=None`` (no explicit path)."""
        dumped = SessionOptions().model_dump(by_alias=True)
        assert dumped["key"] == "authToken"
        assert dumped["path"] is None

    def test_refresh_dump_carries_path(self):
        """Assert a SESSION_REFRESH-style instance exposes the configured path."""
        dumped = SessionOptions(
            COOKIE_NAME="refreshToken", PATH="/api/oauth"
        ).model_dump(by_alias=True)
        assert dumped["key"] == "refreshToken"
        assert dumped["path"] == "/api/oauth"


class TestSessionRefreshDefault:
    """Define tests for the ``SEPSettings.SESSION_REFRESH`` default instance."""

    def test_session_refresh_defaults(self):
        """Assert the default SESSION_REFRESH instance targets /api/oauth."""
        settings = SEPSettings()
        assert settings.SESSION_REFRESH.COOKIE_NAME == "refreshToken"
        assert settings.SESSION_REFRESH.PATH == "/api/oauth"
        assert settings.SESSION.PATH is None


class TestFooterTemplate:
    """Define tests for the FOOTER_TEMPLATE setting."""

    def test_footer_template_default(self):
        """Assert FOOTER_TEMPLATE defaults to ``$summary $version``."""
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
            SEPSettings(PMM=DeprecatedPMMConfig())
        assert mock_settings.PMM is core_pmm


class TestPluginModuleNameDeprecation:
    """Test the legacy ``backup``/``backups`` MODULE_NAME shim on ``App``."""

    @pytest.mark.parametrize("legacy_value", ["backup", "backups"])
    def test_legacy_value_is_remapped_to_mysql_backups(self, legacy_value: str):
        """Assert legacy aliases resolve to ``mysql_backups`` and log a deprecation warning."""
        with patch("app.sep.config.logger") as mock_logger:
            plugin = App(name="MySQL Backups", module_name=legacy_value)
        assert plugin.module_name == "app.sep.apps.mysql_backups"
        mock_logger.warning.assert_called_once()
        rendered = mock_logger.warning.call_args.args[0] % tuple(
            mock_logger.warning.call_args.args[1:]
        )
        assert repr(legacy_value) in rendered
        assert "mysql_backups" in rendered
        assert "next version" in rendered

    def test_modern_value_resolves_without_warning(self):
        """Assert the modern ``mysql_backups`` value resolves normally with no warning."""
        with patch("app.sep.config.logger") as mock_logger:
            plugin = App(name="MySQL Backups", module_name="mysql_backups")
        assert plugin.module_name == "app.sep.apps.mysql_backups"
        mock_logger.warning.assert_not_called()

    @pytest.mark.parametrize(
        ("sibling_value", "expected_module"),
        [
            ("backup_mongo", "app.sep.apps.backup_mongo"),
            ("backup_pg", "app.sep.apps.backup_pg"),
        ],
    )
    def test_sibling_backup_module_is_not_remapped(
        self, sibling_value: str, expected_module: str
    ):
        """Assert sibling plugins whose names begin with ``backup`` are unaffected."""
        with patch("app.sep.config.logger") as mock_logger:
            plugin = App(name="Backups", module_name=sibling_value)
        assert plugin.module_name == expected_module
        mock_logger.warning.assert_not_called()


class TestPluginNameOptional:
    """Test the MODULE_NAME-only ``App`` shrink (``name`` optional)."""

    def test_plugin_constructs_without_name(self) -> None:
        """A MODULE_NAME-only entry validates with ``name`` absent."""
        plugin = App(module_name="checksums")
        assert plugin.name is None

    def test_name_absent_leaves_derived_metadata_empty(self) -> None:
        """Without a name, ``uri_path``/``css_class`` stay empty for the registry."""
        plugin = App(module_name="checksums")
        assert plugin.uri_path == ""
        assert plugin.css_class == ""

    def test_name_still_seeds_derived_metadata(self) -> None:
        """A supplied name keeps driving the slugified defaults."""
        plugin = App(name="Snippet Manager", module_name="snippets")
        assert plugin.uri_path == "/snippet-manager"
        assert plugin.css_class == "snippet-manager"


class TestAppDrainSettings:
    """The drain reconciler settings reject a non-positive stale-task TTL."""

    def test_default_ttl_is_one_hour(self) -> None:
        """The default TTL is a positive duration."""
        assert AppDrainSettings().stale_task_ttl == timedelta(hours=1)

    @pytest.mark.parametrize("seconds", [0, -1, -3600])
    def test_non_positive_ttl_rejected(self, seconds: int) -> None:
        """A zero or negative TTL fails validation rather than pruning live rows."""
        with pytest.raises(ValidationError, match="positive duration"):
            AppDrainSettings(stale_task_ttl=timedelta(seconds=seconds))
