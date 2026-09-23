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

"""Tests for credential-bearing URL field types and redaction helpers."""

from typing import Annotated

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.core.settings_override.registry import (
    annotation_contains_secret,
    annotation_is_credential_url,
    SECRET_STR_MASK,
)
from app.core.utils.fields import (
    AuthCredentialSecretStr,
    CREDENTIAL_URL_MASK,
    credential_url_password,
    CREDENTIAL_URL_STR_JSON_SERIALIZER,
    CredentialHttpUrl,
    map_credential_url_password,
    PreservableSecretStr,
    preserve_credential_url_password,
    PRESERVE_CREDENTIALS_CONTEXT,
    redact_credential_url,
    StrCredentialAnyUrl,
    StrCredentialHttpUrl,
    strip_credential_url_userinfo,
)

_CREDENTIAL_URL = "http://nomad-user:nomad-secret@nomad.internal:4646/v1/jobs"
_REDACTED_URL = "http://nomad-user:****@nomad.internal:4646/v1/jobs"
_PLAIN_URL = "http://nomad.internal:4646"
_BROKER_URL = "amqp://celery-user:celery-pass@rabbit:5672/vhost"
_REDACTED_BROKER_URL = "amqp://celery-user:****@rabbit:5672/vhost"


class TestRedactCredentialUrl:
    """Unit tests for :func:`redact_credential_url`."""

    def test_masks_password_and_preserves_other_components(self) -> None:
        """Only the password segment is replaced; the rest of the URL stays visible."""
        assert redact_credential_url(_CREDENTIAL_URL) == _REDACTED_URL

    def test_leaves_url_without_credentials_unchanged(self) -> None:
        """Return URLs with no embedded password unchanged."""
        assert redact_credential_url(_PLAIN_URL) == _PLAIN_URL

    def test_leaves_username_only_url_unchanged(self) -> None:
        """Return a username-only URL unchanged when no password is present."""
        url = "http://nomad-user@nomad.internal:4646"
        assert redact_credential_url(url) == url

    def test_supports_non_http_schemes(self) -> None:
        """Redact broker-style URLs with arbitrary schemes the same way."""
        assert redact_credential_url(_BROKER_URL) == _REDACTED_BROKER_URL

    def test_custom_mask(self) -> None:
        """Allow callers to override the password mask literal."""
        assert (
            redact_credential_url(_CREDENTIAL_URL, mask="REDACTED")
            == "http://nomad-user:REDACTED@nomad.internal:4646/v1/jobs"
        )

    def test_preserves_ipv6_brackets_in_host(self) -> None:
        """Preserve IPv6 bracket notation when redacting embedded credentials."""
        url = "http://user:secret@[::1]:8080/api"
        assert redact_credential_url(url) == "http://user:****@[::1]:8080/api"


class TestPreserveCredentialUrlPassword:
    """Write-back protection for unchanged redacted URL PATCH payloads."""

    def test_preserves_password_when_only_mask_differs(self) -> None:
        """Restore the stored credential when only the password mask differs."""
        current = "http://nomad-user:nomad-secret@nomad.internal:4646/v1/jobs"
        incoming = "http://nomad-user:****@nomad.internal:4646/v1/jobs"
        assert preserve_credential_url_password(current, incoming) == current

    def test_returns_incoming_when_password_is_new(self) -> None:
        """Accept a genuinely new password as-is."""
        current = "http://nomad-user:old-secret@nomad.internal:4646"
        incoming = "http://nomad-user:new-secret@nomad.internal:4646"
        assert preserve_credential_url_password(current, incoming) == incoming

    def test_returns_incoming_when_host_differs(self) -> None:
        """Treat a redacted URL with a changed host as a real change."""
        current = "http://nomad-user:secret@nomad-a.internal:4646"
        incoming = "http://nomad-user:****@nomad-b.internal:4646"
        assert preserve_credential_url_password(current, incoming) == incoming

    def test_preserves_password_when_paths_differ_only_by_trailing_slash(self) -> None:
        """Normalize HttpUrl trailing-slash differences on redacted resubmit."""
        current = "http://nomad-user:nomad-secret@nomad.internal:4646/"
        incoming = "http://nomad-user:****@nomad.internal:4646"
        assert preserve_credential_url_password(current, incoming) == current

    def test_preserves_password_for_ipv6_endpoint(self) -> None:
        """Restore the stored credential for IPv6 endpoints without raising."""
        current = "http://user:secret@[::1]:8080"
        incoming = "http://user:****@[::1]:8080"
        assert preserve_credential_url_password(current, incoming) == current


class TestCredentialHttpUrl:
    """JSON vs python serialization for :data:`CredentialHttpUrl`."""

    @pytest.fixture
    def adapter(self) -> TypeAdapter[CredentialHttpUrl]:
        """Return a type adapter for the annotated HTTP URL type."""
        return TypeAdapter(CredentialHttpUrl)

    def test_json_dump_redacts_password(
        self, adapter: TypeAdapter[CredentialHttpUrl]
    ) -> None:
        """Mask the password in JSON-mode dumps for API responses."""
        value = adapter.validate_python(_CREDENTIAL_URL)
        assert adapter.dump_python(value, mode="json") == _REDACTED_URL

    def test_python_dump_retains_password(
        self, adapter: TypeAdapter[CredentialHttpUrl]
    ) -> None:
        """Keep the real credential in python-mode dumps for live request use."""
        value = adapter.validate_python(_CREDENTIAL_URL)
        dumped = adapter.dump_python(value, mode="python")
        assert "nomad-secret" in str(dumped)

    def test_preserve_context_skips_redaction_on_json_dump(
        self, adapter: TypeAdapter[CredentialHttpUrl]
    ) -> None:
        """Skip redaction on JSON dump when preserve_credentials context is set."""
        value = adapter.validate_python(_CREDENTIAL_URL)
        dumped = adapter.dump_python(
            value, mode="json", context=PRESERVE_CREDENTIALS_CONTEXT
        )
        assert "nomad-secret" in dumped

    def test_in_memory_value_retains_password(self) -> None:
        """Leave validated model attributes unchanged after serialization."""

        class _Model(BaseModel):
            endpoint: CredentialHttpUrl

        model = _Model.model_validate({"endpoint": _CREDENTIAL_URL})
        assert "nomad-secret" in str(model.endpoint)

    def test_accepts_passwordless_url(
        self, adapter: TypeAdapter[CredentialHttpUrl]
    ) -> None:
        """Accept a URL with no embedded password."""
        assert str(adapter.validate_python(_PLAIN_URL)).rstrip("/") == _PLAIN_URL

    def test_rejects_redacted_mask_and_names_field(self) -> None:
        """Reject the redaction mask and name the field in the error."""

        class _Model(BaseModel):
            endpoint: CredentialHttpUrl

        with pytest.raises(ValidationError, match="endpoint") as exc_info:
            _Model.model_validate({"endpoint": _REDACTED_URL})
        assert "cannot be stored" in str(exc_info.value)


class TestStrCredentialHttpUrl:
    """Serialization behaviour for :data:`StrCredentialHttpUrl`."""

    def test_json_dump_redacts_and_strips_trailing_slash(self) -> None:
        """Normalize string HTTP URLs and redact them on JSON dump."""

        class _Model(BaseModel):
            endpoint: StrCredentialHttpUrl

        model = _Model(endpoint="http://user:secret@host:4646/")
        assert model.model_dump(mode="json") == {
            "endpoint": "http://user:****@host:4646"
        }
        assert model.endpoint == "http://user:secret@host:4646"

    def test_accepts_passwordless_url(self) -> None:
        """Accept a string HTTP URL with no embedded password."""

        class _Model(BaseModel):
            endpoint: StrCredentialHttpUrl

        model = _Model(endpoint=_PLAIN_URL)
        assert model.endpoint == _PLAIN_URL

    def test_rejects_redacted_mask_and_names_field(self) -> None:
        """Reject the redaction mask and name the field in the error."""

        class _Model(BaseModel):
            endpoint: StrCredentialHttpUrl

        with pytest.raises(ValidationError, match="endpoint") as exc_info:
            _Model(endpoint="http://user:****@host:4646")
        assert "cannot be stored" in str(exc_info.value)


class TestStrCredentialAnyUrl:
    """Serialization behaviour for :data:`StrCredentialAnyUrl`."""

    def test_json_dump_redacts_broker_url(self) -> None:
        """Redact any-scheme credential URLs on JSON dump."""

        class _Model(BaseModel):
            broker_url: StrCredentialAnyUrl

        model = _Model(broker_url=_BROKER_URL)
        assert model.model_dump(mode="json") == {"broker_url": _REDACTED_BROKER_URL}
        assert model.broker_url == _BROKER_URL

    def test_mask_constant_matches_ticket_example(self) -> None:
        """Match the default redaction mask format."""
        assert CREDENTIAL_URL_MASK == "****"

    def test_accepts_passwordless_url(self) -> None:
        """Accept an any-scheme URL with no embedded password."""

        class _Model(BaseModel):
            broker_url: StrCredentialAnyUrl

        url = "amqp://rabbit:5672/vhost"
        model = _Model(broker_url=url)
        assert model.broker_url == url

    def test_rejects_redacted_mask_and_names_field(self) -> None:
        """Reject the redaction mask and name the field in the error."""

        class _Model(BaseModel):
            broker_url: StrCredentialAnyUrl

        with pytest.raises(ValidationError, match="broker_url") as exc_info:
            _Model(broker_url=_REDACTED_BROKER_URL)
        assert "cannot be stored" in str(exc_info.value)


class TestStripCredentialUrlUserinfo:
    """Cover :func:`strip_credential_url_userinfo` over every userinfo shape."""

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            (_CREDENTIAL_URL, "http://nomad.internal:4646/v1/jobs"),
            ("http://nomad-user@nomad.internal:4646/v1/jobs", _PLAIN_URL + "/v1/jobs"),
            (_PLAIN_URL, _PLAIN_URL),
            ("https://admin:admin@pmm-server/nomad", "https://pmm-server/nomad"),
            ("http://user:p@ss@[::1]:4646/v1", "http://[::1]:4646/v1"),
            (
                "http://@nomad.internal:4646/v1/jobs",
                "http://nomad.internal:4646/v1/jobs",
            ),
            (
                "http://:@nomad.internal:4646/v1/jobs",
                "http://nomad.internal:4646/v1/jobs",
            ),
        ],
    )
    def test_removes_userinfo_and_preserves_the_rest(
        self, url: str, expected: str
    ) -> None:
        """Drop the userinfo segment while leaving every other component intact."""
        assert strip_credential_url_userinfo(url) == expected

    def test_keeps_the_query_and_fragment(self) -> None:
        """Preserve query and fragment components alongside the stripped host."""
        stripped = strip_credential_url_userinfo(
            "http://u:p@host:4646/v1/jobs?region=eu#frag"
        )
        assert stripped == "http://host:4646/v1/jobs?region=eu#frag"


class TestCredentialUrlPassword:
    """Cover :func:`credential_url_password` over every userinfo shape."""

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            (_CREDENTIAL_URL, "nomad-secret"),
            (_PLAIN_URL, None),
            ("http://nomad-user@nomad.internal:4646", None),
            ("http://nomad-user:@nomad.internal:4646", None),
            ("http://:pw-only@nomad.internal:4646", "pw-only"),
            ("https://u:p%40ss%3Aword@host/", "p%40ss%3Aword"),
            ("https://u:pw@[2001:db8::1]:8443/", "pw"),
            ("not a url at all", None),
        ],
        ids=[
            "present",
            "absent",
            "username-only",
            "empty-password",
            "password-without-username",
            "percent-encoded",
            "ipv6-host",
            "non-url",
        ],
    )
    def test_returns_the_raw_password_segment(
        self, url: str, expected: str | None
    ) -> None:
        """Return the still-percent-encoded password, or ``None`` when there is none."""
        assert credential_url_password(url) == expected

    def test_an_unparseable_url_raises_rather_than_answering_none(self) -> None:
        """Propagate the parse failure instead of reporting "no credential here".

        ``None`` and the exception mean opposite things to a caller that masks:
        ``None`` licenses returning the input untouched, which for an
        unparseable credential URL would emit the password in the clear. A
        malformed bracketed IPv6 literal is one shape that raises; a netloc
        NFKC-normalising into a URL delimiter is another.
        """
        with pytest.raises(ValueError, match="Invalid IPv6 URL"):
            credential_url_password("https://user:pw@[bad:ipv6/")

    def test_a_netloc_rejected_under_nfkc_raises_too(self) -> None:
        """Cover the second parse failure the contract names.

        A full-width colon decomposes into the port delimiter under NFKC
        normalisation, so the parse refuses the netloc rather than guessing
        where the password ends.
        """
        with pytest.raises(ValueError, match="NFKC"):
            credential_url_password("https://user:pw@ho\uff1ast/")

    def test_a_plain_url_never_raises(self) -> None:
        """Confirm the raise above is specific, not a blanket parse failure."""
        assert credential_url_password(_PLAIN_URL) is None


class TestMapCredentialUrlPassword:
    """Cover :func:`map_credential_url_password`'s rewrite and its pass-throughs."""

    def test_applies_the_transform_to_the_password_only(self) -> None:
        """Rewrite the password segment and leave every other component alone."""
        assert map_credential_url_password(_CREDENTIAL_URL, str.upper) == (
            "http://nomad-user:NOMAD-SECRET@nomad.internal:4646/v1/jobs"
        )

    def test_preserves_every_component_around_the_password(self) -> None:
        """Keep scheme, username, host, port, path, params, query and fragment."""
        rewritten = map_credential_url_password(
            "http://u:pw@host:4646/v1/jobs;p=1?region=eu#frag", lambda _password: "X"
        )

        assert rewritten == "http://u:X@host:4646/v1/jobs;p=1?region=eu#frag"

    def test_preserves_ipv6_brackets_and_port(self) -> None:
        """Keep a bracketed IPv6 host and its port through the reassembly."""
        rewritten = map_credential_url_password(
            "https://u:pw@[2001:db8::1]:8443/api", lambda _password: "X"
        )

        assert rewritten == "https://u:X@[2001:db8::1]:8443/api"

    def test_preserves_an_empty_username(self) -> None:
        """Keep the empty username of a ``:password@host`` URL rather than dropping it."""
        rewritten = map_credential_url_password(
            "http://:pw@host:4646/v1", lambda _password: "X"
        )

        assert rewritten == "http://:X@host:4646/v1"

    def test_hands_the_transform_the_still_encoded_password(self) -> None:
        """Pass the raw percent-encoded segment so an encrypt/decrypt round trip is exact.

        ``urlparse`` does not unquote the password, and neither does the
        reassembly, so a password carrying ``@`` or ``:`` survives byte-for-byte
        only if the transform sees exactly what the URL holds.
        """
        seen: list[str] = []

        map_credential_url_password(
            "https://u:p%40ss%3Aword@host/",
            lambda password: seen.append(password) or "",
        )

        assert seen == ["p%40ss%3Aword"]

    def test_round_trips_a_percent_encoded_password_byte_for_byte(self) -> None:
        """Return the original URL when the transform is the identity."""
        url = "https://u:p%40ss%3Aword@host/"

        assert map_credential_url_password(url, lambda password: password) == url

    @pytest.mark.parametrize(
        "url",
        [
            _PLAIN_URL,
            "http://nomad-user@nomad.internal:4646",
            "http://nomad-user:@nomad.internal:4646",
        ],
        ids=["no-userinfo", "username-only", "empty-password"],
    )
    def test_returns_the_url_unchanged_when_there_is_no_password(
        self, url: str
    ) -> None:
        """Leave a URL the transform has nothing to apply to byte-identical.

        An empty password is *absent*, not a credential: transforming it would
        invent one where the operator supplied none.
        """
        assert map_credential_url_password(url, lambda _password: "INVENTED") == url

    def test_an_unparseable_url_propagates_rather_than_returning_the_input(
        self,
    ) -> None:
        """Refuse to hand back the untransformed URL when the parse fails.

        Returning the input here would mean a caller replacing a password with a
        mask silently emits the real one instead — which is what
        ``masking._redact_credential_url_token`` catches this exception to avoid.
        """
        with pytest.raises(ValueError, match="Invalid IPv6 URL"):
            map_credential_url_password(
                "https://user:pw@[bad:ipv6/", lambda _password: CREDENTIAL_URL_MASK
            )


class TestPreservableSecretStr:
    """Cover :data:`PreservableSecretStr`'s masked and preserved JSON dumps."""

    class _Model(BaseModel):
        api_key: PreservableSecretStr | None = None

    def test_json_dump_masks_the_secret(self) -> None:
        """Mask the secret in JSON-mode dumps, which is what the settings API reads."""
        model = self._Model(api_key="glsa_realtoken")
        assert model.model_dump(mode="json")["api_key"] == SECRET_STR_MASK

    def test_preserve_context_emits_the_real_secret(self) -> None:
        """Emit the plain secret under the preserve context, so the round-trip survives."""
        model = self._Model(api_key="glsa_realtoken")
        dumped = model.model_dump(mode="json", context=PRESERVE_CREDENTIALS_CONTEXT)
        assert dumped["api_key"] == "glsa_realtoken"

    def test_round_trip_under_the_preserve_context_keeps_the_secret(self) -> None:
        """Rebuild the model from a preserved dump and recover the original secret."""
        model = self._Model(api_key="glsa_realtoken")
        rebuilt = self._Model.model_validate(
            model.model_dump(mode="json", context=PRESERVE_CREDENTIALS_CONTEXT)
        )
        assert rebuilt.api_key is not None
        assert rebuilt.api_key.get_secret_value() == "glsa_realtoken"

    def test_two_distinct_secrets_dump_differently(self) -> None:
        """Distinguish a rotated secret from an unrotated one in a preserved dump."""
        first = self._Model(api_key="OLDKEY").model_dump(
            mode="json", context=PRESERVE_CREDENTIALS_CONTEXT
        )
        second = self._Model(api_key="NEWKEY").model_dump(
            mode="json", context=PRESERVE_CREDENTIALS_CONTEXT
        )
        assert first != second

    def test_none_stays_none(self) -> None:
        """Leave an unset secret as ``None`` under both dump modes."""
        model = self._Model()
        assert model.model_dump(mode="json")["api_key"] is None
        assert (
            model.model_dump(mode="json", context=PRESERVE_CREDENTIALS_CONTEXT)[
                "api_key"
            ]
            is None
        )

    def test_repr_masks_the_secret(self) -> None:
        """Keep the secret out of ``repr`` so it cannot leak into a log line."""
        rendered = repr(self._Model(api_key="glsa_realtoken"))
        assert SECRET_STR_MASK in rendered
        assert "glsa_realtoken" not in rendered

    def test_annotation_is_classified_secret(self) -> None:
        """Keep the annotation recognisable to the settings-override secret walker."""
        assert annotation_contains_secret(PreservableSecretStr | None) is True


class TestAuthCredentialSecretStr:
    """Cover :data:`AuthCredentialSecretStr`'s header-safety constraint."""

    class _Model(BaseModel):
        api_key: AuthCredentialSecretStr | None = None

    @pytest.mark.parametrize(
        "value", ["tok\n", "tok\r\nX-Injected: yes", "tok\x00", "tok\x0b", "tok\x7f"]
    )
    def test_rejects_a_character_one_client_will_not_send(self, value: str) -> None:
        """Refuse a credential the HTTP clients will not put on the wire."""
        with pytest.raises(ValidationError):
            self._Model(api_key=value)

    @pytest.mark.parametrize("value", ["tok", "Sf-Kx==", "a b", "tok\ttok"])
    def test_accepts_a_credential_both_clients_will_send(self, value: str) -> None:
        """Accept every shape both clients send, including ``HTAB`` and space."""
        model = self._Model(api_key=value)
        assert model.api_key is not None
        assert model.api_key.get_secret_value() == value

    def test_annotation_is_still_classified_secret(self) -> None:
        """Keep the wrapped annotation recognisable to the secret walker.

        Constraining the value by wrapping a constrained ``str`` in
        :class:`~pydantic.Secret` would drop ``SecretStr`` from the annotation and
        silently disable settings-API masking and at-rest encryption.
        """
        assert annotation_contains_secret(AuthCredentialSecretStr | None) is True

    def test_the_preserve_context_still_reaches_the_secret(self) -> None:
        """Keep the inherited preserve-context dump working through the constraint."""
        model = self._Model(api_key="glsa_realtoken")
        assert model.model_dump(mode="json")["api_key"] == SECRET_STR_MASK
        dumped = model.model_dump(mode="json", context=PRESERVE_CREDENTIALS_CONTEXT)
        assert dumped["api_key"] == "glsa_realtoken"


class TestCredentialUrlStrJsonSerializer:
    """Cover JSON redaction through :data:`CREDENTIAL_URL_STR_JSON_SERIALIZER`."""

    @pytest.fixture
    def adapter(self) -> TypeAdapter[str]:
        """Return a type adapter for a plain string carrying the marker."""
        return TypeAdapter(Annotated[str, CREDENTIAL_URL_STR_JSON_SERIALIZER])

    def test_json_dump_redacts_password(self, adapter: TypeAdapter[str]) -> None:
        """Mask the password on a JSON dump of a plain string URL."""
        assert adapter.dump_python(_CREDENTIAL_URL, mode="json") == _REDACTED_URL

    def test_python_dump_retains_password(self, adapter: TypeAdapter[str]) -> None:
        """Keep the real credential in python-mode dumps."""
        assert adapter.dump_python(_CREDENTIAL_URL, mode="python") == _CREDENTIAL_URL

    def test_preserve_context_skips_redaction(self, adapter: TypeAdapter[str]) -> None:
        """Skip redaction when the caller opts out through the context."""
        dumped = adapter.dump_python(
            _CREDENTIAL_URL, mode="json", context=PRESERVE_CREDENTIALS_CONTEXT
        )
        assert dumped == _CREDENTIAL_URL

    def test_the_settings_registry_detects_it_as_a_credential_url(self) -> None:
        """Let the settings registry recognise the marker as a credential URL."""
        assert annotation_is_credential_url(
            Annotated[str, CREDENTIAL_URL_STR_JSON_SERIALIZER]
        )

    def test_declares_a_string_return_type(self, adapter: TypeAdapter[str]) -> None:
        """Keep ``type: string`` in the serialization schema, which a bare wrap drops."""
        assert CREDENTIAL_URL_STR_JSON_SERIALIZER.return_type is str
        schema = adapter.json_schema(mode="serialization")
        assert schema["type"] == "string"
