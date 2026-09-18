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

"""Test masked-secret and credential-URL preservation on the PATCH write path."""

import typing

from pydantic import BaseModel, SecretStr
from pydantic.fields import FieldInfo

from app.core.settings_override.registry import (
    preserve_patch_secret_value,
    preserve_secrets_in_model_payload,
    SECRET_STR_MASK,
)


class _SecretLeaf(BaseModel):
    """Hold one scalar secret beside a stable public identifier."""

    api_key: SecretStr
    label: str = "public"


class _OptionalValueSecretDict(BaseModel):
    """Declare a mapping whose value type unions a secret with ``None``."""

    tokens: dict[str, SecretStr | None] = {}


class _OptionalElementSecretList(BaseModel):
    """Declare a collection whose element type unions a secret with ``None``."""

    tokens: list[SecretStr | None] = []


class _OptionalElementModelList(BaseModel):
    """Declare a collection whose element type unions a model with ``None``."""

    items: list[_SecretLeaf | None] = []


class _ModelList(BaseModel):
    """Declare a homogeneous collection of secret-bearing models."""

    items: list[_SecretLeaf] = []


class _PlainCollections(BaseModel):
    """Declare secret-free mapping and collection fields with union members."""

    labels: dict[str, str | None] = {}
    names: list[str | None] = []


class TestSecretValuedDictPayloads:
    """Cover ``dict``-shaped secret payloads, including malformed annotations."""

    def test_union_valued_mapping_restores_masked_entry(self) -> None:
        """Restore a masked entry whose annotated value type unions with ``None``."""
        current = _OptionalValueSecretDict(tokens={"first": SecretStr("stored")})

        preserved = preserve_secrets_in_model_payload(
            _OptionalValueSecretDict, current, {"tokens": {"first": SECRET_STR_MASK}}
        )

        assert preserved == {"tokens": {"first": "stored"}}

    def test_absent_stored_entry_keeps_the_mask(self) -> None:
        """Leave the mask in place when no stored secret backs the submitted key.

        Restoring from a missing entry would be a guess; keeping the literal is
        what lets the validation layer reject the payload instead.
        """
        current = _OptionalValueSecretDict(tokens={"first": SecretStr("stored")})

        preserved = preserve_secrets_in_model_payload(
            _OptionalValueSecretDict, current, {"tokens": {"second": SECRET_STR_MASK}}
        )

        assert preserved == {"tokens": {"second": SECRET_STR_MASK}}

    def test_secret_free_union_valued_mapping_is_left_alone(self) -> None:
        """Skip restoration for a mapping whose union value type holds no secret."""
        preserved = preserve_patch_secret_value(
            _PlainCollections.model_fields["labels"],
            {"first": "stored"},
            {"first": SECRET_STR_MASK},
        )

        assert preserved == {"first": SECRET_STR_MASK}

    def test_mapping_annotation_of_unexpected_arity_is_not_a_secret_mapping(
        self,
    ) -> None:
        """Skip restoration for a mapping annotation that is not a key/value pair."""
        field_info = FieldInfo.from_annotation(dict[str, SecretStr, str])  # type: ignore[misc]

        preserved = preserve_patch_secret_value(
            field_info, {"first": SecretStr("stored")}, {"first": SECRET_STR_MASK}
        )

        assert preserved == {"first": SECRET_STR_MASK}


class TestSecretValuedSequencePayloads:
    """Cover collection payloads whose elements are secrets."""

    def test_union_element_collection_restores_masked_element(self) -> None:
        """Restore a masked element whose annotated type unions with ``None``."""
        current = _OptionalElementSecretList(
            tokens=[SecretStr("first"), SecretStr("second")]
        )

        preserved = preserve_secrets_in_model_payload(
            _OptionalElementSecretList,
            current,
            {"tokens": [SECRET_STR_MASK, "replacement"]},
        )

        assert preserved == {"tokens": ["first", "replacement"]}

    def test_unparameterized_collection_annotation_restores_nothing(self) -> None:
        """Skip restoration for a collection annotation with no element type."""
        field_info = FieldInfo.from_annotation(typing.List)  # noqa: UP006

        preserved = preserve_patch_secret_value(field_info, None, [SECRET_STR_MASK])

        assert preserved == [SECRET_STR_MASK]


class TestModelCollectionPairing:
    """Cover which stored collection item a masked incoming item inherits from."""

    def test_union_element_model_collection_restores_masked_leaf(self) -> None:
        """Pair items when the annotated element type unions a model with ``None``."""
        current = _OptionalElementModelList(items=[_SecretLeaf(api_key=SecretStr("k"))])

        preserved = preserve_secrets_in_model_payload(
            _OptionalElementModelList,
            current,
            {"items": [{"api_key": SECRET_STR_MASK, "label": "public"}]},
        )

        assert preserved == {"items": [{"api_key": "k", "label": "public"}]}

    def test_secret_free_union_element_collection_is_left_alone(self) -> None:
        """Skip restoration for a collection whose union element holds no secret."""
        preserved = preserve_patch_secret_value(
            _PlainCollections.model_fields["names"], None, [SECRET_STR_MASK]
        )

        assert preserved == [SECRET_STR_MASK]

    def test_stored_scalar_item_keeps_the_mask(self) -> None:
        """Keep the mask when the paired stored item is neither model nor mapping."""
        preserved = preserve_patch_secret_value(
            _ModelList.model_fields["items"],
            ["scalar"],
            [{"api_key": SECRET_STR_MASK}],
        )

        assert preserved == [{"api_key": SECRET_STR_MASK}]

    def test_stored_mapping_item_restores_masked_keys_shallowly(self) -> None:
        """Restore from a stored fingerprint mapping, keeping unbacked masks intact."""
        field_info = _ModelList.model_fields["items"]
        current = [{"api_key": SecretStr("stored")}]
        incoming = [
            {"api_key": SECRET_STR_MASK, "other": SECRET_STR_MASK, "label": "public"},
        ]

        preserved = preserve_patch_secret_value(field_info, current, incoming)

        assert preserved == [
            {"api_key": "stored", "other": SECRET_STR_MASK, "label": "public"},
        ]

    def test_non_mapping_item_passes_through(self) -> None:
        """Forward a collection element that is not a mapping untouched."""
        field_info = _ModelList.model_fields["items"]
        current = [_SecretLeaf(api_key=SecretStr("stored"))]

        preserved = preserve_patch_secret_value(
            field_info, current, ["not-a-mapping", {"api_key": SECRET_STR_MASK}]
        )

        assert preserved == ["not-a-mapping", {"api_key": "stored"}]

    def test_unmatched_item_keeps_the_mask(self) -> None:
        """Keep the mask when no stored model can be paired with the submitted item.

        The discriminator claims the only stored model, leaving the second item
        with mapping-only candidates it cannot match. Inheriting a secret from
        an arbitrary leftover slot would hand one item another's credential.
        """
        field_info = _ModelList.model_fields["items"]
        current = [
            {"api_key": SecretStr("fingerprint")},
            _SecretLeaf(api_key=SecretStr("model")),
            {"api_key": SecretStr("other-fingerprint")},
        ]
        incoming = [
            {"PROVIDER": "secretleaf", "api_key": SECRET_STR_MASK},
            {"PROVIDER": "nonesuch", "api_key": SECRET_STR_MASK},
        ]

        preserved = preserve_patch_secret_value(field_info, current, incoming)

        assert preserved == [
            {"PROVIDER": "secretleaf", "api_key": "model"},
            {"PROVIDER": "nonesuch", "api_key": SECRET_STR_MASK},
        ]

    def test_non_collection_stored_value_yields_no_pairing(self) -> None:
        """Keep masks when the stored value is not a collection at all."""
        field_info = _ModelList.model_fields["items"]

        preserved = preserve_patch_secret_value(
            field_info, None, [{"api_key": SECRET_STR_MASK}]
        )

        assert preserved == [{"api_key": SECRET_STR_MASK}]


class TestStoredValueReads:
    """Cover reading a stored leaf from a model, a mapping, or nothing."""

    def test_absent_stored_model_keeps_the_mask(self) -> None:
        """Keep the mask when there is no stored model to restore from."""
        preserved = preserve_secrets_in_model_payload(
            _SecretLeaf, None, {"api_key": SECRET_STR_MASK}
        )

        assert preserved == {"api_key": SECRET_STR_MASK}
