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

"""Test that a transient Tasks API 503 does not fail a host's probe outright.

A sweep dispatches up to ``MAX_CONCURRENT_PROBES`` hosts at once, each making its
own requests to the Tasks API -- exactly the burst that can transiently exhaust
that process's own database connection pool (SEP-2026 sized it at 5 connections).
``_with_capacity_retry`` absorbs that queueing accident with a bounded retry
instead of letting it count as a dispatch or collection failure, and stays
bounded both in attempt count and in total added wait so a pool that stays
saturated still gives up and lets the ordinary failure path record it.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import HTTPServiceUnavailableException
from app.sep.apps.om_inventory.dispatch import (
    _CAPACITY_RETRY_ATTEMPTS,
    _with_capacity_retry,
    probe_host,
)
from app.sep.apps.om_inventory.inventory import InventoryService
from app.sep.apps.om_inventory.mapping import MappedService
from app.sep.apps.om_inventory.models import NodeResolution

HISTORY_ID = 901
HOST = "replicaset-cluster-node00"


def entries() -> list[MappedService]:
    """Build the one resolved service a host serves.

    :return: The mapping the dispatch is built from.
    """
    return [
        MappedService(
            service=InventoryService(
                service_id=1,
                external_id="a35f6b6e-9b34-4e6a-8f0e-6a6d0f2b6c1a",
                name="svc",
                port=27017,
                node_name=HOST,
                node_address="10.0.0.1",
            ),
            executor_host=HOST,
            resolution=NodeResolution.NAME,
        )
    ]


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the real backoff wait, and the poll loop's own wait between them."""
    from app.sep.apps.om_inventory import dispatch
    from app.sep.apps.om_inventory.config import om_inventory_settings

    monkeypatch.setattr(dispatch, "_CAPACITY_RETRY_BASE_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(om_inventory_settings, "POLL_INTERVAL", 0)


class TestWithCapacityRetry:
    """Pin the retry helper directly, apart from any dispatch machinery."""

    @pytest.mark.asyncio
    async def test_succeeds_once_the_pool_frees_up(self) -> None:
        """A 503 that clears within the attempt budget is invisible to the caller."""
        calls = 0

        async def flaky() -> str:
            nonlocal calls
            calls += 1
            if calls < _CAPACITY_RETRY_ATTEMPTS:
                raise HTTPServiceUnavailableException
            return "ok"

        assert await _with_capacity_retry(flaky) == "ok"
        assert calls == _CAPACITY_RETRY_ATTEMPTS

    @pytest.mark.asyncio
    async def test_gives_up_after_the_bounded_number_of_attempts(self) -> None:
        """A pool that never frees up still fails, rather than retrying forever."""
        calls = 0

        async def always_full() -> str:
            nonlocal calls
            calls += 1
            raise HTTPServiceUnavailableException

        with pytest.raises(HTTPServiceUnavailableException):
            await _with_capacity_retry(always_full)

        # Bounded in count: exactly the configured number of tries, not one more.
        assert calls == _CAPACITY_RETRY_ATTEMPTS

    @pytest.mark.asyncio
    async def test_a_different_error_is_not_retried(self) -> None:
        """Only the capacity signal is absorbed -- everything else fails fast."""
        calls = 0

        async def broken() -> str:
            nonlocal calls
            calls += 1
            raise RuntimeError("not a capacity problem")

        with pytest.raises(RuntimeError):
            await _with_capacity_retry(broken)

        assert calls == 1


class TestProbeHostAbsorbsATransient503:
    """The end-to-end shape: a host's probe survives a queueing accident."""

    @pytest.mark.asyncio
    async def test_a_dispatch_that_clears_on_retry_still_succeeds(self) -> None:
        """One 503 on the initial dispatch is not counted as this host's failure."""
        post_calls = 0

        async def post(_path: str, **_: Any) -> dict[str, Any]:
            nonlocal post_calls
            post_calls += 1
            if post_calls == 1:
                raise HTTPServiceUnavailableException
            return {"id": HISTORY_ID}

        async def get(_path: str, **_: Any) -> dict[str, Any]:
            return {"id": HISTORY_ID, "status": "success"}

        api = MagicMock()
        api.post = AsyncMock(side_effect=post)
        api.get = AsyncMock(side_effect=get)

        async def stream(*_a: Any, **_kw: Any) -> Any:
            return
            yield  # pragma: no cover - makes this an async generator

        api.stream = stream

        result = await probe_host(api, HOST, entries())

        one_retry = 2
        assert post_calls == one_retry
        assert result.error is None
        assert result.task_history_id == HISTORY_ID

    @pytest.mark.asyncio
    async def test_a_pool_that_stays_saturated_is_recorded_as_a_failure(self) -> None:
        """Exhausting the retry budget still fails the host -- it does not hang."""
        post_calls = 0

        async def always_full(_path: str, **_: Any) -> dict[str, Any]:
            nonlocal post_calls
            post_calls += 1
            raise HTTPServiceUnavailableException

        api = MagicMock()
        api.post = AsyncMock(side_effect=always_full)

        result = await probe_host(api, HOST, entries())

        assert post_calls == _CAPACITY_RETRY_ATTEMPTS
        assert "HTTPServiceUnavailableException" in (result.error or "")
        # Nothing reached the queue, so there is nothing for probe_host to release.
        assert result.task_history_id is None
