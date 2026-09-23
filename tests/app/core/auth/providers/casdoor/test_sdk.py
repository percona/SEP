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

"""Define tests for the Casdoor SDK."""

import base64
from math import ceil

import pytest
from pydantic import SecretStr

from app.core.auth.providers.casdoor.sdk import CasdoorSDK
from app.core.exceptions import HTTPBadGatewayException


def test_casdoor_credentials_masked_in_repr():
    """Test that client_id and client_secret are masked in repr."""
    sdk = CasdoorSDK(
        endpoint="https://casdoor.example.com",
        client_id="my-client-id",
        client_secret="my-client-secret",
    )
    repr_str = repr(sdk)
    assert "my-client-id" not in repr_str
    assert "my-client-secret" not in repr_str


def test_casdoor_credential_value_encodes_secret_values():
    """Test that _credential_value correctly encodes the secret credentials."""
    sdk = CasdoorSDK(
        endpoint="https://casdoor.example.com",
        client_id="test-id",
        client_secret="test-secret",
    )
    expected = base64.b64encode(b"test-id:test-secret").decode("utf-8")
    assert sdk._credential_value == expected


def test_casdoor_credential_value_with_empty_credentials():
    """Test that empty credentials encode without raising (no validation guard)."""
    sdk = CasdoorSDK(
        endpoint="https://casdoor.example.com",
        client_id="",
        client_secret="",
    )
    expected = base64.b64encode(b":").decode("utf-8")
    assert sdk._credential_value == expected


def test_casdoor_credential_value_recomputes_after_credentials_change():
    """Test that _credential_value reflects mutated credentials (it is not cached)."""
    sdk = CasdoorSDK(
        endpoint="https://casdoor.example.com",
        client_id="test-id",
        client_secret="test-secret",
    )
    original = sdk._credential_value

    sdk.client_id = SecretStr("new-id")
    sdk.client_secret = SecretStr("new-secret")

    expected = base64.b64encode(b"new-id:new-secret").decode("utf-8")
    assert sdk._credential_value == expected
    assert sdk._credential_value != original


def test_casdoor_headers_carry_basic_authorization():
    """Assert the complete headers including Basic Authorization."""
    sdk = CasdoorSDK(
        endpoint="https://casdoor.example.com",
        client_id="test-id",
        client_secret="test-secret",
    )
    expected = base64.b64encode(b"test-id:test-secret").decode("utf-8")
    assert sdk.headers == {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Basic {expected}",
    }


@pytest.mark.asyncio
async def test_get_tokens_paginates_by_page_size(mocker):
    """Verify get_tokens fetches ceil(total / page_size) pages, not ``total`` pages."""
    sdk = CasdoorSDK(
        endpoint="https://casdoor.example.com",
        client_id="test-id",
        client_secret="test-secret",
    )
    page_size = 100  # matches the internal page size in CasdoorSDK.get_tokens
    total = 250
    expected_pages = ceil(total / page_size)
    page = {"data": [{"user": "alice", "name": "tok"}], "data2": total}
    get_mock = mocker.patch.object(
        CasdoorSDK, "get", new=mocker.AsyncMock(return_value=page)
    )

    yielded = [token async for token in sdk.get_tokens("built-in")]

    assert get_mock.await_count == expected_pages
    assert len(yielded) == expected_pages


@pytest.mark.asyncio
async def test_get_users_returns_the_listed_users(mocker):
    """Return the ``data`` array of a successful user listing."""
    sdk = CasdoorSDK(
        endpoint="https://casdoor.example.com",
        client_id="test-id",
        client_secret="test-secret",
    )
    listed = [{"id": "u1", "name": "alice"}]
    mocker.patch.object(
        CasdoorSDK,
        "get",
        new=mocker.AsyncMock(return_value={"status": "ok", "data": listed}),
    )

    assert await sdk.get_users() == listed


@pytest.mark.asyncio
async def test_get_users_raises_on_an_error_body_without_caching_it(mocker):
    """Raise on Casdoor's HTTP-200 error body and retry the listing on the next call.

    Casdoor answers a denied or failed ``/api/get-users`` with HTTP 200 and
    ``"data": null``. Returning that ``None`` would reach callers as a user list
    and be cached for the listing's whole TTL.
    """
    sdk = CasdoorSDK(
        endpoint="https://casdoor.example.com",
        client_id="test-id",
        client_secret="test-secret",
    )
    error_body = {"status": "error", "msg": "Unauthorized operation", "data": None}
    get_mock = mocker.patch.object(
        CasdoorSDK, "get", new=mocker.AsyncMock(return_value=error_body)
    )
    attempts = 2

    for _ in range(attempts):
        with pytest.raises(HTTPBadGatewayException):
            await sdk.get_users()

    assert get_mock.await_count == attempts
