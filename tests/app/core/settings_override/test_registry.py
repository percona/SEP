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

"""Tests for the HOT-classification registry."""

from string import Template

import pytest
from pydantic import BaseModel

from app.core.alerts.config import AlertSettings
from app.core.alerts.models import BaseAlertProvider
from app.core.settings_override.registry import (
    field_materializer,
    hot_field,
    hot_field_names,
    is_hot_reloadable,
    materialize_fingerprint,
    materialize_template,
    materialize_via_owning_model,
    MaterializerContext,
    nested_overridable_field_names,
    ReloadClassification,
)
from app.core.utils.pydantic import field_with_metadata
from app.inventory.config import InventorySettings
from app.sep.config import SEPSettings
from app.sep.middleware.messages.config import MessagesSettings
from app.sep.snippets.config import SnippetsSettings
from app.tasks.config import TasksSettings


def _ctx(settings_cls: type, field_name: str, raw: object) -> MaterializerContext:
    """Build a :class:`MaterializerContext` for the given class field and raw value."""
    return MaterializerContext(
        settings_cls, field_name, settings_cls.model_fields[field_name], raw
    )


class _ProbeWithMaterializer(BaseModel):
    """A probe model whose HOT field declares a materializer."""

    value: str = hot_field("", materializer=materialize_template)


class _ProbeWithoutMaterializer(BaseModel):
    """A probe model whose HOT field declares no materializer."""

    value: str = hot_field("")


def test_hot_field_records_materializer_in_metadata() -> None:
    """``hot_field(materializer=...)`` round-trips the callable through metadata."""
    assert field_materializer(_ProbeWithMaterializer, "value") is materialize_template


def test_hot_field_without_materializer_returns_none() -> None:
    """A HOT field declared without a materializer reports ``None``."""
    assert field_materializer(_ProbeWithoutMaterializer, "value") is None


def test_field_materializer_unknown_field_returns_none() -> None:
    """An unknown field name reports no materializer instead of raising."""
    assert field_materializer(SEPSettings, "DOES_NOT_EXIST") is None


def test_materialize_via_owning_model_runs_before_validator() -> None:
    """``materialize_via_owning_model`` runs the owning model's before-validator."""
    result = materialize_via_owning_model(
        _ctx(
            AlertSettings,
            "PROVIDERS",
            [{"PROVIDER": "pagerduty", "routing_key": "abc123"}],
        )
    )
    assert isinstance(result, set)
    assert all(isinstance(provider, BaseAlertProvider) for provider in result)
    assert len(result) == 1


def test_materialize_template_builds_template_from_string() -> None:
    """``materialize_template`` converts a raw string into a ``Template``."""
    result = materialize_template(_ctx(SEPSettings, "FOOTER_TEMPLATE", "$summary"))
    assert isinstance(result, Template)
    assert result.template == "$summary"


def test_materialize_template_passes_through_existing_template() -> None:
    """``materialize_template`` returns an already-``Template`` value unchanged."""
    tmpl = Template("$version")
    result = materialize_template(_ctx(SEPSettings, "FOOTER_TEMPLATE", tmpl))
    assert result is tmpl


def test_materialize_template_rejects_non_string() -> None:
    """A non-string, non-``Template`` override is rejected instead of passed through."""
    with pytest.raises(ValueError, match="must be a string"):
        materialize_template(_ctx(SEPSettings, "FOOTER_TEMPLATE", 1))


def test_materialize_fingerprint_returns_diff_stable_dict() -> None:
    """``materialize_fingerprint`` returns a plain dict equal across two calls."""
    raw = {"endpoint": "https://nomad.example.org"}
    first = materialize_fingerprint(_ctx(TasksSettings, "NOMAD", raw))
    second = materialize_fingerprint(_ctx(TasksSettings, "NOMAD", raw))
    assert isinstance(first, dict)
    assert first == second


def test_is_hot_reloadable_true_for_marked_field() -> None:
    """A field marked HOT via ``field_with_metadata`` is detected."""
    assert is_hot_reloadable(SEPSettings, "CONNECTIVITY_CHECK_DEFAULT") is True


def test_is_hot_reloadable_true_for_promoted_endpoint() -> None:
    """``INVENTORY_ENDPOINT`` is promoted to HOT for live endpoint rebind."""
    assert is_hot_reloadable(SEPSettings, "INVENTORY_ENDPOINT") is True


def test_is_hot_reloadable_false_for_structural_field() -> None:
    """Structural fields are never overridable."""
    assert is_hot_reloadable(SEPSettings, "PLUGINS") is False


def test_is_hot_reloadable_false_for_missing_field() -> None:
    """An unknown field returns False instead of raising."""
    assert is_hot_reloadable(SEPSettings, "DOES_NOT_EXIST") is False


def test_hot_field_names_sep_settings() -> None:
    """``SEPSettings`` HOT fields include the endpoint and footer promotions."""
    assert hot_field_names(SEPSettings) == frozenset(
        {
            "CONNECTIVITY_CHECK_DEFAULT",
            "ARTIFACT_DOWNLOAD_TTL",
            "SYNC_REFRESH_TIME",
            "INVENTORY_ENDPOINT",
            "TASKS_ENDPOINT",
            "FOOTER_TEMPLATE",
        }
    )


def test_hot_field_names_tasks_settings() -> None:
    """``TasksSettings`` HOT fields include ``NOMAD`` after its promotion."""
    assert hot_field_names(TasksSettings) == frozenset(
        {"PRE_EXECUTION_CONNECTIVITY_CHECK", "STALENESS_THRESHOLD_SECONDS", "NOMAD"}
    )


def test_nested_overridable_field_names_sep_settings() -> None:
    """``SEPSettings`` ships exactly the two NESTED_ONLY parents this ticket promotes."""
    assert nested_overridable_field_names(SEPSettings) == frozenset(
        {"SESSION", "SESSION_REFRESH"}
    )


def test_nested_overridable_field_names_tasks_settings() -> None:
    """``SECURITY_HEADERS`` is the NESTED_ONLY parent on ``TasksSettings``.

    ``NOMAD`` is HOT (whole-object override materializes a config fingerprint
    that the lifecycle holder rebinds), so it is not in the NESTED_ONLY set even
    though HOT also accepts per-child overrides.
    """
    assert nested_overridable_field_names(TasksSettings) == frozenset(
        {"SECURITY_HEADERS"}
    )


def test_hot_field_names_snippets_settings() -> None:
    """``SnippetsSettings`` ships its three HOT preview / sync fields."""
    assert hot_field_names(SnippetsSettings) == frozenset(
        {"ENABLE_MANUAL_SYNC", "PREVIEW_MAX_CHARS", "PREVIEW_MAX_LINES"}
    )


def test_hot_field_names_messages_settings() -> None:
    """``MessagesSettings`` ships ``LEVEL`` as its single HOT field."""
    assert hot_field_names(MessagesSettings) == frozenset({"LEVEL"})


def test_hot_field_names_inventory_settings_empty() -> None:
    """``InventorySettings`` has no HOT fields in this iteration."""
    assert hot_field_names(InventorySettings) == frozenset()


def test_field_without_metadata_returns_false() -> None:
    """A field without any ``CustomFieldMetadata`` returns False without raising."""

    class _Plain(BaseModel):
        value: int = 1

    assert is_hot_reloadable(_Plain, "value") is False


def test_metadata_with_other_keys_does_not_trigger_hot() -> None:
    """Custom metadata other than ``reload`` does not flip the classification."""

    class _Other(BaseModel):
        value: int = field_with_metadata(1, metadata={"unrelated": "yes"})

    assert is_hot_reloadable(_Other, "value") is False


def test_reload_classification_values() -> None:
    """``ReloadClassification`` exposes ``HOT`` and ``NOT_OVERRIDABLE`` values."""
    assert ReloadClassification.HOT.value == "hot"
    assert ReloadClassification.NOT_OVERRIDABLE.value == "not_overridable"
