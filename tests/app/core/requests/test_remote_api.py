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

"""Define tests for RemoteAPI request-logging helpers."""

from app.core.requests.remote_api import _REDACTED_VALUE, _sanitize_request_kwargs


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
