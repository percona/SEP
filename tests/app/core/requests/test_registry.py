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

"""Tests for :meth:`ClientRegistry.invalidate`."""

import pytest

from app.core.requests.registry import ClientRegistry
from app.core.requests.remote_api import RemoteAPI


@pytest.mark.asyncio
async def test_invalidate_evicts_matching_and_keeps_others() -> None:
    """``invalidate`` evicts and closes only clients on the matching endpoint."""
    registry = ClientRegistry()
    try:
        client_a = await registry.get(RemoteAPI, endpoint="https://a.example.org")
        client_b = await registry.get(RemoteAPI, endpoint="https://b.example.org")

        await registry.invalidate("https://a.example.org")

        assert client_a._session is None  # the evicted client was closed
        reborn_a = await registry.get(RemoteAPI, endpoint="https://a.example.org")
        survived_b = await registry.get(RemoteAPI, endpoint="https://b.example.org")
        assert reborn_a is not client_a  # a was reconstructed fresh
        assert survived_b is client_b  # b was left untouched
    finally:
        await registry.close_all()


@pytest.mark.asyncio
async def test_invalidate_is_trailing_slash_insensitive() -> None:
    """``invalidate`` matches regardless of a trailing slash on the endpoint."""
    registry = ClientRegistry()
    try:
        client = await registry.get(RemoteAPI, endpoint="https://a.example.org")
        await registry.invalidate("https://a.example.org/")
        assert client._session is None
    finally:
        await registry.close_all()


@pytest.mark.asyncio
async def test_invalidate_noop_when_closed() -> None:
    """``invalidate`` is a no-op on a closed registry instead of raising."""
    registry = ClientRegistry()
    await registry.close_all()
    await registry.invalidate("https://a.example.org")


@pytest.mark.asyncio
async def test_invalidate_noop_when_no_match() -> None:
    """``invalidate`` for an unknown endpoint leaves existing clients intact."""
    registry = ClientRegistry()
    try:
        client = await registry.get(RemoteAPI, endpoint="https://a.example.org")
        await registry.invalidate("https://unknown.example.org")
        assert client._session is not None
    finally:
        await registry.close_all()


@pytest.mark.asyncio
async def test_invalidate_defers_the_close_while_a_consumer_holds() -> None:
    """``invalidate`` evicts at once and closes once the last holder releases."""
    registry = ClientRegistry()
    try:
        client = await registry.get(RemoteAPI, endpoint="https://a.example.org")

        async with client.hold():
            await registry.invalidate("https://a.example.org")

            assert client._session is not None  # the holder keeps it usable
            reborn = await registry.get(RemoteAPI, endpoint="https://a.example.org")
            assert reborn is not client  # new work goes to a fresh client

        assert client._session is None
    finally:
        await registry.close_all()
