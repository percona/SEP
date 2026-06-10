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

"""Unit tests for the field-introspection helpers in ``registry.py``."""

from datetime import timedelta
from typing import ClassVar

import pytest
from pydantic import BaseModel, Field, PositiveInt, SecretStr, ValidationError

from app.core.config import BaseYamlSettings
from app.core.settings_override.api.routes import _settings_response_from_field
from app.core.settings_override.models import SettingClassEnum
from app.core.settings_override.proxy import OverridableSettingsProxy
from app.core.settings_override.registry import (
    coerce_field_value,
    dump_field_value,
    hot_field,
    iter_class_fields,
    iter_nested_leaf_keys,
    nested_overridable_field,
    ReloadClassification,
    resolve_nested_field_metadata,
)


class _NestedWithSecret(BaseModel):
    """Submodel exposing a top-level ``SecretStr`` for nesting tests."""

    name: str
    token: SecretStr


class _FixtureSettings(BaseYamlSettings):
    """Synthetic settings class exercising every helper branch."""

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["FIXTURE"]

    HOT_INT: PositiveInt = hot_field(10)
    HOT_BOOL: bool = hot_field(default=True)
    COLD_STRING: str = "default"
    COLD_TIMEDELTA: timedelta = timedelta(minutes=5)
    COLD_NESTED: _NestedWithSecret = _NestedWithSecret(
        name="alice", token=SecretStr("s3cr3t")
    )
    COLD_TOP_SECRET: SecretStr = SecretStr("top-secret")
    COLD_OPTIONAL: int | None = None


def test_coerce_field_value_preserves_positive_int_constraint() -> None:
    """A ``PositiveInt`` field rejects ``-1`` via the preserved ``Gt(0)`` metadata."""
    field = _FixtureSettings.model_fields["HOT_INT"]
    with pytest.raises(ValidationError):
        coerce_field_value(field, -1)


def test_coerce_field_value_accepts_valid_int() -> None:
    """A ``PositiveInt`` field accepts a valid positive integer."""
    valid_int = 42
    field = _FixtureSettings.model_fields["HOT_INT"]
    assert coerce_field_value(field, valid_int) == valid_int


def test_coerce_field_value_rejects_wrong_type() -> None:
    """A ``bool`` field rejects a string that is not bool-parseable."""
    field = _FixtureSettings.model_fields["HOT_BOOL"]
    with pytest.raises(ValidationError):
        coerce_field_value(field, "not-a-bool")


def test_iter_class_fields_yields_every_field() -> None:
    """Every declared field on the synthetic class is surfaced."""
    fields = {meta.key for meta in iter_class_fields(_FixtureSettings)}
    expected = {
        "FASTAPI_ENV",
        "HOT_INT",
        "HOT_BOOL",
        "COLD_STRING",
        "COLD_TIMEDELTA",
        "COLD_NESTED",
        "COLD_TOP_SECRET",
        "COLD_OPTIONAL",
    }
    assert expected.issubset(fields)


def test_iter_class_fields_classifies_hot_and_cold() -> None:
    """HOT fields are marked HOT; everything else is NOT_OVERRIDABLE."""
    classification = {
        meta.key: meta.reload for meta in iter_class_fields(_FixtureSettings)
    }
    assert classification["HOT_INT"] is ReloadClassification.HOT
    assert classification["HOT_BOOL"] is ReloadClassification.HOT
    assert classification["COLD_STRING"] is ReloadClassification.NOT_OVERRIDABLE
    assert classification["COLD_NESTED"] is ReloadClassification.NOT_OVERRIDABLE


def test_iter_class_fields_marks_top_level_secret() -> None:
    """A top-level ``SecretStr`` field is flagged ``is_secret=True``."""
    metas = {meta.key: meta for meta in iter_class_fields(_FixtureSettings)}
    assert metas["COLD_TOP_SECRET"].is_secret is True


def test_iter_class_fields_marks_nested_secret() -> None:
    """A nested ``SecretStr`` inside a submodel is flagged ``is_secret=True``."""
    metas = {meta.key: meta for meta in iter_class_fields(_FixtureSettings)}
    assert metas["COLD_NESTED"].is_secret is True


def test_iter_class_fields_marks_complex_submodel() -> None:
    """A field whose annotation is a Pydantic ``BaseModel`` is flagged ``is_complex``."""
    metas = {meta.key: meta for meta in iter_class_fields(_FixtureSettings)}
    assert metas["COLD_NESTED"].is_complex is True
    assert metas["HOT_INT"].is_complex is False


def test_dump_field_value_serialises_timedelta_to_iso8601() -> None:
    """A ``timedelta`` value is dumped to its ISO 8601 duration string."""
    field = _FixtureSettings.model_fields["COLD_TIMEDELTA"]
    dumped = dump_field_value(field, timedelta(minutes=5))
    assert dumped == "PT5M"


def test_dump_field_value_redacts_secret_str() -> None:
    """A ``SecretStr`` value is redacted by Pydantic's JSON dump."""
    field = _FixtureSettings.model_fields["COLD_TOP_SECRET"]
    dumped = dump_field_value(field, SecretStr("hunter2"))
    assert dumped == "**********"


def test_dump_field_value_redacts_nested_secret() -> None:
    """A nested ``SecretStr`` inside a submodel is redacted in the dumped dict."""
    field = _FixtureSettings.model_fields["COLD_NESTED"]
    dumped = dump_field_value(
        field, _NestedWithSecret(name="bob", token=SecretStr("hunter2"))
    )
    assert dumped == {"name": "bob", "token": "**********"}


class _NoDefault(BaseYamlSettings):
    """Synthetic settings class with a required HOT field (no default)."""

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["NODEF"]
    BARE: int = hot_field(...)


def test_dump_field_value_returns_none_for_undefined_default() -> None:
    """A field with no declared default dumps to ``None`` instead of raising."""
    field = _NoDefault.model_fields["BARE"]
    assert dump_field_value(field, field.default) is None


class _WithFactory(BaseYamlSettings):
    """Synthetic settings class with a field declared via ``default_factory``."""

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["FACTORY"]
    ITEMS: list[str] = Field(default_factory=lambda: ["alpha", "beta"])


def test_iter_class_fields_invokes_default_factory() -> None:
    """``default_factory`` is invoked so the metadata holds the actual default value."""
    metas = {meta.key: meta for meta in iter_class_fields(_WithFactory)}
    assert metas["ITEMS"].default == ["alpha", "beta"]


class _Unschemable:
    """A non-Pydantic type with no overridden ``__str__`` (default object repr)."""


class _WithUnschemableAnnotation(BaseYamlSettings):
    """Synthetic settings class whose field annotation Pydantic can't schemafy."""

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["UNSCHEMABLE"]
    model_config = {"arbitrary_types_allowed": True}
    OPAQUE: _Unschemable = _Unschemable()


def test_dump_field_value_returns_none_for_unschemable_annotation() -> None:
    """Unschemable annotations dump to ``None`` rather than an unstable object repr."""
    field = _WithUnschemableAnnotation.model_fields["OPAQUE"]
    assert dump_field_value(field, _Unschemable()) is None


class _SecretLeafModel(BaseModel):
    """Submodel carrying a secret leaf under a nested-overridable parent."""

    TOKEN: SecretStr = SecretStr("s3cr3t")
    LABEL: str = "public"


class _SecretLeafParent(BaseModel):
    """Model declaring a nested-overridable parent over a secret submodel."""

    GROUP: _SecretLeafModel = nested_overridable_field(_SecretLeafModel())


def test_iter_nested_leaf_keys_enumerates_secret_leaf() -> None:
    """A nested-overridable parent enumerates its secret leaf alongside siblings."""
    leaves = dict(iter_nested_leaf_keys(_SecretLeafParent, "GROUP"))
    assert set(leaves) == {"GROUP__TOKEN", "GROUP__LABEL"}


def test_settings_response_redacts_secret_leaf_with_key_path() -> None:
    """A secret leaf response redacts the value and carries the canonical key_path."""
    proxy = OverridableSettingsProxy(
        _SecretLeafParent, setting_class=SettingClassEnum.SEP_SETTINGS
    )
    leaf_meta = resolve_nested_field_metadata(_SecretLeafParent, "GROUP__TOKEN")
    assert leaf_meta is not None
    response = _settings_response_from_field(
        setting_class=SettingClassEnum.SEP_SETTINGS,
        settings_cls=_SecretLeafParent,
        proxy=proxy,
        field_meta=leaf_meta,
        has_override=False,
    )
    assert response.value == "**********"
    assert response.is_secret is True
    assert response.key_path == ["GROUP", "TOKEN"]
