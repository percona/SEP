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

import pytest
from pydantic import BaseModel, TypeAdapter

from app.core.utils.fields import (
    CREDENTIAL_URL_MASK,
    CredentialHttpUrl,
    preserve_credential_url_password,
    PRESERVE_CREDENTIALS_CONTEXT,
    redact_credential_url,
    StrCredentialAnyUrl,
    StrCredentialHttpUrl,
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
        """Match the SEP-1381 default redaction mask format."""
        assert CREDENTIAL_URL_MASK == "****"
