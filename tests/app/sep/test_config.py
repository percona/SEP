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

import logging
from datetime import timedelta
from string import Template

import pytest
from pydantic import ValidationError

from app.sep.config import (
    App,
    AppDrainSettings,
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


class TestDeprecatedPMMRemoved:
    """The deprecated ``SEP.PMM`` section is gone; PMM lives only top-level."""

    def test_sep_settings_has_no_pmm_field(self):
        """``SEPSettings`` no longer declares a ``PMM`` field."""
        assert "PMM" not in SEPSettings.model_fields

    def test_stray_sep_pmm_mapping_is_ignored_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ):
        """A leftover ``SEP.PMM`` mapping is dropped but logs a removal warning.

        Connection config must now come from the top-level ``PMM`` section. The
        stale ``SEP.PMM`` block has no effect (``extra='ignore'`` drops it), but a
        ``WARNING`` is emitted so upgraded deployments get a startup signal instead
        of silently carrying dead config.
        """
        with caplog.at_level(logging.WARNING, logger="app.sep.config"):
            settings = SEPSettings(PMM={"ENDPOINT": "https://pmm.example.com"})
        assert not hasattr(settings, "PMM")
        assert "PMM" not in settings.model_fields_set
        assert any(
            "SEP.PMM" in r.message and r.levelno == logging.WARNING
            for r in caplog.records
        )

    def test_no_warning_without_stray_pmm(self, caplog: pytest.LogCaptureFixture):
        """A clean ``SEPSettings`` build emits no ``SEP.PMM`` removal warning."""
        with caplog.at_level(logging.WARNING, logger="app.sep.config"):
            SEPSettings()
        assert not any("SEP.PMM" in r.message for r in caplog.records)


class TestPerSyncerPMMRemoved:
    """The per-syncer ``pmm:`` override is gone; PMM syncers read top-level ``PMM``."""

    def test_stray_pmm_on_syncer_is_dropped_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ):
        """A leftover ``pmm`` key on a ``SYNCERS[]`` entry is dropped and warns."""
        with caplog.at_level(logging.WARNING, logger="app.sep.config"):
            syncer = SyncOptions(
                syncer="PMMSyncer", pmm={"endpoint": "https://pmm.example.com"}
            )
        assert "pmm" not in syncer.model_dump()
        assert any(
            "pmm" in r.message and r.levelno == logging.WARNING for r in caplog.records
        )

    def test_stray_pmm_on_extra_kwargs_is_dropped_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ):
        """A leftover ``pmm`` key in ``SYNCER_EXTRA_KWARGS`` is dropped and warns."""
        with caplog.at_level(logging.WARNING, logger="app.sep.config"):
            extra = SyncerExtraKwargs(pmm={"api_key": "secret"})
        assert "pmm" not in extra.model_dump()
        assert any(
            "pmm" in r.message and r.levelno == logging.WARNING for r in caplog.records
        )


class TestPluginModuleNameResolution:
    """``App.MODULE_NAME`` resolution after the legacy backup shim removal."""

    @pytest.mark.parametrize("legacy_value", ["backup", "backups"])
    def test_legacy_backup_names_are_rejected(self, legacy_value: str):
        """Legacy ``backup``/``backups`` no longer remap and fail module validation."""
        with pytest.raises(ValidationError, match="No module named"):
            App(name="MySQL Backups", module_name=legacy_value)

    def test_modern_value_resolves(self):
        """The modern ``mysql_backups`` value resolves normally."""
        plugin = App(name="MySQL Backups", module_name="mysql_backups")
        assert plugin.module_name == "app.sep.plugins.mysql_backups"

    @pytest.mark.parametrize(
        ("sibling_value", "expected_module"),
        [
            ("backup_mongo", "app.sep.plugins.backup_mongo"),
            ("backup_pg", "app.sep.plugins.backup_pg"),
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
        """A zero or negative TTL fails validation rather than pruning live rows."""
        with pytest.raises(ValidationError, match="positive duration"):
            AppDrainSettings(stale_task_ttl=timedelta(seconds=seconds))
