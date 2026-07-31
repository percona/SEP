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

"""Cover the ``SETTINGS_OVERRIDE_ALLOWED_KEYS`` restriction and its predicates.

Exercise the setting itself (env parsing through the real ``Settings()`` source
chain, entry-format validation), the ``policy`` predicates that read it, the
fail-closed and restrict-only invariants, and the value the side-car image
ships in its Containerfile.
"""

import json
import subprocess
import sys
from collections.abc import Callable

import pytest

from app import BASE_DIR
from app.core.alerts.config import AlertSettings
from app.core.config import Settings, settings
from app.core.settings_override.models import SettingClassEnum
from app.core.settings_override.policy import (
    has_allowed_key_under,
    is_key_allowed,
    is_restriction_active,
)
from app.core.settings_override.registry import (
    _policy_locked,
    field_reload_classification,
    ReloadClassification,
    resolve_nested_field,
)
from app.inventory.config import InventorySettings
from app.sep.apps.alerts.config import AlertsSettings
from app.sep.config import SEPSettings
from app.sep.middleware.messages.config import MessagesSettings
from app.sep.snippets.config import SnippetsSettings
from app.tasks.anonymizer.config import AnonymizerSettings
from app.tasks.config import TasksSettings

CONTAINERFILE = BASE_DIR / "sidecar" / "Containerfile.sidecar"
ENV_LINE_PREFIX = "ENV SETTINGS_OVERRIDE_ALLOWED_KEYS="

#: Every settings class reachable from the settings router, keyed by the enum
#: member whose value is the class ``__name__``.
SETTINGS_CLASSES: dict[SettingClassEnum, type] = {
    SettingClassEnum.SETTINGS: Settings,
    SettingClassEnum.SEP_SETTINGS: SEPSettings,
    SettingClassEnum.TASKS_SETTINGS: TasksSettings,
    SettingClassEnum.SNIPPETS_SETTINGS: SnippetsSettings,
    SettingClassEnum.MESSAGES_SETTINGS: MessagesSettings,
    SettingClassEnum.ALERT_SETTINGS: AlertSettings,
    SettingClassEnum.ALERTS_SETTINGS: AlertsSettings,
    SettingClassEnum.ANONYMIZER_SETTINGS: AnonymizerSettings,
    SettingClassEnum.INVENTORY_SETTINGS: InventorySettings,
}

#: Keys the ticket names as provisioned topology that the embedded image must
#: never expose, plus the profile-pinned PMM connection leaves.
TOPOLOGY_KEYS = [
    "SEPSettings.INVENTORY_ENDPOINT",
    "SEPSettings.TASKS_ENDPOINT",
    "SEPSettings.AMBIENT_SESSION_SSO_ENABLED",
    "Settings.PMM__endpoint",
    "Settings.PMM__api_key",
    "TasksSettings.NOMAD__endpoint",
    "SnippetsSettings.SNIPPETS_BASE_URL",
]

#: The one product default the embedded image deliberately leaves tunable.
CARVE_OUT_KEY = "Settings.PMM__annotations_enabled"


def shipped_allowed_keys() -> list[str]:
    """Return the allowlist the side-car Containerfile bakes into the image."""
    for line in CONTAINERFILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(ENV_LINE_PREFIX):
            raw = stripped.removeprefix(ENV_LINE_PREFIX).strip()
            return json.loads(raw.strip("'"))
    pytest.fail(f"No {ENV_LINE_PREFIX!r} line in {CONTAINERFILE}")


class TestSettingDeclaration:
    """Cover the setting's own declaration, parsing and validation."""

    def test_default_is_none(self) -> None:
        """Assert the shipped default leaves every deployment unrestricted."""
        assert settings.SETTINGS_OVERRIDE_ALLOWED_KEYS is None

    def test_field_is_not_overridable(self) -> None:
        """Assert the restriction cannot be unlocked through the override API."""
        assert (
            field_reload_classification(
                Settings.model_fields["SETTINGS_OVERRIDE_ALLOWED_KEYS"],
                owner_cls=Settings,
                field_name="SETTINGS_OVERRIDE_ALLOWED_KEYS",
            )
            is ReloadClassification.NOT_OVERRIDABLE
        )

    def test_parses_json_array_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Assert a bare env var carrying a JSON array reaches the field as a set."""
        monkeypatch.setenv(
            "SETTINGS_OVERRIDE_ALLOWED_KEYS",
            '["Settings.LOGGING", "SEPSettings.SYNC_REFRESH_TIME"]',
        )
        assert {
            "Settings.LOGGING",
            "SEPSettings.SYNC_REFRESH_TIME",
        } == Settings().SETTINGS_OVERRIDE_ALLOWED_KEYS

    @pytest.mark.parametrize("entry", ["no-dot", ".KEY", "Class.", "Too.Many.Dots", ""])
    def test_rejects_malformed_entry(
        self, monkeypatch: pytest.MonkeyPatch, entry: str
    ) -> None:
        """Assert a malformed entry fails the settings load rather than going inert."""
        monkeypatch.setenv("SETTINGS_OVERRIDE_ALLOWED_KEYS", json.dumps([entry]))
        with pytest.raises(ValueError, match="SETTINGS_OVERRIDE_ALLOWED_KEYS"):
            Settings()

    def test_accepts_nested_key_entry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Assert a ``__``-delimited key token passes the format validator."""
        monkeypatch.setenv(
            "SETTINGS_OVERRIDE_ALLOWED_KEYS", '["Settings.PMM__annotations_enabled"]'
        )
        assert {
            "Settings.PMM__annotations_enabled"
        } == Settings().SETTINGS_OVERRIDE_ALLOWED_KEYS


class TestPredicates:
    """Cover the policy predicates the classification gates call."""

    def test_inactive_by_default(self) -> None:
        """Assert an unset restriction reports inactive."""
        assert is_restriction_active() is False

    def test_inactive_allows_every_key(self) -> None:
        """Assert every key stays allowed while the restriction is unset."""
        assert is_key_allowed(SettingClassEnum.SEP_SETTINGS, "INVENTORY_ENDPOINT")
        assert has_allowed_key_under(SettingClassEnum.TASKS_SETTINGS, "NOMAD")

    def test_active_locks_unlisted_key(self, restrict: Callable[..., None]) -> None:
        """Assert an entry set locks every key it does not name."""
        restrict("Settings.LOGGING")
        assert is_restriction_active() is True
        assert is_key_allowed(SettingClassEnum.SETTINGS, "LOGGING") is True
        assert is_key_allowed(SettingClassEnum.SEP_SETTINGS, "LOGGING") is False
        assert (
            is_key_allowed(SettingClassEnum.SEP_SETTINGS, "INVENTORY_ENDPOINT") is False
        )

    def test_unknown_entry_allows_nothing(self, restrict: Callable[..., None]) -> None:
        """Assert an entry naming no real class or field grants no access."""
        restrict("BogusSettings.WHATEVER")
        assert is_key_allowed(SettingClassEnum.SETTINGS, "WHATEVER") is False
        assert is_key_allowed(SettingClassEnum.SETTINGS, "LOGGING") is False

    def test_parent_addressable_via_allowed_leaf(
        self, restrict: Callable[..., None]
    ) -> None:
        """Assert an allowed leaf keeps its parent addressable for nested writes."""
        restrict(CARVE_OUT_KEY)
        assert has_allowed_key_under(SettingClassEnum.SETTINGS, "PMM") is True
        assert has_allowed_key_under(SettingClassEnum.SETTINGS, "SECURITY_HEADERS") is (
            False
        )

    def test_parent_addressable_via_exact_entry(
        self, restrict: Callable[..., None]
    ) -> None:
        """Assert an entry naming the parent itself keeps the parent addressable."""
        restrict("Settings.PMM")
        assert has_allowed_key_under(SettingClassEnum.SETTINGS, "PMM") is True

    def test_prefix_match_requires_a_segment_boundary(
        self, restrict: Callable[..., None]
    ) -> None:
        """Assert a shared textual prefix does not make an unrelated parent open."""
        restrict("SEPSettings.SESSION_REFRESH__ENABLED")
        assert has_allowed_key_under(SettingClassEnum.SEP_SETTINGS, "SESSION") is False

    def test_fail_closed_for_unknown_settings_class(
        self, restrict: Callable[..., None]
    ) -> None:
        """Assert a class outside the enum is locked rather than silently allowed."""

        class ProbeSettings(Settings):
            """Stand in for a settings class the enum does not know."""

        restrict("Settings.LOGGING")
        assert _policy_locked(ProbeSettings, "LOGGING") is True
        assert _policy_locked(Settings, "LOGGING") is False


class TestShippedValue:
    """Cover the allowlist the side-car image bakes in."""

    def test_every_entry_resolves(self) -> None:
        """Assert each shipped entry names a real settings class and field."""
        for entry in shipped_allowed_keys():
            class_token, key = entry.split(".", 1)
            setting_class = SettingClassEnum(class_token)
            settings_cls = SETTINGS_CLASSES[setting_class]
            if "__" in key:
                resolved = resolve_nested_field(settings_cls, key)
                assert resolved is not None, f"{entry} does not resolve"
                assert "__".join(resolved[0]) == key, f"{entry} is not canonical"
            else:
                assert key in settings_cls.model_fields, f"{entry} does not resolve"

    def test_entries_are_unique(self) -> None:
        """Assert the shipped list carries no duplicate entry."""
        entries = shipped_allowed_keys()
        assert len(entries) == len(set(entries))

    @pytest.mark.parametrize("entry", TOPOLOGY_KEYS)
    def test_topology_keys_are_locked(self, entry: str) -> None:
        """Assert no provisioned-topology key is tunable in the embedded image."""
        assert entry not in shipped_allowed_keys()

    def test_annotations_carve_out_is_allowed(self) -> None:
        """Assert the one documented product-default carve-out stays tunable."""
        assert CARVE_OUT_KEY in shipped_allowed_keys()

    def test_no_nomad_key_is_allowed(self) -> None:
        """Assert the whole Nomad subtree is locked, not only its endpoint."""
        assert not [
            entry
            for entry in shipped_allowed_keys()
            if entry.startswith("TasksSettings.NOMAD")
        ]


class TestImportOrder:
    """Cover the module-import cycle the lazy settings read exists to avoid."""

    @pytest.mark.parametrize(
        ("first", "second"),
        [
            ("app.core.settings_override.policy", "app.core.config"),
            ("app.core.config", "app.core.settings_override.policy"),
        ],
    )
    def test_both_import_orders_succeed(self, first: str, second: str) -> None:
        """Assert neither import order trips a circular import at startup."""
        result = subprocess.run(
            [sys.executable, "-c", f"import {first}; import {second}"],
            capture_output=True,
            check=False,
            cwd=BASE_DIR,
            text=True,
        )
        assert result.returncode == 0, result.stderr
