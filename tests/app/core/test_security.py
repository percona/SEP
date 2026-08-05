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

"""Define tests for the app.core.security module."""

import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.core.security import (
    crypto_serializer,
    crypto_timestamp_serializer,
    get_internal_token,
    require_internal_token,
)


def test_crypto_serializer_basic():
    """Test basic serialization and deserialization."""
    payload = {"user_id": 123, "email": "test@example.com"}
    token = crypto_serializer.dumps(payload)
    decoded_payload = crypto_serializer.loads(token)
    assert decoded_payload == payload


def test_crypto_timestamp_serializer_basic():
    """Test basic serialization and deserialization with timestamp."""
    payload = {"user_id": 456, "email": "time@example.com"}
    token = crypto_timestamp_serializer.dumps(payload)
    decoded_payload = crypto_timestamp_serializer.loads(token)
    assert decoded_payload == payload


def test_get_internal_token_returns_secret(mocker):
    """``get_internal_token`` returns the configured token's secret value."""
    mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", SecretStr("internal-secret"))
    assert get_internal_token() == "internal-secret"


def test_get_internal_token_returns_none_when_unset(mocker):
    """``get_internal_token`` returns ``None`` when the token is unset."""
    mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", None)
    assert get_internal_token() is None


def test_get_internal_token_returns_none_when_empty(mocker):
    """``get_internal_token`` treats an empty ``SecretStr`` as absent."""
    mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", SecretStr(""))
    assert get_internal_token() is None


def test_require_internal_token_returns_secret(mocker):
    """``require_internal_token`` returns the configured token's secret value."""
    mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", SecretStr("internal-secret"))
    assert require_internal_token() == "internal-secret"


def test_require_internal_token_raises_when_absent(mocker):
    """``require_internal_token`` raises ``RuntimeError`` when the token is absent."""
    mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", None)
    with pytest.raises(RuntimeError, match="SEP_INTERNAL_TOKEN must be configured"):
        require_internal_token()
