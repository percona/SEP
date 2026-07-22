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

"""Define tests for RemoteAPI request-logging helpers and the upload primitive."""

import pytest
from aioresponses import aioresponses
from fastapi import HTTPException, status

from app.core.exceptions import HTTPBadGatewayException, HTTPConflictException
from app.core.requests import RemoteAPI
from app.core.requests.remote_api import (
    _REDACTED_VALUE,
    _sanitize_request_kwargs,
    UPSTREAM_NON_JSON_HEADER,
)

_UPLOAD_URL = "http://localhost:8000/upload"


@pytest.fixture
def remote_api() -> RemoteAPI:
    """Provide a real RemoteAPI client pointed at a local base URL."""
    return RemoteAPI(endpoint="http://localhost:8000/")


def _one_file() -> dict:
    """Return a single-file multipart mapping for upload tests."""
    return {"file": ("bundle.tar.gz", b"bundle-bytes", "application/octet-stream")}


def test_redacts_sensitive_headers():
    """Verify credential-bearing headers are masked, others preserved."""
    safe = _sanitize_request_kwargs(
        {"headers": {"Authorization": "Bearer x", "Accept": "application/json"}}
    )

    assert safe["headers"]["Authorization"] == _REDACTED_VALUE
    assert safe["headers"]["Accept"] == "application/json"


def test_redacts_password_in_json_body():
    """Verify a password in a JSON body is masked in the logged copy."""
    safe = _sanitize_request_kwargs({"json": {"user": "alice", "password": "secret"}})

    assert safe["json"]["password"] == _REDACTED_VALUE
    assert safe["json"]["user"] == "alice"


def test_redacts_password_in_form_data_body():
    """Verify a password in a form ``data`` body is masked in the logged copy."""
    safe = _sanitize_request_kwargs(
        {"data": {"grant_type": "password", "password": "secret"}}
    )

    assert safe["data"]["password"] == _REDACTED_VALUE
    assert safe["data"]["grant_type"] == "password"


def test_does_not_mutate_the_original_kwargs():
    """Verify the outgoing request keeps its real credentials (copy is masked)."""
    kwargs = {
        "headers": {"Authorization": "Bearer x"},
        "json": {"password": "secret"},
    }

    _sanitize_request_kwargs(kwargs)

    assert kwargs["headers"]["Authorization"] == "Bearer x"
    assert kwargs["json"]["password"] == "secret"


def test_passes_through_non_dict_body():
    """Verify a non-mapping body is left untouched."""
    safe = _sanitize_request_kwargs({"data": b"raw-bytes"})

    assert safe["data"] == b"raw-bytes"


def test_extra_sensitive_headers_masked():
    """Mask a caller-supplied custom header name via the extra-redaction keyword."""
    safe = _sanitize_request_kwargs(
        {"headers": {"X-Custom-Token": "raw-secret", "Accept": "application/json"}},
        extra_sensitive_headers=frozenset({"x-custom-token"}),
    )

    assert safe["headers"]["X-Custom-Token"] == _REDACTED_VALUE
    assert safe["headers"]["Accept"] == "application/json"


def test_extra_sensitive_headers_defaults_to_existing_behavior():
    """Keep a custom header untouched when no extra redaction is requested."""
    safe = _sanitize_request_kwargs({"headers": {"X-Custom-Token": "raw-secret"}})

    assert safe["headers"]["X-Custom-Token"] == "raw-secret"


def test_extra_sensitive_body_fields_masked():
    """Mask a caller-supplied custom body key via the extra-redaction keyword."""
    safe = _sanitize_request_kwargs(
        {"json": {"client_token": "raw-secret", "ticket_number": "CS0001"}},
        extra_sensitive_body_fields=frozenset({"client_token"}),
    )

    assert safe["json"]["client_token"] == _REDACTED_VALUE
    assert safe["json"]["ticket_number"] == "CS0001"


def test_extra_sensitive_body_fields_defaults_to_existing_behavior():
    """Keep a custom body key untouched when no extra redaction is requested."""
    safe = _sanitize_request_kwargs({"json": {"client_token": "raw-secret"}})

    assert safe["json"]["client_token"] == "raw-secret"


def test_extra_sensitive_body_fields_keeps_built_in_masking():
    """Mask the always-sensitive body keys alongside the caller-supplied ones."""
    safe = _sanitize_request_kwargs(
        {"json": {"password": "pw", "client_token": "raw-secret"}},
        extra_sensitive_body_fields=frozenset({"client_token"}),
    )

    assert safe["json"]["password"] == _REDACTED_VALUE
    assert safe["json"]["client_token"] == _REDACTED_VALUE


def test_redact_headers_masks_within_context_only(remote_api):
    """Mask extra header names only for the duration of the ``redact_headers`` block."""
    with remote_api.redact_headers(["X-Custom-Token"]):
        active = remote_api._extra_sensitive_headers.get()
    after = remote_api._extra_sensitive_headers.get()

    assert active == frozenset({"x-custom-token"})
    assert after == frozenset()


def test_redact_headers_nesting_unions_with_outer_context(remote_api):
    """Accumulate an inner ``redact_headers`` block's names on top of the outer set."""
    with remote_api.redact_headers(["X-Outer"]):
        with remote_api.redact_headers(["X-Inner"]):
            nested = remote_api._extra_sensitive_headers.get()
        restored = remote_api._extra_sensitive_headers.get()

    assert nested == frozenset({"x-outer", "x-inner"})
    assert restored == frozenset({"x-outer"})


def test_redact_body_fields_masks_within_context_only(remote_api):
    """Mask extra body keys only for the duration of the ``redact_body_fields`` block."""
    with remote_api.redact_body_fields(["Client_Token"]):
        active = remote_api._extra_sensitive_body_fields.get()
    after = remote_api._extra_sensitive_body_fields.get()

    assert active == frozenset({"client_token"})
    assert after == frozenset()


def test_redact_body_fields_nesting_unions_with_outer_context(remote_api):
    """Accumulate an inner ``redact_body_fields`` block's keys on top of the outer set."""
    with remote_api.redact_body_fields(["outer_token"]):
        with remote_api.redact_body_fields(["inner_token"]):
            nested = remote_api._extra_sensitive_body_fields.get()
        restored = remote_api._extra_sensitive_body_fields.get()

    assert nested == frozenset({"outer_token", "inner_token"})
    assert restored == frozenset({"outer_token"})


class TestUpload:
    """Cover the multipart ``RemoteAPI.upload`` primitive."""

    pytestmark = pytest.mark.asyncio

    async def test_returns_parsed_json_body(self, remote_api):
        """Return the parsed JSON body on a 2xx JSON response."""
        with aioresponses() as mock:
            mock.post(_UPLOAD_URL, status=status.HTTP_200_OK, payload={"ok": True})
            async with remote_api:
                result = await remote_api.upload(
                    "upload", files=_one_file(), fields={"client_id": "acme"}
                )

        assert result == {"ok": True}

    async def test_sends_multipart_content_type_with_boundary(self, remote_api):
        """Send a ``multipart/form-data`` Content-Type carrying a boundary, not JSON."""
        with aioresponses() as mock:
            mock.post(_UPLOAD_URL, status=status.HTTP_200_OK, payload={"ok": True})
            async with remote_api:
                await remote_api.upload(
                    "upload", files=_one_file(), fields={"client_id": "acme"}
                )
            request = next(iter(mock.requests.values()))[0]

        content_type = request.kwargs["headers"]["Content-Type"]
        assert content_type.startswith("multipart/form-data")
        assert "boundary=" in content_type

    async def test_maps_conflict_to_project_exception(self, remote_api):
        """Map a 409 response to ``HTTPConflictException`` via ``request``."""
        with aioresponses() as mock:
            mock.post(
                _UPLOAD_URL,
                status=status.HTTP_409_CONFLICT,
                payload={"detail": "already ingested"},
            )
            async with remote_api:
                with pytest.raises(HTTPConflictException):
                    await remote_api.upload("upload", files=_one_file())

    async def test_maps_bad_gateway_to_project_exception(self, remote_api):
        """Map a 502 response to ``HTTPBadGatewayException`` via ``request``."""
        with aioresponses() as mock:
            mock.post(
                _UPLOAD_URL,
                status=status.HTTP_502_BAD_GATEWAY,
                payload={"detail": "upstream down"},
            )
            async with remote_api:
                with pytest.raises(HTTPBadGatewayException):
                    await remote_api.upload("upload", files=_one_file())

    async def test_non_json_success_body_returns_none(self, remote_api):
        """Return ``None`` for a 2xx response whose body is not JSON."""
        with aioresponses() as mock:
            mock.post(
                _UPLOAD_URL,
                status=status.HTTP_201_CREATED,
                body="OK",
                content_type="text/plain",
            )
            async with remote_api:
                result = await remote_api.upload("upload", files=_one_file())

        assert result is None

    async def test_non_json_error_body_still_raises_stamped(self, remote_api):
        """Raise the stamped upstream error for a non-JSON 4xx/5xx body."""
        with aioresponses() as mock:
            mock.post(
                _UPLOAD_URL,
                status=status.HTTP_502_BAD_GATEWAY,
                body="<html>bad gateway</html>",
                content_type="text/html",
            )
            async with remote_api:
                with pytest.raises(HTTPException) as exc_info:
                    await remote_api.upload("upload", files=_one_file())

        assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY
        assert exc_info.value.headers.get(UPSTREAM_NON_JSON_HEADER) == "1"
