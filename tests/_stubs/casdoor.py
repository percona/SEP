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

"""Canonical stub for the Casdoor OAuth provider.

Pattern reference for milestone M4. The actual consolidation work pulls the
Casdoor stubs currently scattered across plugin-level ``conftest.py`` modules
into a single fixture exposed from here, recorded with ``vcrpy`` against
staging. Until then this module documents the contract by example so plugin
authors know where canonical stubs will live.

Usage from a test::

    from tests._stubs.casdoor import patch_casdoor_sdk

    def test_something(mocker, casdoor_user_data):
        patch_casdoor_sdk(mocker, user=casdoor_user_data)
        ...

The companion ``nomad.py`` and ``pmm.py`` modules follow the same shape.
"""

from typing import Any

from pytest_mock import MockerFixture


def patch_casdoor_sdk(
    mocker: MockerFixture,
    *,
    user: dict[str, Any],
    token_payload: dict[str, Any] | None = None,
) -> None:
    """Patch ``CasdoorSDK`` async methods with deterministic payloads.

    This is a thin reference of the M4 contract. The production stub will
    expand the surface (introspection, refresh, token deletion) and source
    payloads from cassette files recorded with ``vcrpy``.

    :param mocker: The ``pytest-mock`` fixture from the calling test.
    :type mocker: pytest_mock.MockerFixture
    :param user: A Casdoor user payload compatible with
        ``app.models.CasdoorUser``.
    :type user: dict[str, Any]
    :param token_payload: Optional pre-built token payload; defaults to a
        minimal valid payload built from ``user``.
    :type token_payload: dict[str, Any] | None
    """
    payload = token_payload or {
        "iss": "https://allowed-issuer.com",
        "sub": user.get("id"),
        "aud": ["test-client-id"],
        "username": user.get("username"),
        "active": True,
    }
    mocker.patch(
        "app.core.auth.providers.casdoor.CasdoorSDK.introspect_token",
        new=mocker.AsyncMock(return_value=payload),
    )
    mocker.patch(
        "app.core.auth.providers.casdoor.CasdoorSDK.get_user",
        new=mocker.AsyncMock(return_value=user),
    )
