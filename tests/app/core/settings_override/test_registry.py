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
    chain_has_advanced,
    field_materializer,
    hot_field,
    hot_field_names,
    is_advanced_field,
    is_hot_reloadable,
    materialize_template,
    materialize_via_owning_model,
    MaterializerContext,
    nested_overridable_field_names,
    preserve_patch_credential_url_value,
    ReloadClassification,
    resolve_nested_field_metadata,
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
    """Assert ``hot_field(materializer=...)`` round-trips the callable through metadata."""
    assert field_materializer(_ProbeWithMaterializer, "value") is materialize_template


def test_hot_field_without_materializer_returns_none() -> None:
    """Assert a HOT field declared without a materializer reports ``None``."""
    assert field_materializer(_ProbeWithoutMaterializer, "value") is None


def test_field_materializer_unknown_field_returns_none() -> None:
    """Assert an unknown field name reports no materializer instead of raising."""
    assert field_materializer(SEPSettings, "DOES_NOT_EXIST") is None


def test_materialize_via_owning_model_runs_before_validator() -> None:
    """Assert ``materialize_via_owning_model`` runs the owning model's before-validator."""
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
    """Assert ``materialize_template`` converts a raw string into a ``Template``."""
    result = materialize_template(_ctx(SEPSettings, "FOOTER_TEMPLATE", "$summary"))
    assert isinstance(result, Template)
    assert result.template == "$summary"


def test_materialize_template_passes_through_existing_template() -> None:
    """Assert ``materialize_template`` returns an already-``Template`` value unchanged."""
    tmpl = Template("$version")
    result = materialize_template(_ctx(SEPSettings, "FOOTER_TEMPLATE", tmpl))
    assert result is tmpl


def test_materialize_template_rejects_non_string() -> None:
    """Reject a non-string, non-``Template`` override instead of passing it through."""
    with pytest.raises(ValueError, match="must be a string"):
        materialize_template(_ctx(SEPSettings, "FOOTER_TEMPLATE", 1))


def test_preserve_patch_credential_url_value_for_scalar_field() -> None:
    """Assert scalar credential URL PATCH values restore the stored password when redacted."""
    field = SEPSettings.model_fields["INVENTORY_ENDPOINT"]
    current = "http://inv-user:inv-secret@inventory.internal:8080"
    incoming = "http://inv-user:****@inventory.internal:8080"
    assert preserve_patch_credential_url_value(field, current, incoming) == current


def test_preserve_patch_credential_url_value_for_materializer_payload() -> None:
    """Assert whole-object materializer PATCH payloads preserve nested endpoint passwords."""
    field = TasksSettings.model_fields["NOMAD"]
    current = {"endpoint": "http://nomad-user:nomad-secret@nomad.internal:4646"}
    incoming = {"endpoint": "http://nomad-user:****@nomad.internal:4646"}
    preserved = preserve_patch_credential_url_value(field, current, incoming)
    assert preserved["endpoint"] == current["endpoint"]


def test_is_hot_reloadable_true_for_marked_field() -> None:
    """Assert a field marked HOT via ``field_with_metadata`` is detected."""
    assert is_hot_reloadable(SEPSettings, "CONNECTIVITY_CHECK_DEFAULT") is True


def test_is_hot_reloadable_true_for_promoted_endpoint() -> None:
    """Assert ``INVENTORY_ENDPOINT`` is promoted to HOT for live endpoint rebind."""
    assert is_hot_reloadable(SEPSettings, "INVENTORY_ENDPOINT") is True


def test_is_hot_reloadable_false_for_structural_field() -> None:
    """Assert structural fields are never overridable."""
    assert is_hot_reloadable(SEPSettings, "APPS") is False


def test_is_hot_reloadable_false_for_missing_field() -> None:
    """Assert an unknown field returns False instead of raising."""
    assert is_hot_reloadable(SEPSettings, "DOES_NOT_EXIST") is False


def test_hot_field_names_sep_settings() -> None:
    """Assert ``SEPSettings`` HOT fields include the endpoint and footer promotions."""
    assert hot_field_names(SEPSettings) == frozenset(
        {
            "CONNECTIVITY_CHECK_DEFAULT",
            "AMBIENT_SESSION_SSO_ENABLED",
            "ARTIFACT_DOWNLOAD_TTL",
            "SYNC_REFRESH_TIME",
            "INVENTORY_ENDPOINT",
            "TASKS_ENDPOINT",
            "FOOTER_TEMPLATE",
        }
    )


def test_hot_field_names_tasks_settings() -> None:
    """Assert ``TasksSettings`` HOT fields exclude ``NOMAD`` but include ``SYNC_LOCK_TTL``."""
    assert hot_field_names(TasksSettings) == frozenset(
        {
            "LOG_STREAM_CAP_BYTES",
            "LOG_STREAM_EVICTION_MAX_ROWS",
            "PRE_EXECUTION_CONNECTIVITY_CHECK",
            "STALENESS_THRESHOLD_SECONDS",
            "SYNC_LOCK_TTL",
            "LOG_RETENTION_DAYS",
            "LOG_PURGE_BATCH_SIZE",
        }
    )


def test_nested_overridable_field_names_sep_settings() -> None:
    """Assert ``SEPSettings`` exposes the session parents plus ``APP_DRAIN``."""
    assert nested_overridable_field_names(SEPSettings) == frozenset(
        {"SESSION", "SESSION_REFRESH", "APP_DRAIN"}
    )


def test_nested_overridable_field_names_tasks_settings() -> None:
    """Assert ``NOMAD`` and ``SECURITY_HEADERS`` are NESTED_ONLY parents on ``TasksSettings``."""
    assert nested_overridable_field_names(TasksSettings) == frozenset(
        {"NOMAD", "SECURITY_HEADERS"}
    )


def test_hot_field_names_snippets_settings() -> None:
    """Expose the HOT preview / sync fields and the sync interval on ``SnippetsSettings``."""
    assert hot_field_names(SnippetsSettings) == frozenset(
        {
            "ENABLE_MANUAL_SYNC",
            "PREVIEW_MAX_CHARS",
            "PREVIEW_MAX_LINES",
            "SYNC_INTERVAL",
            "SNIPPETS_BASE_URL",
            "SYNC_FILTER",
        }
    )


def test_hot_field_names_messages_settings() -> None:
    """Assert ``MessagesSettings`` ships ``LEVEL`` as its single HOT field."""
    assert hot_field_names(MessagesSettings) == frozenset({"LEVEL"})


def test_hot_field_names_inventory_settings_empty() -> None:
    """Assert ``InventorySettings`` has no HOT fields in this iteration."""
    assert hot_field_names(InventorySettings) == frozenset()


def test_field_without_metadata_returns_false() -> None:
    """Assert a field without any ``CustomFieldMetadata`` returns False without raising."""

    class _Plain(BaseModel):
        value: int = 1

    assert is_hot_reloadable(_Plain, "value") is False


def test_metadata_with_other_keys_does_not_trigger_hot() -> None:
    """Assert custom metadata other than ``reload`` does not flip the classification."""

    class _Other(BaseModel):
        value: int = field_with_metadata(1, metadata={"unrelated": "yes"})

    assert is_hot_reloadable(_Other, "value") is False


def test_reload_classification_values() -> None:
    """Assert ``ReloadClassification`` exposes ``HOT`` and ``NOT_OVERRIDABLE`` values."""
    assert ReloadClassification.HOT.value == "hot"
    assert ReloadClassification.NOT_OVERRIDABLE.value == "not_overridable"


@pytest.mark.parametrize(
    "field_name",
    [
        "SESSION",
        "SESSION_REFRESH",
        "INVENTORY_ENDPOINT",
        "TASKS_ENDPOINT",
        "FOOTER_TEMPLATE",
    ],
)
def test_sep_settings_marked_advanced(field_name: str) -> None:
    """Assert the five promoted SEP settings carry the advanced flag."""
    assert is_advanced_field(SEPSettings.model_fields[field_name]) is True


@pytest.mark.parametrize("field_name", ["SYNC_REFRESH_TIME", "APPS", "DATABASE"])
def test_sep_settings_not_marked_advanced(field_name: str) -> None:
    """Assert SEP settings left basic do not carry the advanced flag (no over-marking)."""
    assert is_advanced_field(SEPSettings.model_fields[field_name]) is False


def test_security_headers_marked_advanced() -> None:
    """Assert ``Tasks.SECURITY_HEADERS`` is the only Tasks setting promoted to advanced."""
    assert is_advanced_field(TasksSettings.model_fields["SECURITY_HEADERS"]) is True


@pytest.mark.parametrize("field_name", ["NOMAD", "PRE_EXECUTION_CONNECTIVITY_CHECK"])
def test_tasks_settings_not_marked_advanced(field_name: str) -> None:
    """Assert the ``NOMAD`` parent and other unpromoted Tasks settings stay basic.

    Only the NOMAD *leaves* are advanced, never the parent itself.
    """
    assert is_advanced_field(TasksSettings.model_fields[field_name]) is False


@pytest.mark.parametrize(
    "field_name",
    [
        "SYNC_LOCK_TTL",
        "STALENESS_THRESHOLD_SECONDS",
        "LOG_RETENTION_DAYS",
        "LOG_PURGE_BATCH_SIZE",
        "LOG_STREAM_CAP_BYTES",
        "LOG_STREAM_EVICTION_MAX_ROWS",
    ],
)
def test_tasks_settings_marked_advanced(field_name: str) -> None:
    """Promote the log-retention cluster and lock/staleness TTLs to advanced."""
    assert is_advanced_field(TasksSettings.model_fields[field_name]) is True


def test_session_leaf_inherits_advanced() -> None:
    """Assert every ``SESSION`` leaf inherits the parent's advanced flag."""
    leaf = resolve_nested_field_metadata(SEPSettings, "SESSION__COOKIE_NAME")
    assert leaf is not None
    assert leaf.is_advanced is True


def test_security_headers_deep_leaf_inherits_advanced() -> None:
    """Assert a two-level ``SECURITY_HEADERS`` leaf inherits advanced from the top parent.

    Only ``SECURITY_HEADERS`` is marked; ``strict_transport_security`` and
    ``max_age`` are not, so the chain walk is what propagates the flag down.
    """
    leaf = resolve_nested_field_metadata(
        TasksSettings, "SECURITY_HEADERS__STRICT_TRANSPORT_SECURITY__MAX_AGE"
    )
    assert leaf is not None
    assert leaf.is_advanced is True
    assert chain_has_advanced(
        TasksSettings, "SECURITY_HEADERS__STRICT_TRANSPORT_SECURITY__MAX_AGE"
    )


def test_non_advanced_nested_leaf_stays_false() -> None:
    """Assert a leaf under a non-advanced parent reports ``is_advanced=False``."""
    leaf = resolve_nested_field_metadata(SEPSettings, "DATABASE__NAME")
    assert leaf is not None
    assert leaf.is_advanced is False


def test_advanced_does_not_change_reload_classification() -> None:
    """Assert marking a HOT field advanced leaves its reload classification untouched.

    ``advanced`` is display-only: a marked-advanced HOT endpoint stays HOT (and
    thus still patchable), proving the flag does not gate override eligibility.
    """
    assert is_advanced_field(SEPSettings.model_fields["INVENTORY_ENDPOINT"]) is True
    assert is_hot_reloadable(SEPSettings, "INVENTORY_ENDPOINT") is True


def test_is_advanced_field_false_without_metadata() -> None:
    """Assert a field without any ``CustomFieldMetadata`` reads ``False`` without raising."""

    class _Plain(BaseModel):
        value: int = 1

    assert is_advanced_field(_Plain.model_fields["value"]) is False
