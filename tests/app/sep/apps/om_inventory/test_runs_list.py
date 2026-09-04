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

"""Test ``GET /runs`` date-range filtering.

The window is applied before ``limit``: a week of twenty-one runs is twenty-one
runs, not the twenty newest overall with the older-than-a-week ones dropped. That
is the difference between a real history filter and a cosmetic one over a capped
page.
"""

from datetime import datetime, timedelta, UTC

import pytest
import pytest_asyncio
from fastapi import status
from httpx import ASGITransport, AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import require_minimum_role_for_unsafe_methods
from app.core.auth.providers.casdoor.models import CasdoorUser
from app.sep.apps.om_inventory.crud import ProbeRunManager
from app.sep.apps.om_inventory.models import ProbeRun, ProbeRunStatus
from app.sep.deps import (
    get_current_user,
    get_session,
    require_bearer_for_unsafe_methods,
)
from app.sep.main import sep_app

BASE = "/api/apps/om_inventory"

#: Three stamps, a day apart, so a window can include the middle one and exclude
#: the others without depending on clock-second fuzz.
DAY = timedelta(days=1)
T0 = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
T1 = T0 + DAY
T2 = T1 + DAY


@pytest_asyncio.fixture
async def api(regular_user: CasdoorUser, session: AsyncSession) -> AsyncClient:
    """Yield an authenticated client sharing the test session.

    :param regular_user: The authenticated user.
    :param session: The database session the routes should use.
    :return: The client.
    """
    sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
    sep_app.dependency_overrides[require_minimum_role_for_unsafe_methods] = lambda: None
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user
    sep_app.dependency_overrides[get_session] = lambda: session
    client = AsyncClient(
        transport=ASGITransport(app=sep_app),
        base_url="http://test",
        headers={"Authorization": "Bearer test"},
    )
    try:
        yield client
    finally:
        await client.aclose()
        sep_app.dependency_overrides = {}


async def record_run(session: AsyncSession, started_at: datetime) -> ProbeRun:
    """Write a finished run that started at ``started_at``.

    :param session: The database session.
    :param started_at: When the sweep started.
    :return: The saved run.
    """
    run = await ProbeRunManager.save(session, ProbeRun(status=ProbeRunStatus.SUCCESS))
    run.started_at = started_at
    return await ProbeRunManager.save(session, run)


@pytest.mark.asyncio
async def test_list_runs_filters_started_at_before_limit(
    api: AsyncClient, session: AsyncSession
) -> None:
    """Keep the in-window runs, then apply limit, so an older in-window run survives.

    Three runs a day apart, ``since`` on the oldest, ``limit=2``: without the
    window the newest two would win and the oldest would drop. With it, the two
    oldest are the ones in range once the newest is excluded by ``until``.
    """
    oldest = await record_run(session, T0)
    middle = await record_run(session, T1)
    await record_run(session, T2)

    response = await api.get(
        f"{BASE}/runs",
        params={
            "since": T0.isoformat(),
            "until": T1.isoformat(),
            "limit": 2,
        },
    )

    assert response.status_code == status.HTTP_200_OK
    ids = [row["run_id"] for row in response.json()]
    assert ids == [str(middle.id), str(oldest.id)]


@pytest.mark.asyncio
async def test_list_runs_since_excludes_older(
    api: AsyncClient, session: AsyncSession
) -> None:
    """A lower bound drops runs that started before it."""
    await record_run(session, T0)
    kept = await record_run(session, T2)

    response = await api.get(f"{BASE}/runs", params={"since": T1.isoformat()})

    assert response.status_code == status.HTTP_200_OK
    assert [row["run_id"] for row in response.json()] == [str(kept.id)]


@pytest.mark.asyncio
async def test_list_runs_until_excludes_newer(
    api: AsyncClient, session: AsyncSession
) -> None:
    """An upper bound drops runs that started after it."""
    kept = await record_run(session, T0)
    await record_run(session, T2)

    response = await api.get(f"{BASE}/runs", params={"until": T1.isoformat()})

    assert response.status_code == status.HTTP_200_OK
    assert [row["run_id"] for row in response.json()] == [str(kept.id)]


@pytest.mark.asyncio
async def test_list_runs_rejects_until_before_since(api: AsyncClient) -> None:
    """An inverted window is a validation failure, not an empty page."""
    response = await api.get(
        f"{BASE}/runs",
        params={"since": T2.isoformat(), "until": T0.isoformat()},
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert response.json()["detail"] == "until must not be before since"


@pytest.mark.asyncio
async def test_list_runs_omits_window_when_unset(
    api: AsyncClient, session: AsyncSession
) -> None:
    """No date params still returns newest first, including the oldest row."""
    oldest = await record_run(session, T0)
    newest = await record_run(session, T2)

    response = await api.get(f"{BASE}/runs")

    assert response.status_code == status.HTTP_200_OK
    assert [row["run_id"] for row in response.json()] == [
        str(newest.id),
        str(oldest.id),
    ]
