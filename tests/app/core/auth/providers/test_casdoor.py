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

"""Define tests for the app.core.auth.providers.casdoor module."""

import base64

from app.core.auth.providers.casdoor import CasdoorSDK


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
