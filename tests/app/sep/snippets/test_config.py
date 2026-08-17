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

"""Tests for SnippetSudoOption, including OPTIONAL_DEFAULT_TRUE."""

import json
import re
from collections.abc import Iterator
from typing import Any

import pytest
import yaml
from pydantic import ValidationError
from sqlalchemy_celery_beat.models import Period

from app import BASE_DIR
from app.core.celery.models import IntervalSchedule
from app.core.settings_override.registry import (
    is_hot_reloadable,
    materialize_override_value,
)
from app.sep.snippets.config import (
    SnippetFilter,
    SnippetFilterType,
    SnippetsSettings,
    SnippetSudoOption,
)
from app.sep.snippets.models.snippet import BaseSnippet

EXECUTOR_HOSTS = frozenset({("host1", "host1")})


def _make_params_json(*params: dict[str, Any]) -> str:
    """Serialize parameter dicts to a JSON string for `_to_form`."""
    return json.dumps(list(params))


def _extract_fieldset_legends(html: str) -> list[str]:
    """Extract all fieldset legend texts from rendered HTML, in order."""
    return re.findall(r"<legend[^>]*>(.*?)</legend>", html)


def _count_fieldsets(html: str) -> int:
    """Count total fieldset elements in rendered HTML."""
    return html.count("<fieldset")


class TestSnippetSudoOptionProperties:
    """Test the is_optional and sudo_default properties."""

    @pytest.mark.parametrize(
        ("option", "expected"),
        [
            (SnippetSudoOption.NEVER, False),
            (SnippetSudoOption.ALWAYS, False),
            (SnippetSudoOption.OPTIONAL, True),
            (SnippetSudoOption.OPTIONAL_DEFAULT_TRUE, True),
            (SnippetSudoOption.OPTIONAL_DEFAULT_FALSE, True),
        ],
    )
    def test_is_optional(self, option, expected):
        """Verify is_optional returns correct value for each sudo option."""
        assert option.is_optional is expected

    @pytest.mark.parametrize(
        ("option", "expected"),
        [
            (SnippetSudoOption.NEVER, False),
            (SnippetSudoOption.ALWAYS, False),
            (SnippetSudoOption.OPTIONAL, False),
            (SnippetSudoOption.OPTIONAL_DEFAULT_TRUE, True),
            (SnippetSudoOption.OPTIONAL_DEFAULT_FALSE, False),
        ],
    )
    def test_sudo_default(self, option, expected):
        """Verify sudo_default returns correct value for each sudo option."""
        assert option.sudo_default is expected


class TestSnippetSudoOptionAlias:
    """Test that OPTIONAL_DEFAULT_FALSE is an alias for OPTIONAL."""

    def test_alias_identity(self):
        """Verify OPTIONAL_DEFAULT_FALSE is the same object as OPTIONAL."""
        assert SnippetSudoOption.OPTIONAL_DEFAULT_FALSE is SnippetSudoOption.OPTIONAL

    def test_alias_value(self):
        """Verify OPTIONAL_DEFAULT_FALSE has the same numeric value as OPTIONAL."""
        assert (
            SnippetSudoOption.OPTIONAL_DEFAULT_FALSE.value
            == SnippetSudoOption.OPTIONAL.value
        )


class TestSudoExecutionModel:
    """Test that _get_execution_model sets correct sudo default."""

    def test_sudo_default_false(self):
        """Verify execution model sudo field defaults to False."""
        model = BaseSnippet._get_execution_model(
            "[]",
            add_sudo_field=True,
            sudo_default=False,
        )
        assert model.model_fields["sudo"].default is False

    def test_sudo_default_true(self):
        """Verify execution model sudo field defaults to True."""
        model = BaseSnippet._get_execution_model(
            "[]",
            add_sudo_field=True,
            sudo_default=True,
        )
        assert model.model_fields["sudo"].default is True

    def test_no_sudo_field_when_not_optional(self):
        """Verify no sudo field exists when add_sudo_field is False."""
        model = BaseSnippet._get_execution_model(
            "[]",
            add_sudo_field=False,
        )
        assert "sudo" not in model.model_fields


EXPECTED_FIELDSETS_WITH_EXECUTOR = 2
EXPECTED_FIELDSETS_MIXED_GROUPS = 3


class TestSyncIntervalHotField:
    """``SYNC_INTERVAL`` is HOT-reloadable so a DB override takes effect live."""

    def test_sync_interval_is_hot_reloadable(self) -> None:
        """``SYNC_INTERVAL`` is declared HOT via ``hot_field``."""
        assert is_hot_reloadable(SnippetsSettings, "SYNC_INTERVAL") is True

    def test_materializes_dict_override_to_interval_schedule(self) -> None:
        """A raw dict override coerces to an ``IntervalSchedule`` snapshot value."""
        field_info = SnippetsSettings.model_fields["SYNC_INTERVAL"]
        value = materialize_override_value(
            SnippetsSettings,
            "SYNC_INTERVAL",
            field_info,
            {"every": 30, "period": "minutes"},
        )
        assert value == IntervalSchedule(every=30, period=Period.MINUTES)

    def test_materializes_string_override_to_interval_schedule(self) -> None:
        """A raw string override coerces via ``IntervalSchedule.create_from_str``."""
        field_info = SnippetsSettings.model_fields["SYNC_INTERVAL"]
        value = materialize_override_value(
            SnippetsSettings, "SYNC_INTERVAL", field_info, "every 15 minutes"
        )
        assert value == IntervalSchedule(every=15, period=Period.MINUTES)

    @pytest.mark.parametrize(
        "bad",
        [{"every": 0, "period": "minutes"}, {"every": -1, "period": "hours"}, "junk"],
    )
    def test_invalid_override_rejected(self, bad: Any) -> None:
        """Non-positive or unparseable overrides fail coercion (caller logs+skips)."""
        field_info = SnippetsSettings.model_fields["SYNC_INTERVAL"]
        with pytest.raises((ValidationError, ValueError)):
            materialize_override_value(
                SnippetsSettings, "SYNC_INTERVAL", field_info, bad
            )


class TestShippedSyncFilterConfig:
    """Guard the shipped ``settings.yaml`` snippet sync filter declaration.

    ``FILTER_EXTENSIONS`` was never a ``SnippetsSettings`` field, so the shipped
    key was silently dropped by ``extra="ignore"`` and snippet sync ran
    unfiltered. These tests pin the live ``SYNC_FILTER`` key and keep the dead
    key from creeping back in.
    """

    @staticmethod
    def _shipped_settings() -> dict[str, Any]:
        """Load the repository's tracked ``settings.yaml``."""
        return yaml.safe_load((BASE_DIR / "settings.yaml").read_text())

    @staticmethod
    def _iter_keys(node: Any) -> Iterator[str]:
        """Yield every mapping key found anywhere in a parsed YAML document."""
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from TestShippedSyncFilterConfig._iter_keys(value)
        elif isinstance(node, list):
            for item in node:
                yield from TestShippedSyncFilterConfig._iter_keys(item)

    def test_no_dead_filter_extensions_key(self):
        """Assert no section of the shipped config declares the dead key."""
        assert "FILTER_EXTENSIONS" not in set(self._iter_keys(self._shipped_settings()))

    def test_sync_filter_declares_shell_scripts_only(self):
        """Assert the shipped config restricts sync to ``.sh`` via the live field."""
        snippets = self._shipped_settings()["default"]["SEP"]["SNIPPETS"]
        assert snippets["SYNC_FILTER"] == [".sh"]

    def test_shipped_sync_filter_parses_to_extension_filter(self):
        """Verify the shipped value validates into an extension ``SnippetFilter``."""
        snippets = self._shipped_settings()["default"]["SEP"]["SNIPPETS"]
        parsed = SnippetsSettings(SYNC_FILTER=snippets["SYNC_FILTER"])
        assert {SnippetFilter(".sh", SnippetFilterType.EXTENSION)} == parsed.SYNC_FILTER
