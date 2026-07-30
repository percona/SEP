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
from typing import ClassVar

import pytest
from pydantic import BaseModel, SecretStr

from app.core.alerts.config import AlertSettings
from app.core.alerts.models import BaseAlertProvider
from app.core.alerts.providers.pagerduty import PagerDutyEventsAlertProvider
from app.core.settings_override.registry import (
    chain_has_advanced,
    dump_field_value,
    field_materializer,
    field_reload_classification,
    hot_field,
    hot_field_names,
    is_advanced_field,
    is_explicit_not_overridable,
    is_hot_reloadable,
    iter_class_fields,
    materialize_template,
    materialize_via_owning_model,
    MaterializerContext,
    nested_overridable_field_names,
    preserve_patch_credential_url_value,
    ReloadClassification,
    resolve_nested_field_metadata,
    SECRET_STR_MASK,
    unwrap_secrets_for_storage,
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


class _SecretLeafModel(BaseModel):
    """Nested model with a scalar SecretStr leaf (PMM-shaped)."""

    api_key: SecretStr
    label: str = "ok"


class _TopLevelSecretSettings(BaseModel):
    """Fixture settings class with a top-level SecretStr field."""

    TOKEN: SecretStr = hot_field(SecretStr("stored-top-secret"))


class _NestedSecretSettings(BaseModel):
    """Fixture settings class with a nested model that holds a SecretStr."""

    GROUP: _SecretLeafModel = hot_field(
        _SecretLeafModel(api_key=SecretStr("stored-nested-secret"))
    )


class _DictSecretSettings(BaseModel):
    """Fixture settings class with a ``dict[str, SecretStr]`` field."""

    secrets: dict[str, SecretStr] = hot_field(
        {"api_key": SecretStr("stored-dict-secret"), "token": SecretStr("keep-me")}
    )


def test_preserve_patch_secret_value_for_top_level_field() -> None:
    """Assert a masked top-level SecretStr PATCH restores the stored secret."""
    field = _TopLevelSecretSettings.model_fields["TOKEN"]
    current = SecretStr("stored-top-secret")
    assert (
        preserve_patch_credential_url_value(field, current, SECRET_STR_MASK)
        == "stored-top-secret"
    )


def test_preserve_patch_secret_value_for_nested_leaf() -> None:
    """Assert a masked SecretStr on a nested model's leaf FieldInfo restores the stored secret."""
    field = _SecretLeafModel.model_fields["api_key"]
    current = SecretStr("stored-nested-secret")
    assert (
        preserve_patch_credential_url_value(field, current, SECRET_STR_MASK)
        == "stored-nested-secret"
    )


def test_preserve_patch_secret_value_overwrites_with_real_value() -> None:
    """Assert a non-mask SecretStr PATCH keeps the newly submitted value."""
    field = _TopLevelSecretSettings.model_fields["TOKEN"]
    current = SecretStr("stored-top-secret")
    assert (
        preserve_patch_credential_url_value(field, current, "brand-new-secret")
        == "brand-new-secret"
    )


def test_preserve_patch_secret_value_for_nested_model_payload() -> None:
    """Assert a whole-object nested-model PATCH restores masked SecretStr leaves."""
    field = _NestedSecretSettings.model_fields["GROUP"]
    current = _SecretLeafModel(api_key=SecretStr("stored-nested-secret"), label="ok")
    incoming = {"api_key": SECRET_STR_MASK, "label": "ok"}
    preserved = preserve_patch_credential_url_value(field, current, incoming)
    assert preserved["api_key"] == "stored-nested-secret"
    assert preserved["label"] == "ok"


def test_preserve_patch_secret_value_for_dict_of_secrets() -> None:
    """Assert masked values inside ``dict[str, SecretStr]`` are restored per key."""
    field = _DictSecretSettings.model_fields["secrets"]
    current = {
        "api_key": SecretStr("stored-dict-secret"),
        "token": SecretStr("keep-me"),
    }
    incoming = {"api_key": SECRET_STR_MASK, "token": "replacement-token"}
    preserved = preserve_patch_credential_url_value(field, current, incoming)
    assert preserved["api_key"] == "stored-dict-secret"
    assert preserved["token"] == "replacement-token"


def test_preserve_patch_secret_value_for_polymorphic_provider_set() -> None:
    """Assert masked subclass secrets in ``set[BaseAlertProvider]`` are restored."""
    field = AlertSettings.model_fields["PROVIDERS"]
    current = {PagerDutyEventsAlertProvider(routing_key=SecretStr("real-routing-key"))}
    incoming = [
        {
            "PROVIDER": "pagerduty",
            "routing_key": SECRET_STR_MASK,
            "api_endpoint": "https://events.pagerduty.com/v2/",
        }
    ]
    preserved = preserve_patch_credential_url_value(field, current, incoming)
    assert preserved[0]["routing_key"] == "real-routing-key"
    assert preserved[0]["PROVIDER"] == "pagerduty"


def test_preserve_patch_secret_value_for_two_pagerduty_providers() -> None:
    """Assert two same-type PROVIDERS restore by identity, not hash set order.

    Distinct ``api_endpoint`` values identify each entry when both routing keys
    are masked. Incoming order deliberately disagrees with sorted set order so
    positional pairing alone would swap secrets.
    """
    field = AlertSettings.model_fields["PROVIDERS"]
    first = PagerDutyEventsAlertProvider(
        routing_key=SecretStr("routing-key-a"),
        api_endpoint="https://events-a.example/v2/",
    )
    second = PagerDutyEventsAlertProvider(
        routing_key=SecretStr("routing-key-b"),
        api_endpoint="https://events-b.example/v2/",
    )
    incoming = [
        {
            "PROVIDER": "pagerduty",
            "routing_key": SECRET_STR_MASK,
            "api_endpoint": "https://events-b.example/v2/",
        },
        {
            "PROVIDER": "pagerduty",
            "routing_key": SECRET_STR_MASK,
            "api_endpoint": "https://events-a.example/v2/",
        },
    ]
    preserved = preserve_patch_credential_url_value(field, {first, second}, incoming)
    assert preserved[0]["routing_key"] == "routing-key-b"
    assert preserved[0]["api_endpoint"] == "https://events-b.example/v2/"
    assert preserved[1]["routing_key"] == "routing-key-a"
    assert preserved[1]["api_endpoint"] == "https://events-a.example/v2/"


def test_preserve_patch_secret_value_for_two_pagerduty_providers_same_endpoint() -> (
    None
):
    """Assert identical non-secret fields still restore via stable set order.

    When both entries share ``api_endpoint`` and both secrets are masked, GET
    dump order (stable sort by routing key) is the only identity signal.
    """
    field = AlertSettings.model_fields["PROVIDERS"]
    first = PagerDutyEventsAlertProvider(routing_key=SecretStr("routing-key-a"))
    second = PagerDutyEventsAlertProvider(routing_key=SecretStr("routing-key-b"))
    dumped = dump_field_value(field, {second, first})
    assert dumped[0]["routing_key"] == SECRET_STR_MASK
    assert dumped[1]["routing_key"] == SECRET_STR_MASK
    incoming = [
        {
            "PROVIDER": "pagerduty",
            "routing_key": SECRET_STR_MASK,
            "api_endpoint": dumped[0]["api_endpoint"],
        },
        {
            "PROVIDER": "pagerduty",
            "routing_key": SECRET_STR_MASK,
            "api_endpoint": dumped[1]["api_endpoint"],
        },
    ]
    preserved = preserve_patch_credential_url_value(field, {second, first}, incoming)
    assert preserved[0]["routing_key"] == "routing-key-a"
    assert preserved[1]["routing_key"] == "routing-key-b"


def test_preserve_patch_secret_value_for_list_of_models() -> None:
    """Assert masked secrets inside ``list[Model]`` whole-object PATCHes are restored."""

    class _Leaf(BaseModel):
        api_key: SecretStr
        label: str = "ok"

    class _ListSecretSettings(BaseModel):
        items: list[_Leaf] = hot_field([])

    field = _ListSecretSettings.model_fields["items"]
    current = [_Leaf(api_key=SecretStr("stored-list-secret"), label="a")]
    incoming = [{"api_key": SECRET_STR_MASK, "label": "a"}]
    preserved = preserve_patch_credential_url_value(field, current, incoming)
    assert preserved[0]["api_key"] == "stored-list-secret"
    assert preserved[0]["label"] == "a"


def test_preserve_patch_secret_value_for_list_of_secrets() -> None:
    """Assert masked elements inside ``list[SecretStr]`` are restored by index."""

    class _ListOfSecretsSettings(BaseModel):
        tokens: list[SecretStr] = hot_field([])

    field = _ListOfSecretsSettings.model_fields["tokens"]
    current = [SecretStr("keep-first"), SecretStr("keep-second")]
    incoming = [SECRET_STR_MASK, "brand-new-second"]
    preserved = preserve_patch_credential_url_value(field, current, incoming)
    assert preserved == ["keep-first", "brand-new-second"]


def test_preserve_patch_secret_value_for_set_of_secrets() -> None:
    """Assert masked elements inside ``set[SecretStr]`` restore via stable order."""

    class _SetOfSecretsSettings(BaseModel):
        tokens: set[SecretStr] = hot_field(set())

    field = _SetOfSecretsSettings.model_fields["tokens"]
    current = {SecretStr("keep-a"), SecretStr("keep-b")}
    dumped = dump_field_value(field, current)
    assert dumped == [SECRET_STR_MASK, SECRET_STR_MASK]
    preserved = preserve_patch_credential_url_value(field, current, dumped)
    assert preserved == ["keep-a", "keep-b"]
    preserved_partial = preserve_patch_credential_url_value(
        field, current, [SECRET_STR_MASK, "brand-new-b"]
    )
    assert preserved_partial == ["keep-a", "brand-new-b"]


def test_providers_field_reports_is_secret() -> None:
    """Assert ``PROVIDERS`` is flagged secret via subclass ``SecretStr`` fields."""
    meta = next(m for m in iter_class_fields(AlertSettings) if m.key == "PROVIDERS")
    assert meta.is_secret is True


def test_unwrap_secrets_for_storage_scalar_secret() -> None:
    """Assert a SecretStr is persisted as plaintext, not the JSON mask."""
    assert (
        unwrap_secrets_for_storage(SecretStr("stored-top-secret"))
        == "stored-top-secret"
    )


def test_unwrap_secrets_for_storage_nested_model() -> None:
    """Assert SecretStr leaves inside a model dump to plaintext for JSON storage."""
    current = _SecretLeafModel(api_key=SecretStr("stored-nested-secret"), label="ok")
    assert unwrap_secrets_for_storage(current) == {
        "api_key": "stored-nested-secret",
        "label": "ok",
    }


def test_unwrap_secrets_for_storage_dict_of_secrets() -> None:
    """Assert secret-valued dict entries unwrap per key."""
    current = {
        "api_key": SecretStr("stored-dict-secret"),
        "token": SecretStr("keep-me"),
    }
    assert unwrap_secrets_for_storage(current) == {
        "api_key": "stored-dict-secret",
        "token": "keep-me",
    }


def test_unwrap_secrets_for_storage_passes_through_non_secrets() -> None:
    """Assert non-secret scalars and mappings are unchanged."""
    assert unwrap_secrets_for_storage("plain") == "plain"
    assert unwrap_secrets_for_storage({"a": 1}) == {"a": 1}


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
    """``SEPSettings`` ships the promoted HOT fields plus runtime toggles.

    Includes the endpoint and footer promotions and the ambient-SSO toggle.
    """
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


class _OverlayProbe(BaseModel):
    """Define a probe carrying an ``INHERITED_MARKERS`` overlay over otherwise-bare fields.

    ``inherited_leaf`` is a plain (unmarked) field promoted purely by the
    overlay, mirroring the inherited-field use case. ``plain_leaf`` has no
    overlay entry and must classify exactly as it would without the mechanism.
    ``conflicting`` carries an explicit ``NOT_OVERRIDABLE`` marker that the
    overlay must not override. ``ghost_field`` is an overlay entry naming a field
    that does not exist on the model, to prove such entries are safely ignored.
    """

    INHERITED_MARKERS: ClassVar[dict[str, dict[str, object]]] = {
        "inherited_leaf": {"reload": ReloadClassification.HOT, "advanced": True},
        "conflicting": {"reload": ReloadClassification.HOT, "advanced": True},
        "ghost_field": {"advanced": True},
    }
    inherited_leaf: int = 1
    plain_leaf: int = 2
    conflicting: int = field_with_metadata(
        3, metadata={"reload": ReloadClassification.NOT_OVERRIDABLE}
    )


def test_overlay_promotes_bare_inherited_field() -> None:
    """Assert an overlay entry marks a bare field ``advanced`` + HOT via owner context."""
    info = _OverlayProbe.model_fields["inherited_leaf"]
    assert is_advanced_field(info, owner_cls=_OverlayProbe, field_name="inherited_leaf")
    assert (
        field_reload_classification(
            info, owner_cls=_OverlayProbe, field_name="inherited_leaf"
        )
        is ReloadClassification.HOT
    )
    assert is_hot_reloadable(_OverlayProbe, "inherited_leaf") is True


def test_overlay_bare_call_is_unchanged_fast_path() -> None:
    """Assert calling classifiers with only a bare ``FieldInfo`` ignores the overlay."""
    info = _OverlayProbe.model_fields["inherited_leaf"]
    assert is_advanced_field(info) is False
    assert field_reload_classification(info) is ReloadClassification.NOT_OVERRIDABLE


def test_overlay_is_opt_in_per_field() -> None:
    """Assert a field with no overlay entry classifies exactly as today."""
    info = _OverlayProbe.model_fields["plain_leaf"]
    assert (
        is_advanced_field(info, owner_cls=_OverlayProbe, field_name="plain_leaf")
        is False
    )
    assert (
        field_reload_classification(
            info, owner_cls=_OverlayProbe, field_name="plain_leaf"
        )
        is ReloadClassification.NOT_OVERRIDABLE
    )


def test_overlay_does_not_override_explicit_field_metadata() -> None:
    """Assert the field's own marker wins; the overlay only fills absent keys.

    ``conflicting`` explicitly declares ``NOT_OVERRIDABLE`` -- the overlay's
    ``HOT`` must not win -- while ``advanced`` (absent on the field) is filled.
    """
    info = _OverlayProbe.model_fields["conflicting"]
    assert (
        field_reload_classification(
            info, owner_cls=_OverlayProbe, field_name="conflicting"
        )
        is ReloadClassification.NOT_OVERRIDABLE
    )
    assert is_explicit_not_overridable(
        info, owner_cls=_OverlayProbe, field_name="conflicting"
    )
    assert is_advanced_field(info, owner_cls=_OverlayProbe, field_name="conflicting")


def test_overlay_entry_for_absent_field_is_ignored() -> None:
    """Assert an overlay entry naming a field absent from the model is harmless.

    ``ghost_field`` has an overlay entry but no matching model field, so no
    classifier ever resolves it and its presence must not affect the real fields.
    """
    assert "ghost_field" not in _OverlayProbe.model_fields
    assert (
        is_advanced_field(
            _OverlayProbe.model_fields["plain_leaf"],
            owner_cls=_OverlayProbe,
            field_name="plain_leaf",
        )
        is False
    )


class _OverlayMaterializerProbe(BaseModel):
    """Define a probe whose overlay supplies a materializer for an otherwise-bare field.

    ``inherited_leaf`` declares no materializer of its own; the overlay attaches
    one. ``own`` declares its own materializer that the overlay must not shadow.
    """

    INHERITED_MARKERS: ClassVar[dict[str, dict[str, object]]] = {
        "inherited_leaf": {
            "reload": ReloadClassification.HOT,
            "materializer": materialize_template,
        },
    }
    inherited_leaf: str = ""
    own: str = hot_field("", materializer=materialize_template)


def test_overlay_supplies_materializer_for_bare_field() -> None:
    """Assert ``field_materializer`` honors an overlay-supplied materializer."""
    assert (
        field_materializer(_OverlayMaterializerProbe, "inherited_leaf")
        is materialize_template
    )


def test_overlay_materializer_does_not_shadow_own_field() -> None:
    """Assert a field's own materializer wins over an (absent) overlay entry."""
    assert field_materializer(_OverlayMaterializerProbe, "own") is materialize_template


@pytest.mark.parametrize(
    "overlay",
    [None, {}, "not-a-dict", {"value": "not-a-dict-entry"}],
)
def test_overlay_malformed_or_absent_is_harmless(overlay: object) -> None:
    """Assert an absent, empty, or malformed overlay never affects classification or raises."""

    class _Probe(BaseModel):
        value: int = 1

    if overlay is not None:
        _Probe.INHERITED_MARKERS = overlay  # type: ignore[attr-defined]

    info = _Probe.model_fields["value"]
    assert is_advanced_field(info, owner_cls=_Probe, field_name="value") is False
    assert (
        field_reload_classification(info, owner_cls=_Probe, field_name="value")
        is ReloadClassification.NOT_OVERRIDABLE
    )
