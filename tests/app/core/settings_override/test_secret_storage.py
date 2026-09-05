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

"""Define tests for the schema-driven secret-leaf walker.

Which leaves are secret is derived from the settings annotation, never from the
stored JSON, so every case here pairs a settings class and an override key with
the JSON shape that key actually persists.
"""

from collections import defaultdict, OrderedDict
from collections.abc import MutableMapping
from typing import Any

import pytest
from cryptography.fernet import Fernet
from pydantic import BaseModel, SecretStr

from app.core.alerts.config import AlertSettings
from app.core.config import BaseYamlSettings, Settings
from app.core.encryption import decrypt, DecryptionError, encrypt, is_encrypted
from app.core.settings_override.secret_storage import (
    _positional_args,
    _transform_secret_leaves,
    decrypt_secret_leaves,
    encrypt_secret_leaves,
    reencrypt_secret_leaves,
)
from app.sep.config import SEPSettings

PMM_KEY = "PMM"
PMM_NESTED_KEY = "PMM__API_KEY"
PROVIDERS_KEY = "PROVIDERS"
DELIVERY_INPUTS_KEY = "DIAGNOSTICS_DELIVERY_INPUTS"

#: A plaintext credential ``is_encrypted`` misreads as a Fernet token: 100
#: base64url characters decoding to a leading ``0x80``. Every test using it
#: asserts that misreading first, so the literal cannot go stale unnoticed.
FERNET_SHAPED_PLAINTEXT = (
    "gBrle-7Zwz135751BZtx8xwcbtxmKhU1YI8Owrth49_"
    "fdSL8gSiBYnsom2i4yH0ezlpcaER2qVlAGyLicNyLdNIrX7yiZdZ7uJIX"
)


def foreign_token(value: str = "written under another key") -> str:
    """Return ciphertext minted with a key the configured one cannot decrypt.

    :param value: The plaintext to encrypt with the foreign key.
    :return: The foreign Fernet token.
    """
    return Fernet(Fernet.generate_key()).encrypt(value.encode()).decode("ascii")


def pmm_payload(api_key: object = "pmm-secret") -> dict[str, object]:
    """Return the stored JSON shape of a whole-object ``PMM`` override.

    :param api_key: The value to place at ``$.api_key``.
    :return: The override row's stored value.
    """
    return {
        "endpoint": "https://pmm.example.com",
        "api_key": api_key,
        "verify_ssl": True,
    }


def pagerduty_payload(
    routing_key_field: str = "routing_key",
) -> list[dict[str, object]]:
    """Return the stored JSON shape of a ``PROVIDERS`` override with one PagerDuty entry.

    :param routing_key_field: The spelling the client used for the secret field.
    :return: The override row's stored value.
    """
    return [
        {
            "PROVIDER": "PAGERDUTY",
            "api_endpoint": "https://events.pagerduty.com/v2/",
            routing_key_field: "pd-routing-secret",
        }
    ]


def delivery_inputs_payload() -> dict[str, object]:
    """Return the stored JSON shape of a ``DIAGNOSTICS_DELIVERY_INPUTS`` override.

    :return: The override row's stored value.
    """
    return {
        "endpoint": "https://intake.example.com",
        "secrets": {"token": "intake-token", "api_key": "intake-api-key"},
    }


class TestEncryptSecretLeaves:
    """Cover :func:`encrypt_secret_leaves` over every secret-bearing override shape."""

    def test_encrypts_top_level_model_secret_leaf(self) -> None:
        """Encrypt ``$.api_key`` of a whole-object ``PMM`` override, leaving siblings alone."""
        stored = encrypt_secret_leaves(Settings, PMM_KEY, pmm_payload())

        assert is_encrypted(stored["api_key"])
        assert decrypt(stored["api_key"]) == "pmm-secret"
        assert stored["endpoint"] == "https://pmm.example.com"
        assert stored["verify_ssl"] is True

    def test_encrypts_bare_nested_leaf(self) -> None:
        """Encrypt the whole value of a nested ``PMM__API_KEY`` row."""
        stored = encrypt_secret_leaves(Settings, PMM_NESTED_KEY, "pmm-secret")

        assert is_encrypted(stored)
        assert decrypt(stored) == "pmm-secret"

    def test_encrypts_polymorphic_provider_secret(self) -> None:
        """Encrypt ``$[i].routing_key`` on a concrete provider subclass, keeping siblings."""
        stored = encrypt_secret_leaves(
            AlertSettings, PROVIDERS_KEY, pagerduty_payload()
        )

        assert is_encrypted(stored[0]["routing_key"])
        assert decrypt(stored[0]["routing_key"]) == "pd-routing-secret"
        assert stored[0]["PROVIDER"] == "PAGERDUTY"
        assert stored[0]["api_endpoint"] == "https://events.pagerduty.com/v2/"

    def test_encrypts_polymorphic_provider_secret_uppercase_key(self) -> None:
        """Match the provider's field name case-folded, as the client may store it uppercase."""
        stored = encrypt_secret_leaves(
            AlertSettings, PROVIDERS_KEY, pagerduty_payload("ROUTING_KEY")
        )

        assert is_encrypted(stored[0]["ROUTING_KEY"])
        assert decrypt(stored[0]["ROUTING_KEY"]) == "pd-routing-secret"

    def test_encrypts_secret_valued_dict(self) -> None:
        """Encrypt every value of a ``dict[str, SecretStr]`` leaf, never its keys."""
        stored = encrypt_secret_leaves(
            SEPSettings, DELIVERY_INPUTS_KEY, delivery_inputs_payload()
        )

        assert sorted(stored["secrets"]) == ["api_key", "token"]
        assert is_encrypted(stored["secrets"]["token"])
        assert decrypt(stored["secrets"]["token"]) == "intake-token"
        assert decrypt(stored["secrets"]["api_key"]) == "intake-api-key"
        assert stored["endpoint"] == "https://intake.example.com"

    def test_non_secret_field_returned_by_identity(self) -> None:
        """Return a value whose annotation reaches no secret without rebuilding it.

        Asserted by identity rather than equality: a container the walker
        descended into would compare equal while being a different object, so
        only ``is`` proves the annotation was pruned before any descent.
        """
        payload = {"version": 1, "handlers": {"console": {"level": "DEBUG"}}}

        assert encrypt_secret_leaves(Settings, "LOGGING_CONFIG", payload) is payload

    @pytest.mark.parametrize("api_key", [None, 7, ["not-a-string"]])
    def test_non_str_leaves_pass_through(self, api_key: object) -> None:
        """Leave a non-``str`` value at a secret position untouched rather than encrypting it."""
        stored = encrypt_secret_leaves(Settings, PMM_KEY, pmm_payload(api_key))

        assert stored["api_key"] == api_key

    def test_empty_string_secret_is_encrypted(self) -> None:
        """Encrypt an empty secret, which Fernet pads to a full block and round-trips."""
        stored = encrypt_secret_leaves(Settings, PMM_KEY, pmm_payload(""))

        assert is_encrypted(stored["api_key"])
        assert decrypt(stored["api_key"]) == ""

    def test_encrypts_a_secret_that_is_itself_shaped_like_ciphertext(self) -> None:
        """Encrypt a credential ``is_encrypted`` would misread as already-encrypted.

        ``is_encrypted`` is purely structural, so roughly one in 256 base64url
        secrets of 100 characters or more decodes to a leading ``0x80`` and
        passes it. On the write path the value is always plaintext, so consulting
        that predicate there would store such a credential in the clear, which is
        the exact exposure this module exists to remove, and the subsequent
        read would fail to decrypt it and drop the override silently.
        """
        secret = FERNET_SHAPED_PLAINTEXT
        assert is_encrypted(secret), "the fixture must exercise the misreading"

        stored = encrypt_secret_leaves(Settings, PMM_NESTED_KEY, secret)

        assert stored != secret
        assert decrypt(stored) == secret

    def test_input_is_not_mutated(self) -> None:
        """Return new containers so the caller's payload keeps its plaintext."""
        payload = pmm_payload()

        encrypt_secret_leaves(Settings, PMM_KEY, payload)

        assert payload["api_key"] == "pmm-secret"

    def test_unresolvable_key_returns_value_unchanged(self) -> None:
        """Return the value untouched for a key that resolves to no field."""
        payload = pmm_payload()

        assert encrypt_secret_leaves(Settings, "NO_SUCH_FIELD", payload) == payload


class TestReencryptSecretLeaves:
    """Cover the idempotent variant the re-encryption migrations use."""

    def test_encrypts_a_plaintext_leaf(self) -> None:
        """Encrypt a leaf that is not yet ciphertext, like the write path does."""
        stored = reencrypt_secret_leaves(Settings, PMM_KEY, pmm_payload())

        assert is_encrypted(stored["api_key"])
        assert decrypt(stored["api_key"]) == "pmm-secret"

    def test_already_encrypted_leaf_not_re_encrypted(self) -> None:
        """Leave an already-encrypted leaf byte-identical instead of double-encrypting it."""
        once = reencrypt_secret_leaves(Settings, PMM_KEY, pmm_payload())

        assert reencrypt_secret_leaves(Settings, PMM_KEY, once) == once

    def test_foreign_key_ciphertext_not_re_encrypted(self) -> None:
        """Leave ciphertext this key cannot decrypt alone, since re-encrypting destroys it."""
        token = foreign_token()

        stored = reencrypt_secret_leaves(Settings, PMM_KEY, pmm_payload(token))

        assert stored["api_key"] == token

    def test_a_plaintext_secret_shaped_like_ciphertext_is_skipped(self) -> None:
        """Pin the accepted limitation: a Fernet-shaped plaintext row stays in the clear.

        Telling this apart from ciphertext written under another key would take a
        decrypt attempt, and guessing wrong on the second destroys the only copy
        of its plaintext. The write path has no such ambiguity, so only rows
        predating the migration can be affected.
        """
        stored = reencrypt_secret_leaves(
            Settings, PMM_NESTED_KEY, FERNET_SHAPED_PLAINTEXT
        )

        assert stored == FERNET_SHAPED_PLAINTEXT


class TestDecryptSecretLeaves:
    """Cover :func:`decrypt_secret_leaves` over the read path's inputs."""

    def test_decrypts_top_level_model_secret_leaf(self) -> None:
        """Restore the plaintext of an encrypted ``$.api_key``."""
        stored = encrypt_secret_leaves(Settings, PMM_KEY, pmm_payload())

        assert decrypt_secret_leaves(Settings, PMM_KEY, stored) == pmm_payload()

    def test_decrypt_passes_legacy_plaintext_through(self) -> None:
        """Return a not-yet-encrypted leaf unchanged so pre-migration rows keep working."""
        payload = pmm_payload()

        assert decrypt_secret_leaves(Settings, PMM_KEY, payload) == payload

    def test_decrypt_raises_on_foreign_key_ciphertext(self) -> None:
        """Raise :class:`DecryptionError` for ciphertext minted under another key."""
        payload = pmm_payload(foreign_token())

        with pytest.raises(DecryptionError):
            decrypt_secret_leaves(Settings, PMM_KEY, payload)

    @pytest.mark.parametrize(
        ("settings_cls", "key", "payload"),
        [
            (Settings, PMM_KEY, pmm_payload()),
            (Settings, PMM_NESTED_KEY, "pmm-secret"),
            (AlertSettings, PROVIDERS_KEY, pagerduty_payload()),
            (SEPSettings, DELIVERY_INPUTS_KEY, delivery_inputs_payload()),
        ],
        ids=["pmm-object", "pmm-nested-leaf", "providers-array", "delivery-inputs"],
    )
    def test_round_trip(
        self, settings_cls: type[BaseYamlSettings], key: str, payload: object
    ) -> None:
        """Restore every secret-bearing override shape to its original plaintext."""
        stored = encrypt_secret_leaves(settings_cls, key, payload)

        assert decrypt_secret_leaves(settings_cls, key, stored) == payload

    def test_ciphertext_differs_from_plaintext_for_every_shape(self) -> None:
        """Confirm the round trip above is not vacuous: the stored value really changed."""
        stored = encrypt_secret_leaves(
            AlertSettings, PROVIDERS_KEY, pagerduty_payload()
        )

        assert stored[0]["routing_key"] != "pd-routing-secret"
        assert stored != pagerduty_payload()

    def test_mixed_provider_array_leaves_non_secret_entries_alone(self) -> None:
        """Transform only the entries whose annotation carries a secret field."""
        payload = [*pagerduty_payload(), {"PROVIDER": "PAGERDUTY", "api_endpoint": "x"}]

        stored = encrypt_secret_leaves(AlertSettings, PROVIDERS_KEY, payload)

        assert is_encrypted(stored[0]["routing_key"])
        assert stored[1] == {"PROVIDER": "PAGERDUTY", "api_endpoint": "x"}

    def test_unmatched_json_key_is_left_alone(self) -> None:
        """Leave a stored key that matches no model field untouched."""
        payload = {**pmm_payload(), "retired_field": "plain"}

        stored = encrypt_secret_leaves(Settings, PMM_KEY, payload)

        assert stored["retired_field"] == "plain"
        assert is_encrypted(stored["api_key"])


class _SecretHolder(BaseModel):
    """Carry one secret-typed field for the annotation-shape cases below.

    :param token: The secret leaf a walker must reach.
    """

    token: SecretStr


class TestAnnotationShapes:
    """Cover container annotations no settings field declares today.

    Each shape is one the walker's own type-argument handling admits, so a gap
    here is a silent plaintext store rather than an error. Driven through
    ``_transform_secret_leaves`` directly because no settings class declares
    them, which is exactly why the codebase cannot exercise them for us.
    """

    @staticmethod
    def _encrypt(annotation: Any, value: Any) -> Any:
        """Apply the write path's transform against ``annotation``.

        :param annotation: The annotation of the JSON position ``value`` occupies.
        :param value: The stored value at that position.
        :return: The transformed value.
        """
        return _transform_secret_leaves(annotation, value, encrypt)

    @pytest.mark.parametrize(
        "annotation",
        [
            dict[str, SecretStr],
            defaultdict[str, SecretStr],
            OrderedDict[str, SecretStr],
            MutableMapping[str, SecretStr],
        ],
        ids=["dict", "defaultdict", "OrderedDict", "MutableMapping"],
    )
    def test_every_mapping_flavour_reaches_its_secret_values(
        self, annotation: Any
    ) -> None:
        """Descend into any mapping type, not just the ``dict`` spelling.

        ``defaultdict`` and ``OrderedDict`` are both live override-field
        annotations, so a membership test against a fixed set of origins would
        leave a future secret-valued one in the clear.
        """
        stored = self._encrypt(annotation, {"a": "s1", "b": "s2"})

        assert decrypt(stored["a"]) == "s1"
        assert decrypt(stored["b"]) == "s2"

    @pytest.mark.parametrize(
        "annotation",
        [dict[str, str] | _SecretHolder, _SecretHolder | dict[str, str]],
        ids=["mapping-first", "model-first"],
    )
    def test_a_union_of_mapping_and_model_still_reaches_the_model_secret(
        self, annotation: Any
    ) -> None:
        """Fall through to the model branch when the mapping candidate holds no secret.

        Resolving the union to the ``dict``'s plain ``str`` values would take the
        mapping branch and never look inside the model, storing its credential in
        the clear whichever way the union is spelled.
        """
        stored = self._encrypt(annotation, {"token": "s1"})

        assert decrypt(stored["token"]) == "s1"

    def test_a_heterogeneous_tuple_reaches_the_secret_at_a_later_index(self) -> None:
        """Resolve a fixed-length tuple per index, not from its first argument alone."""
        stored = self._encrypt(tuple[str, SecretStr], ["plain", "s1"])

        assert stored[0] == "plain"
        assert decrypt(stored[1]) == "s1"

    def test_a_variadic_tuple_annotates_every_item_alike(self) -> None:
        """Apply the single element annotation to every item of a ``tuple[X, ...]``."""
        stored = self._encrypt(tuple[SecretStr, ...], ["s1", "s2"])

        assert decrypt(stored[0]) == "s1"
        assert decrypt(stored[1]) == "s2"

    def test_a_set_annotation_over_a_json_array_reaches_its_items(self) -> None:
        """Descend a ``set``-annotated field, which JSON stores as an array.

        This is the shape ``AlertSettings.PROVIDERS`` declares, so the collection
        predicate has to admit origins whose values never arrive as that type.
        """
        stored = self._encrypt(set[SecretStr], ["s1", "s2"])

        assert [decrypt(item) for item in stored] == ["s1", "s2"]

    def test_union_members_reach_the_tie_break_in_declaration_order(self) -> None:
        """Preserve a union's declared order through the positional flattening.

        ``_first_secret_bearing`` resolves a contested position by taking the
        first candidate that reaches a secret, so the order this returns *is*
        the tie-break rule. A LIFO traversal that forgets to reverse silently
        inverts it, and no live annotation has two secret-bearing candidates
        today to fail on it.
        """
        assert _positional_args(dict[str, str] | list[int] | SecretStr) == [
            dict[str, str],
            list[int],
            SecretStr,
        ]
