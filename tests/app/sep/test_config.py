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

from app.core.settings_override.registry import is_hot_reloadable
from app.sep.config import (
    App,
    AppDrainSettings,
    sep_settings,
    SEPSettings,
    SessionOptions,
    SyncerExtraKwargs,
    SyncOptions,
)


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


class TestFeatureFlags:
    """Define tests for SEP feature flags."""

    def test_inventory_topology_defaults_off(self):
        """Assert inventory topology is disabled by default."""
        settings = SEPSettings()
        assert settings.INVENTORY_TOPOLOGY_ENABLED is False


class TestAmbientSessionSSO:
    """Test the ambient Grafana SSO feature toggle."""

    def test_defaults_to_disabled(self):
        """Verify ambient SSO is opt-in, reading ``False`` through the proxy."""
        assert sep_settings.AMBIENT_SESSION_SSO_ENABLED is False

    def test_is_hot_reloadable(self):
        """Verify the toggle is a hot field, so a DB override can enable it live."""
        assert is_hot_reloadable(SEPSettings, "AMBIENT_SESSION_SSO_ENABLED")


class TestFooterTemplate:
    """Define tests for the FOOTER_TEMPLATE setting."""

    def test_footer_template_default(self):
        """Assert FOOTER_TEMPLATE defaults to ``$summary $version``.

        Load without the dotenv file so a local ``.env.local`` override (a
        worktree hook may set ``SEP__FOOTER_TEMPLATE`` to the branch name) does
        not mask the built-in default.
        """
        settings = SEPSettings(_env_file=None)
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


class TestDeprecatedPMMRemoved:
    """The deprecated ``SEP.PMM`` section is gone; PMM lives only top-level."""

    def test_sep_settings_has_no_pmm_field(self):
        """``SEPSettings`` no longer declares a ``PMM`` field."""
        assert "PMM" not in SEPSettings.model_fields

    def test_stray_sep_pmm_mapping_is_rejected(self):
        """A leftover ``SEP.PMM`` mapping is rejected at construction.

        Connection config must now come from the top-level ``PMM`` section. The
        stale ``SEP.PMM`` block (including the ``SEP__PMM__*`` env-var path) is
        rejected with a ``ValidationError`` so upgraded deployments fail fast at
        startup instead of silently carrying dead config.
        """
        with pytest.raises(ValidationError, match="SEP.PMM"):
            SEPSettings(PMM={"ENDPOINT": "https://pmm.example.com"})

    def test_clean_build_without_stray_pmm(self):
        """A clean ``SEPSettings`` build (no ``PMM`` key) constructs without error."""
        assert SEPSettings() is not None


class TestPerSyncerPMMRemoved:
    """The per-syncer ``pmm:`` override is gone; PMM syncers read top-level ``PMM``."""

    def test_stray_pmm_on_syncer_is_rejected(self):
        """A leftover ``pmm`` key on a ``SYNCERS[]`` entry is rejected."""
        with pytest.raises(ValidationError, match="pmm"):
            SyncOptions(syncer="PMMSyncer", pmm={"endpoint": "https://pmm.example.com"})

    def test_stray_pmm_on_extra_kwargs_is_rejected(self):
        """A leftover ``pmm`` key in ``SYNCER_EXTRA_KWARGS`` is rejected."""
        with pytest.raises(ValidationError, match="pmm"):
            SyncerExtraKwargs(pmm={"api_key": "secret"})


class TestPluginModuleNameResolution:
    """``App.MODULE_NAME`` resolution after the legacy backup shim removal."""

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
    def test_sibling_backup_module_resolves(
        self, sibling_value: str, expected_module: str
    ):
        """Sibling plugins whose names begin with ``backup`` resolve unchanged."""
        plugin = App(name="Backups", module_name=sibling_value)
        assert plugin.module_name == expected_module


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
        """A zero or negative TTL fails validation rather than pruning live rows.

        Positivity is enforced by the ``Gt`` annotation constraint so it also
        holds for runtime overrides, hence the standard "greater than" message.
        """
        with pytest.raises(ValidationError, match="greater than"):
            AppDrainSettings(stale_task_ttl=timedelta(seconds=seconds))


def _logged_legacy_apps_warning(mock_logger: object) -> bool:
    """Return whether any ``logger.warning`` call names the deprecated PLUGINS key."""
    return any(
        "PLUGINS" in str(call.args[0]) for call in mock_logger.warning.call_args_list
    )


class TestAppsKeyBackCompat:
    """Cover the ``SEP.PLUGINS`` -> ``SEP.APPS`` config-key back-compat shim."""

    def test_legacy_plugins_key_populates_apps(self):
        """Load a legacy ``PLUGINS`` key into ``APPS`` via the validation alias."""
        settings = SEPSettings.model_validate(
            {"PLUGINS": [{"MODULE_NAME": "backup_pg"}]}
        )
        assert [app.module_name for app in settings.APPS] == ["app.sep.apps.backup_pg"]

    def test_modern_apps_key_populates_apps(self):
        """Load the app list from the modern ``APPS`` key."""
        settings = SEPSettings.model_validate({"APPS": [{"MODULE_NAME": "backup_pg"}]})
        assert [app.module_name for app in settings.APPS] == ["app.sep.apps.backup_pg"]

    def test_apps_takes_precedence_over_legacy(self):
        """Prefer ``APPS`` over the legacy ``PLUGINS`` when both keys are set."""
        settings = SEPSettings.model_validate(
            {
                "APPS": [{"MODULE_NAME": "backup_pg"}],
                "PLUGINS": [{"MODULE_NAME": "backup_mongo"}],
            }
        )
        assert [app.module_name for app in settings.APPS] == ["app.sep.apps.backup_pg"]

    def test_deprecation_warning_for_legacy_key(self):
        """Assert a deprecation warning is logged when the legacy ``PLUGINS`` key is set."""
        with patch("app.sep.config.logger") as mock_logger:
            SEPSettings.model_validate({"PLUGINS": [{"MODULE_NAME": "backup_pg"}]})
        assert _logged_legacy_apps_warning(mock_logger)

    def test_no_warning_for_modern_key(self):
        """Assert no deprecation warning is logged for the modern ``APPS`` key."""
        with patch("app.sep.config.logger") as mock_logger:
            SEPSettings.model_validate({"APPS": [{"MODULE_NAME": "backup_pg"}]})
        assert not _logged_legacy_apps_warning(mock_logger)

    def test_legacy_plugins_env_var_populates_apps_and_warns(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Load a legacy ``SEP__PLUGINS`` env var into ``APPS`` and warn."""
        monkeypatch.setenv("SEP__PLUGINS", '[{"MODULE_NAME": "backup_pg"}]')
        with patch("app.sep.config.logger") as mock_logger:
            settings = SEPSettings()
        assert any(app.module_name == "app.sep.apps.backup_pg" for app in settings.APPS)
        assert _logged_legacy_apps_warning(mock_logger)

    def test_modern_apps_env_var_does_not_warn(self, monkeypatch: pytest.MonkeyPatch):
        """Load a modern ``SEP__APPS`` env var into ``APPS`` without warning."""
        monkeypatch.setenv("SEP__APPS", '[{"MODULE_NAME": "backup_pg"}]')
        with patch("app.sep.config.logger") as mock_logger:
            settings = SEPSettings()
        assert any(app.module_name == "app.sep.apps.backup_pg" for app in settings.APPS)
        assert not _logged_legacy_apps_warning(mock_logger)
