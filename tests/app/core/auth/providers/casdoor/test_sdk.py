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


def test_casdoor_api_key_decodes_secret_values():
    """Test that api_key correctly encodes the secret credentials."""
    sdk = CasdoorSDK(
        endpoint="https://casdoor.example.com",
        client_id="test-id",
        client_secret="test-secret",
    )
    expected = base64.b64encode(b"test-id:test-secret").decode("utf-8")
    assert sdk.api_key == expected


def test_casdoor_api_key_with_empty_credentials():
    """Test that empty credentials encode without raising (no validation guard)."""
    sdk = CasdoorSDK(
        endpoint="https://casdoor.example.com",
        client_id="",
        client_secret="",
    )
    expected = base64.b64encode(b":").decode("utf-8")
    assert sdk.api_key == expected


def test_casdoor_api_key_recomputes_after_credentials_change():
    """Test that api_key reflects mutated credentials (it is not cached)."""
    sdk = CasdoorSDK(
        endpoint="https://casdoor.example.com",
        client_id="test-id",
        client_secret="test-secret",
    )
    original = sdk.api_key

    sdk.client_id = SecretStr("new-id")
    sdk.client_secret = SecretStr("new-secret")

    expected = base64.b64encode(b"new-id:new-secret").decode("utf-8")
    assert sdk.api_key == expected
    assert sdk.api_key != original


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
