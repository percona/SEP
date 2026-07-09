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

"""Tests for the nested-override helpers in the classification registry."""

import functools
from datetime import timedelta
from typing import ClassVar

import pytest
from pydantic import BaseModel, SecretStr, ValidationError

from app.core.middleware.security_headers import SecurityHeadersOptions
from app.core.settings_override.api.routes import _settings_response_from_field
from app.core.settings_override.models import SettingClassEnum
from app.core.settings_override.proxy import OverridableSettingsProxy
from app.core.settings_override.registry import (
    _clear_cached_properties,
    _resolve_field_in_model,
    canonical_override_key,
    chain_has_advanced,
    chain_has_explicit_not_overridable,
    coerce_nested_field_value,
    is_hot_reloadable,
    is_nested_overridable_parent,
    iter_nested_leaf_keys,
    nested_overridable_field,
    NESTED_VALUE_MISSING,
    not_overridable_field,
    ReloadClassification,
    resolve_nested_field,
    resolve_nested_field_metadata,
    resolve_nested_value,
)
from app.sep.config import SEPSettings, SessionOptions
from app.tasks.config import TasksSettings


class _Leaf(BaseModel):
    """Leaf model nested under an explicitly not-overridable intermediate."""

    VALUE: int = 1


class _Inner(BaseModel):
    """Inner model used to exercise nested classification helpers."""

    BARE: int = 1
    LOCKED: int = not_overridable_field(2)
    LOCKED_SUB: _Leaf = not_overridable_field(_Leaf())


class _Outer(BaseModel):
    """Outer model declaring a nested-overridable parent."""

    NESTED: _Inner = nested_overridable_field(_Inner())
    PLAIN: int = 5


class _CachedModel(BaseModel):
    """Model with a ``cached_property`` to exercise the memo-clearing helper."""

    value: int = 1

    @functools.cached_property
    def derived(self) -> int:
        """Return a value derived from ``value`` (memoised)."""
        return self.value * 10


def test_resolve_field_in_model_exact_match() -> None:
    """An exact attribute-name match returns the canonical name and field."""
    resolved = _resolve_field_in_model(SessionOptions, "MAX_AGE")
    assert resolved is not None
    canonical, _ = resolved
    assert canonical == "MAX_AGE"


def test_resolve_field_in_model_uppercase_alias_match() -> None:
    """An uppercase alias resolves to the lowercase canonical attribute name.

    ``SecurityHeadersOptions`` is a ``BaseCaseInsensitiveModel`` whose
    attribute names are lowercase but whose aliases are uppercase.
    """
    resolved = _resolve_field_in_model(SecurityHeadersOptions, "X_FRAME_OPTIONS_DENY")
    assert resolved is not None
    canonical, _ = resolved
    assert canonical == "x_frame_options_deny"


def test_resolve_field_in_model_lowercase_fallback() -> None:
    """A lowercase segment resolves to the lowercase canonical attribute name."""
    resolved = _resolve_field_in_model(SecurityHeadersOptions, "x_frame_options_deny")
    assert resolved is not None
    canonical, _ = resolved
    assert canonical == "x_frame_options_deny"


def test_resolve_field_in_model_missing_segment() -> None:
    """An unknown segment returns ``None``."""
    assert _resolve_field_in_model(SessionOptions, "NOPE") is None


def test_resolve_nested_field_single_level() -> None:
    """A single-level key resolves to a one-segment chain and its leaf field."""
    resolved = resolve_nested_field(SEPSettings, "SESSION__MAX_AGE")
    assert resolved is not None
    chain, _ = resolved
    assert chain == ("SESSION", "MAX_AGE")


def test_resolve_nested_field_multi_level() -> None:
    """A multi-level key descends through nested models to the leaf."""
    resolved = resolve_nested_field(
        TasksSettings, "SECURITY_HEADERS__STRICT_TRANSPORT_SECURITY__MAX_AGE"
    )
    assert resolved is not None
    chain, _ = resolved
    assert chain == ("SECURITY_HEADERS", "strict_transport_security", "max_age")


def test_resolve_nested_field_unknown_top_level() -> None:
    """An unknown top-level segment resolves to ``None``."""
    assert resolve_nested_field(SEPSettings, "BOGUS__X") is None


def test_resolve_nested_field_unknown_nested_leaf() -> None:
    """An unknown nested leaf resolves to ``None``."""
    assert resolve_nested_field(SEPSettings, "SESSION__BOGUS") is None


def test_resolve_nested_field_non_pydantic_intermediate() -> None:
    """A path whose intermediate is a collection (not a model) resolves to ``None``."""
    assert resolve_nested_field(SEPSettings, "APPS__0__NAME") is None


def test_resolve_nested_field_primitive_past_leaf() -> None:
    """A path that descends past a primitive leaf resolves to ``None``."""
    assert resolve_nested_field(SEPSettings, "SESSION__MAX_AGE__SUB") is None


def test_resolve_nested_field_empty_key() -> None:
    """An empty key resolves to ``None``."""
    assert resolve_nested_field(SEPSettings, "") is None


def test_coerce_nested_field_value_success() -> None:
    """A leaf value is coerced to the leaf's declared type (int → timedelta)."""
    chain, value = coerce_nested_field_value(SEPSettings, "SESSION__MAX_AGE", 3600)
    assert chain == ("SESSION", "MAX_AGE")
    assert value == timedelta(seconds=3600)


def test_coerce_nested_field_value_preserves_constraint() -> None:
    """The leaf's constraint metadata (``Gt(0)``) is enforced during coercion."""
    with pytest.raises(ValidationError):
        coerce_nested_field_value(
            TasksSettings,
            "SECURITY_HEADERS__STRICT_TRANSPORT_SECURITY__MAX_AGE",
            0,
        )


def test_coerce_nested_field_value_unresolvable_raises_keyerror() -> None:
    """An unresolvable path raises ``KeyError``."""
    with pytest.raises(KeyError):
        coerce_nested_field_value(SEPSettings, "SESSION__BOGUS", 1)


def test_coerce_nested_field_value_rejects_not_overridable_leaf() -> None:
    """A leaf explicitly marked ``not_overridable_field`` raises ``KeyError``."""
    with pytest.raises(KeyError):
        coerce_nested_field_value(_Outer, "NESTED__LOCKED", 9)


def test_coerce_nested_field_value_rejects_not_overridable_intermediate() -> None:
    """A leaf under an explicitly not-overridable *intermediate* raises ``KeyError``.

    ``NESTED.LOCKED_SUB`` is marked ``not_overridable_field``; even though its
    own ``VALUE`` leaf is unmarked, the intermediate marker must block the
    override of any descendant.
    """
    with pytest.raises(KeyError):
        coerce_nested_field_value(_Outer, "NESTED__LOCKED_SUB__VALUE", 9)


def test_chain_has_explicit_not_overridable_flags_intermediate() -> None:
    """The chain check reports a not-overridable intermediate, not only the leaf."""
    assert chain_has_explicit_not_overridable(_Outer, "NESTED__LOCKED_SUB__VALUE")


def test_chain_has_explicit_not_overridable_flags_leaf() -> None:
    """The chain check reports an explicitly not-overridable leaf."""
    assert chain_has_explicit_not_overridable(_Outer, "NESTED__LOCKED")


def test_chain_has_explicit_not_overridable_false_for_open_path() -> None:
    """A fully overridable path reports no explicit not-overridable segment."""
    assert not chain_has_explicit_not_overridable(_Outer, "NESTED__BARE")


def test_chain_has_explicit_not_overridable_false_for_unresolvable() -> None:
    """An unresolvable path reports ``False`` (resolution failure surfaces elsewhere)."""
    assert not chain_has_explicit_not_overridable(_Outer, "NESTED__BOGUS")


def test_clear_cached_properties_removes_memo() -> None:
    """A populated ``cached_property`` memo is removed from ``__dict__``."""
    instance = _CachedModel(value=2)
    assert instance.derived == instance.value * 10  # populate the memo
    assert "derived" in instance.__dict__
    _clear_cached_properties(instance)
    assert "derived" not in instance.__dict__


def test_clear_cached_properties_noop_when_unpopulated() -> None:
    """Clearing an instance with no populated memo is a no-op."""
    instance = _CachedModel(value=2)
    _clear_cached_properties(instance)
    assert "derived" not in instance.__dict__


def test_not_overridable_field_detected_as_not_hot() -> None:
    """A ``not_overridable_field`` leaf is not HOT."""
    assert is_hot_reloadable(_Inner, "LOCKED") is False


def test_is_nested_overridable_parent_true_for_nested_field() -> None:
    """A ``nested_overridable_field`` parent is nested-overridable."""
    assert is_nested_overridable_parent(_Outer, "NESTED") is True


def test_is_nested_overridable_parent_false_for_plain_field() -> None:
    """An unmarked field is not nested-overridable."""
    assert is_nested_overridable_parent(_Outer, "PLAIN") is False


def test_is_nested_overridable_parent_false_for_missing_field() -> None:
    """An unknown field is not nested-overridable."""
    assert is_nested_overridable_parent(_Outer, "DOES_NOT_EXIST") is False


def test_iter_nested_leaf_keys_session_yields_all_leaves() -> None:
    """``SESSION`` enumerates its five leaves with canonical uppercase chains."""
    leaves = dict(iter_nested_leaf_keys(SEPSettings, "SESSION"))
    assert set(leaves) == {
        "SESSION__COOKIE_NAME",
        "SESSION__MAX_AGE",
        "SESSION__SAMESITE",
        "SESSION__SECURE",
        "SESSION__PATH",
    }
    for key, chain in leaves.items():
        assert "__".join(chain) == key
        assert canonical_override_key(SEPSettings, key) == key


def test_iter_nested_leaf_keys_security_headers_descends_two_levels() -> None:
    """``SECURITY_HEADERS`` enumerates lowercase-child leaves, descending two levels."""
    leaves = dict(iter_nested_leaf_keys(TasksSettings, "SECURITY_HEADERS"))
    assert set(leaves) == {
        "SECURITY_HEADERS__x_frame_options_deny",
        "SECURITY_HEADERS__x_content_type_options_nosniff",
        "SECURITY_HEADERS__referrer_policy_same_origin",
        "SECURITY_HEADERS__content_security_policy_strict",
        "SECURITY_HEADERS__content_security_policy_exclude_paths",
        "SECURITY_HEADERS__strict_transport_security__max_age",
        "SECURITY_HEADERS__strict_transport_security__include_sub_domains",
        "SECURITY_HEADERS__strict_transport_security__preload",
        "SECURITY_HEADERS__permissions_policy__allow_self",
        "SECURITY_HEADERS__permissions_policy__allow_all",
    }
    for key, chain in leaves.items():
        assert "__".join(chain) == key
        assert canonical_override_key(TasksSettings, key) == key


def test_iter_nested_leaf_keys_scalar_field_yields_nothing() -> None:
    """A scalar (non-submodel) field enumerates to no leaves."""
    assert list(iter_nested_leaf_keys(_Outer, "PLAIN")) == []


def test_iter_nested_leaf_keys_unknown_parent_yields_nothing() -> None:
    """An unknown parent field name enumerates to no leaves."""
    assert list(iter_nested_leaf_keys(_Outer, "DOES_NOT_EXIST")) == []


def test_iter_nested_leaf_keys_descends_synthetic_submodel() -> None:
    """Recursion descends through a nested submodel to its grandchild leaf."""
    leaves = dict(iter_nested_leaf_keys(_Outer, "NESTED"))
    assert set(leaves) == {
        "NESTED__BARE",
        "NESTED__LOCKED",
        "NESTED__LOCKED_SUB__VALUE",
    }
    assert leaves["NESTED__LOCKED_SUB__VALUE"] == ("NESTED", "LOCKED_SUB", "VALUE")


def test_resolve_nested_field_metadata_reflects_chain_not_overridable() -> None:
    """A leaf under a ``not_overridable_field`` intermediate reports NOT_OVERRIDABLE.

    The enumerated-leaf reload classification must match the chain check that
    gates PATCH/DELETE, so a leaf is never advertised as editable when an
    intermediate in its chain is locked.
    """
    open_leaf = resolve_nested_field_metadata(_Outer, "NESTED__BARE")
    locked_leaf = resolve_nested_field_metadata(_Outer, "NESTED__LOCKED_SUB__VALUE")
    assert open_leaf is not None
    assert locked_leaf is not None
    assert open_leaf.reload is ReloadClassification.HOT
    assert locked_leaf.reload is ReloadClassification.NOT_OVERRIDABLE


class _SecretLeafModel(BaseModel):
    """Represent a submodel with a required ``SecretStr`` leaf for resolver tests."""

    TOKEN: SecretStr = SecretStr("s3cr3t")
    LABEL: str = "public"


class _SecretLeafParent(BaseModel):
    """Represent a parent declaring a nested-overridable group over a secret submodel."""

    GROUP: _SecretLeafModel = nested_overridable_field(_SecretLeafModel())


class _OptionalInner(BaseModel):
    """Represent an inner model reached through an optional intermediate."""

    DEEP: int = 1


class _OptionalIntermediate(BaseModel):
    """Represent a submodel whose intermediate child defaults to ``None``."""

    INNER: _OptionalInner | None = None


class _OptionalIntermediateParent(BaseModel):
    """Represent the top-level parent for optional-intermediate resolver tests."""

    NESTED: _OptionalIntermediate = nested_overridable_field(_OptionalIntermediate())


def test_resolve_nested_value_missing_mapping_segment_returns_sentinel() -> None:
    """Return :data:`NESTED_VALUE_MISSING` for a dict snapshot missing a segment."""
    proxy = OverridableSettingsProxy(
        _SecretLeafParent, setting_class=SettingClassEnum.SEP_SETTINGS
    )
    proxy._set_snapshot({"GROUP": {"LABEL": "visible"}})
    _, value = resolve_nested_value(
        settings_cls=_SecretLeafParent, proxy=proxy, key="GROUP__TOKEN"
    )
    assert value is NESTED_VALUE_MISSING


def test_resolve_nested_value_optional_none_intermediate_returns_none() -> None:
    """Collapse the leaf to ``None`` for a present-``None`` optional intermediate."""
    proxy = OverridableSettingsProxy(
        _OptionalIntermediateParent, setting_class=SettingClassEnum.SEP_SETTINGS
    )
    _, value = resolve_nested_value(
        settings_cls=_OptionalIntermediateParent,
        proxy=proxy,
        key="NESTED__INNER__DEEP",
    )
    assert value is None
    assert value is not NESTED_VALUE_MISSING


def test_resolve_nested_value_present_none_secret_leaf_returns_none() -> None:
    """Distinguish a present-``None`` secret leaf from a missing segment."""
    proxy = OverridableSettingsProxy(
        _SecretLeafParent, setting_class=SettingClassEnum.SEP_SETTINGS
    )
    proxy._set_snapshot(
        {"GROUP": _SecretLeafModel.model_construct(TOKEN=None, LABEL="public")}
    )
    _, value = resolve_nested_value(
        settings_cls=_SecretLeafParent, proxy=proxy, key="GROUP__TOKEN"
    )
    assert value is None
    assert value is not NESTED_VALUE_MISSING


def test_settings_response_serializes_missing_mapping_segment_as_null() -> None:
    """LIST projection maps a missing nested segment to JSON ``null``."""
    proxy = OverridableSettingsProxy(
        _SecretLeafParent, setting_class=SettingClassEnum.SEP_SETTINGS
    )
    proxy._set_snapshot({"GROUP": {"LABEL": "visible"}})
    leaf_meta = resolve_nested_field_metadata(_SecretLeafParent, "GROUP__TOKEN")
    assert leaf_meta is not None
    response = _settings_response_from_field(
        setting_class=SettingClassEnum.SEP_SETTINGS,
        settings_cls=_SecretLeafParent,
        proxy=proxy,
        field_meta=leaf_meta,
        has_override=False,
    )
    assert response.value is None
    assert response.is_secret is True


def test_settings_response_serializes_present_none_secret_leaf_as_null() -> None:
    """LIST projection renders an unresolved secret leaf as JSON ``null``."""
    proxy = OverridableSettingsProxy(
        _SecretLeafParent, setting_class=SettingClassEnum.SEP_SETTINGS
    )
    proxy._set_snapshot(
        {"GROUP": _SecretLeafModel.model_construct(TOKEN=None, LABEL="public")}
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
    assert response.value is None
    assert response.is_secret is True


class _OverlayLeafOwner(BaseModel):
    """Define a submodel whose overlay promotes one bare leaf; a sibling stays unmarked.

    Mirrors the SEP-1511 ``NomadExecutor`` case: the overlay lives on the class
    that *owns* the resolved leaf, not on the top-level settings class.
    """

    INHERITED_MARKERS: ClassVar[dict[str, dict[str, object]]] = {
        "MARKED": {"reload": ReloadClassification.HOT, "advanced": True},
    }
    MARKED: int = 1
    PLAIN: int = 2


class _OverlayParent(BaseModel):
    """Top-level model nesting an overlay-bearing submodel; carries no overlay itself."""

    CHILD: _OverlayLeafOwner = nested_overridable_field(_OverlayLeafOwner())


def test_nested_leaf_uses_owning_class_overlay() -> None:
    """Assert a nested leaf is classified against its owning submodel's overlay."""
    assert chain_has_advanced(_OverlayParent, "CHILD__MARKED") is True
    meta = resolve_nested_field_metadata(_OverlayParent, "CHILD__MARKED")
    assert meta is not None
    assert meta.is_advanced is True
    assert meta.reload is ReloadClassification.HOT


def test_nested_sibling_without_overlay_entry_stays_unmarked() -> None:
    """Assert a sibling leaf with no overlay entry is not promoted (opt-in per field)."""
    assert chain_has_advanced(_OverlayParent, "CHILD__PLAIN") is False
    meta = resolve_nested_field_metadata(_OverlayParent, "CHILD__PLAIN")
    assert meta is not None
    assert meta.is_advanced is False
