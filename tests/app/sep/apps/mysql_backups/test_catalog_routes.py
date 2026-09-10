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

"""Tests for the per-service and task-scoped backup catalog query routes."""

from collections.abc import Sequence
from datetime import datetime, UTC
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import status
from httpx import Response
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import HTTPBadGatewayException, HTTPNotFoundException
from app.core.pagination import MAX_PAGINATION_LIMIT
from app.core.requests import RemoteAPI
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.mysql_backups.crud import MysqlBackupRunManager
from app.sep.apps.mysql_backups.deps import MAX_TASK_RUN_SCAN
from app.sep.apps.mysql_backups.forms import OWNER
from app.sep.apps.mysql_backups.models import MysqlBackupRun
from tests.app.factories import TaskFactory
from tests.app.sep.apps.mysql_backups.conftest import (
    authenticated_get,
    inventory_mock,
    service_payload,
)

_URL = "/api/apps/mysql_backups/services/{service_id}/backups"
_TASK_URL = "/api/apps/mysql_backups/{task_name}/backups"
_TASK_NAME = "nightly-mysql-backup"

# 500 rows at the upstream 200-row page cap; the route's own task lookup makes a
# fourth request on top.
_MAX_HISTORY_PAGES = 3


def _is_history_call(call: Any) -> bool:
    """Return whether a recorded Tasks API call targeted the history endpoint."""
    return str(call.args[0]).endswith("/history/")


def _task_payload(*, name: str = _TASK_NAME, owner: str = OWNER) -> dict[str, Any]:
    """Return a Tasks-API task payload the backups task dependency accepts."""
    return TaskFactory.build(name=name, owner=owner).model_dump(mode="json")


def _history_page(history_ids: Sequence[int], *, total: int | None = None) -> dict:
    """Return one ``GET /{task}/history/`` page listing ``history_ids``."""
    ids = list(history_ids)
    return {
        "items": [{"id": history_id} for history_id in ids],
        "total": len(ids) if total is None else total,
        "offset": 0,
        "limit": len(ids),
    }


def _tasks_mock(
    *,
    task: dict[str, Any] | None = None,
    task_raises: Exception | None = None,
    history: Sequence[Any] = (),
    history_raises: Exception | None = None,
) -> AsyncMock:
    """Build a Tasks API mock answering the task lookup and the history walk.

    ``history`` pages are served in request order and exhausted into empty pages,
    so a test can under-supply them without the walk re-reading a page forever.
    """
    pages = list(history)

    async def _get(url: str, **kwargs: Any) -> Any:
        if url.endswith("/history/"):
            if history_raises is not None:
                raise history_raises
            if not pages:
                return _history_page([])
            page = pages.pop(0)
            if not isinstance(page, dict):
                return page
            limit = (kwargs.get("params") or {}).get("limit")
            items = page.get("items")
            if limit is None or not isinstance(items, list):
                return page
            return {**page, "items": items[:limit], "limit": limit}
        if task_raises is not None:
            raise task_raises
        return task

    mock = AsyncMock(spec=RemoteAPI)
    mock.get.side_effect = _get
    return mock


async def _save_run(session: AsyncSession, **fields: Any) -> None:
    """Persist one catalog row, defaulting the fields these tests do not vary."""
    fields.setdefault("service_name", "svc-a")
    fields.setdefault("backup_type", "M")
    await MysqlBackupRunManager.save(session, MysqlBackupRun(**fields))


class TestTaskBackupsRoute:
    """GET /api/apps/mysql_backups/{task_name}/backups."""

    async def _get(
        self,
        session: AsyncSession,
        tasks: AsyncMock,
        regular_user: object,
        *,
        inventory: AsyncMock | None = None,
        params: dict[str, Any] | None = None,
    ) -> Response:
        """Drive the task-scoped route with the given session + Tasks mock."""
        return await authenticated_get(
            _TASK_URL.format(task_name=_TASK_NAME),
            session=session,
            inventory=inventory or inventory_mock(service_payload("svc-a")),
            user=regular_user,
            params=params,
            tasks=tasks,
        )

    @pytest.mark.asyncio
    async def test_returns_the_tasks_runs_newest_first(
        self, session, regular_user
    ) -> None:
        """Return every run the task catalogued, newest completion first."""
        for index, hour in enumerate((3, 1, 5), start=1):
            await _save_run(
                session,
                task_history_id=index,
                location=f"/data/mydumper/svc-a/{index}",
                finished_at=datetime(2026, 7, 29, hour, tzinfo=UTC),
            )

        response = await self._get(
            session,
            _tasks_mock(task=_task_payload(), history=[_history_page([1, 2, 3])]),
            regular_user,
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == 3  # noqa: PLR2004
        assert [item["location"] for item in body["items"]] == [
            "/data/mydumper/svc-a/3",
            "/data/mydumper/svc-a/1",
            "/data/mydumper/svc-a/2",
        ]

    @pytest.mark.asyncio
    async def test_paginates_the_catalogued_runs(self, session, regular_user) -> None:
        """Honour the caller's offset/limit and echo them back with the true total."""
        for index in range(1, 6):
            await _save_run(session, task_history_id=index)

        response = await self._get(
            session,
            _tasks_mock(task=_task_payload(), history=[_history_page([1, 2, 3, 4, 5])]),
            regular_user,
            params={"offset": 2, "limit": 2},
        )

        body = response.json()
        assert body["total"] == 5  # noqa: PLR2004
        assert body["offset"] == 2  # noqa: PLR2004
        assert body["limit"] == 2  # noqa: PLR2004
        assert len(body["items"]) == 2  # noqa: PLR2004

    @pytest.mark.asyncio
    async def test_carries_the_restore_ready_source_and_run_details(
        self, session, regular_user
    ) -> None:
        """Serve the resolved source alongside the fields a restore form needs."""
        await _save_run(
            session,
            task_history_id=1,
            hostname="db01",
            backup_type="X",
            location="/data/xtrabackup/svc-a/base",
            upload_destination="s3://bucket/svc-a/base",
        )

        response = await self._get(
            session,
            _tasks_mock(task=_task_payload(), history=[_history_page([1])]),
            regular_user,
        )

        item = response.json()["items"][0]
        assert item["backup_source"] == "s3://bucket/svc-a/base"
        assert item["backup_type"] == "X"
        assert item["hostname"] == "db01"

    @pytest.mark.asyncio
    async def test_unusable_source_nulls_the_field_but_keeps_the_run(
        self, session, regular_user
    ) -> None:
        """List a run whose source the restore form rejects, with a null source.

        Dropping the row would hide a backup that exists; offering the value
        would seed a restore that 422s on submit.
        """
        await _save_run(session, task_history_id=1, location="/data/mydumper/`whoami`")

        response = await self._get(
            session,
            _tasks_mock(task=_task_payload(), history=[_history_page([1])]),
            regular_user,
        )

        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["backup_source"] is None

    @pytest.mark.asyncio
    async def test_known_task_without_runs_returns_an_empty_page(
        self, session, regular_user
    ) -> None:
        """Answer 200 with no items for a task that has never produced a backup.

        Conflating this with an unknown task would leave a caller unable to tell a
        typo'd task name from one whose first run has not happened yet.
        """
        response = await self._get(
            session,
            _tasks_mock(task=_task_payload(), history=[_history_page([])]),
            regular_user,
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["items"] == []
        assert body["total"] == 0

    @pytest.mark.asyncio
    async def test_unknown_task_returns_404(self, session, regular_user) -> None:
        """Surface an unknown task name as 404, not as an empty catalog."""
        response = await self._get(
            session,
            _tasks_mock(task_raises=HTTPNotFoundException(detail="nope")),
            regular_user,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_task_owned_by_another_app_returns_404(
        self, session, regular_user
    ) -> None:
        """Refuse to serve a task another app owns, as the derived routes do."""
        response = await self._get(
            session,
            _tasks_mock(task=_task_payload(owner="RESTORES")),
            regular_user,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_serves_runs_whose_service_no_longer_resolves(
        self, session, regular_user
    ) -> None:
        """Serve catalogued runs without consulting the Inventory API at all.

        The task-keyed path never resolves a service, so a run whose service was
        deleted stays readable — and two same-named services cannot be confused.
        """
        await _save_run(session, task_history_id=1, service_id=404)
        inventory = inventory_mock(raises=HTTPNotFoundException(detail="gone"))

        response = await self._get(
            session,
            _tasks_mock(task=_task_payload(), history=[_history_page([1])]),
            regular_user,
            inventory=inventory,
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 1
        inventory.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_task_with_no_catalogued_type_returns_an_empty_page(
        self, session, regular_user
    ) -> None:
        """Answer with an empty page for a task whose runs are never catalogued.

        A binlog task produces successful histories but no catalog rows, so the
        history walk finds ids that match nothing.
        """
        response = await self._get(
            session,
            _tasks_mock(task=_task_payload(), history=[_history_page([1, 2, 3])]),
            regular_user,
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["items"] == []

    @pytest.mark.asyncio
    async def test_serves_a_run_catalogued_before_this_route_existed(
        self, session, regular_user
    ) -> None:
        """Serve a row carrying only the columns the recorder has always written.

        No column was added for this route, so a run catalogued earlier is
        reachable on exactly the terms a new one is.
        """
        await _save_run(
            session, task_history_id=1, location="/data/mydumper/svc-a/legacy"
        )

        response = await self._get(
            session,
            _tasks_mock(task=_task_payload(), history=[_history_page([1])]),
            regular_user,
        )

        item = response.json()["items"][0]
        assert item["service_id"] is None
        assert item["backup_source"] == "/data/mydumper/svc-a/legacy"

    @pytest.mark.asyncio
    async def test_bounds_the_history_walk(self, session, regular_user) -> None:
        """Stop walking history at the scan cap, whatever the task's run count."""
        full_page = _history_page(range(MAX_PAGINATION_LIMIT), total=10_000)
        tasks = _tasks_mock(task=_task_payload(), history=[full_page] * 5)

        response = await self._get(session, tasks, regular_user)

        assert response.status_code == status.HTTP_200_OK
        history_calls = [
            call for call in tasks.get.await_args_list if _is_history_call(call)
        ]
        lookup_calls = [
            call for call in tasks.get.await_args_list if not _is_history_call(call)
        ]
        assert len(lookup_calls) == 1
        assert len(history_calls) <= _MAX_HISTORY_PAGES
        assert (
            sum(call.kwargs["params"]["limit"] for call in history_calls)
            == MAX_TASK_RUN_SCAN
        )

    @pytest.mark.asyncio
    async def test_run_outside_the_window_stays_reachable_per_service(
        self, session, regular_user
    ) -> None:
        """Keep a run the capped walk did not reach listed by the per-service route.

        The cap limits how far one request reaches, never how long a run stays
        readable, so the exhaustive route must still return what this one omits.
        """
        await _save_run(session, task_history_id=1, location="/data/mydumper/recent")
        await _save_run(session, task_history_id=999, location="/data/mydumper/older")

        task_scoped = await self._get(
            session,
            _tasks_mock(task=_task_payload(), history=[_history_page([1])]),
            regular_user,
        )
        per_service = await authenticated_get(
            _URL.format(service_id=1),
            session=session,
            inventory=inventory_mock(service_payload("svc-a")),
            user=regular_user,
        )

        assert [item["location"] for item in task_scoped.json()["items"]] == [
            "/data/mydumper/recent"
        ]
        assert {item["location"] for item in per_service.json()["items"]} == {
            "/data/mydumper/recent",
            "/data/mydumper/older",
        }

    @pytest.mark.asyncio
    async def test_malformed_upstream_envelope_returns_502(
        self, session, regular_user
    ) -> None:
        """Fail loudly when the Tasks API answers with something that is not a page.

        Coercing it would report a broken Tasks service as a task that has never
        produced a backup — the one answer a caller must not act on.
        """
        response = await self._get(
            session,
            _tasks_mock(task=_task_payload(), history=[["not", "a", "page"]]),
            regular_user,
        )

        assert response.status_code == status.HTTP_502_BAD_GATEWAY

    @pytest.mark.asyncio
    async def test_null_items_envelope_returns_502(self, session, regular_user) -> None:
        """Refuse a page whose items are null rather than reporting no backups.

        The envelope is a JSON object, so a shape check that stops there would
        serve a confident empty catalog for a task that may have hundreds of runs.
        """
        response = await self._get(
            session,
            _tasks_mock(task=_task_payload(), history=[{"items": None, "total": 9}]),
            regular_user,
        )

        assert response.status_code == status.HTTP_502_BAD_GATEWAY

    @pytest.mark.asyncio
    async def test_requests_the_history_ordering_it_depends_on(
        self, session, regular_user
    ) -> None:
        """Ask upstream for newest-first, since that decides which runs are scanned."""
        tasks = _tasks_mock(task=_task_payload(), history=[_history_page([1])])

        await self._get(session, tasks, regular_user)

        history_calls = [
            call for call in tasks.get.await_args_list if _is_history_call(call)
        ]
        assert history_calls
        assert all(
            call.kwargs["params"]["sort"] == "-created_at" for call in history_calls
        )

    @pytest.mark.asyncio
    async def test_upstream_failure_propagates(self, session, regular_user) -> None:
        """Propagate a Tasks API failure rather than reporting an empty catalog."""
        response = await self._get(
            session,
            _tasks_mock(
                task=_task_payload(),
                history_raises=HTTPBadGatewayException(detail="tasks is down"),
            ),
            regular_user,
        )

        assert response.status_code == status.HTTP_502_BAD_GATEWAY

    @pytest.mark.asyncio
    async def test_skips_history_rows_without_a_usable_id(
        self, session, regular_user
    ) -> None:
        """Ignore a mis-shaped history row instead of failing the whole page."""
        await _save_run(session, task_history_id=1)
        page = _history_page([1])
        page["items"].extend([{"id": None}, {}])

        response = await self._get(
            session,
            _tasks_mock(task=_task_payload(), history=[page]),
            regular_user,
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 1

    def test_requires_authentication(self, unauthenticated_client) -> None:
        """Reject an unauthenticated caller."""
        response = unauthenticated_client.get(_TASK_URL.format(task_name=_TASK_NAME))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestServiceBackupsRoute:
    """GET /api/apps/mysql_backups/services/{service_id}/backups."""

    async def _get(
        self,
        session: AsyncSession,
        service_id: int,
        inventory: AsyncMock,
        regular_user: object,
    ) -> Response:
        """Drive the route with the given session + inventory mock, authenticated."""
        return await authenticated_get(
            _URL.format(service_id=service_id),
            session=session,
            inventory=inventory,
            user=regular_user,
        )

    @pytest.mark.asyncio
    async def test_returns_records_newest_first(self, session, regular_user) -> None:
        """Return a service's records newest first."""
        for i in range(3):
            await MysqlBackupRunManager.save(
                session,
                MysqlBackupRun(
                    task_history_id=i + 1,
                    service_name="svc-a",
                    backup_type="X",
                    location=f"/data/xtrabackup/svc-a/{i}",
                    size_bytes=i,
                ),
            )

        response = await self._get(
            session, 1, inventory_mock(service_payload("svc-a")), regular_user
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == 3  # noqa: PLR2004
        assert [r["location"] for r in body["items"]] == [
            "/data/xtrabackup/svc-a/2",
            "/data/xtrabackup/svc-a/1",
            "/data/xtrabackup/svc-a/0",
        ]
        assert body["items"][0]["backup_type"] == "X"

    @pytest.mark.asyncio
    async def test_items_carry_the_restore_ready_source(
        self, session, regular_user
    ) -> None:
        """Serve the resolved source here too — one response model, one resolution."""
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(
                task_history_id=1,
                service_name="svc-a",
                backup_type="M",
                location="/data/mydumper/svc-a/0",
                upload_destination="s3://bucket/svc-a/0",
            ),
        )

        response = await self._get(
            session, 1, inventory_mock(service_payload("svc-a")), regular_user
        )

        assert response.json()["items"][0]["backup_source"] == "s3://bucket/svc-a/0"

    @pytest.mark.asyncio
    async def test_excludes_other_services(self, session, regular_user) -> None:
        """Return only the requested service's records."""
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(task_history_id=1, service_name="svc-a", backup_type="M"),
        )
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(task_history_id=2, service_name="svc-b", backup_type="M"),
        )

        response = await self._get(
            session, 1, inventory_mock(service_payload("svc-a")), regular_user
        )

        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["service_name"] == "svc-a"

    @pytest.mark.asyncio
    async def test_retired_service_still_lists_its_runs(
        self, session, regular_user
    ) -> None:
        """Resolve a retired service, so a backup history survives its retirement."""
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(task_history_id=1, service_name="svc-gone", backup_type="M"),
        )
        inventory = inventory_mock(
            service_payload("svc-gone") | {"retired_at": "2026-08-01T00:00:00Z"}
        )

        response = await self._get(session, 1, inventory, regular_user)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 1
        inventory.get.assert_awaited_once_with(
            "/services/1", params={"include_retired": "true"}
        )

    @pytest.mark.asyncio
    async def test_existing_service_no_records_returns_empty(
        self, session, regular_user
    ) -> None:
        """Return an empty page for a resolvable service with no recorded runs."""
        response = await self._get(
            session, 1, inventory_mock(service_payload("svc-empty")), regular_user
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == 0
        assert body["items"] == []

    @pytest.mark.asyncio
    async def test_unknown_service_propagates_404(self, session, regular_user) -> None:
        """Surface an unknown service id as ``404`` — a real error, not an empty page.

        Only a *resolvable* service with no recorded runs yields an empty page;
        conflating the two would hide a bad service id from the caller.
        """
        response = await self._get(
            session,
            999,
            inventory_mock(raises=HTTPNotFoundException(detail="nope")),
            regular_user,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_non_mysql_service_returns_404(self, session, regular_user) -> None:
        """Surface a resolvable non-MySQL service as ``404``, not an empty page.

        The catalog query filters on ``service_name`` alone, so serving a
        wrong-type service would let a same-named non-MySQL service leak
        another service's rows.
        """
        response = await self._get(
            session,
            1,
            inventory_mock(
                service_payload("svc-a", service_type=ServiceTypeEnum.POSTGRESQL)
            ),
            regular_user,
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_requires_authentication(self, unauthenticated_client) -> None:
        """Reject an unauthenticated caller."""
        response = unauthenticated_client.get(_URL.format(service_id=1))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_renamed_service_still_returns_its_backups(
        self, session, regular_user
    ) -> None:
        """Keep a recorded run reachable after its service was renamed.

        The row was written when the service was called ``old-name``; inventory
        now resolves the same id to ``new-name``. Keying on the name alone lost the
        row and answered with the same empty page a service with no backups gives.
        """
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(
                task_history_id=1,
                service_name="old-name",
                service_id=1,
                backup_type="M",
                location="/data/mydumper/old-name/0",
            ),
        )

        response = await self._get(
            session, 1, inventory_mock(service_payload("new-name")), regular_user
        )

        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["location"] == "/data/mydumper/old-name/0"
        assert body["items"][0]["service_id"] == 1

    @pytest.mark.asyncio
    async def test_row_without_service_id_still_returned_by_name(
        self, session, regular_user
    ) -> None:
        """Serve a row predating the id through the name it was written with."""
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(task_history_id=1, service_name="svc-a", backup_type="M"),
        )

        response = await self._get(
            session, 1, inventory_mock(service_payload("svc-a")), regular_user
        )

        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["service_id"] is None

    @pytest.mark.asyncio
    async def test_same_named_services_do_not_leak_each_others_runs(
        self, session, regular_user
    ) -> None:
        """Isolate two MySQL services that share a name once ids are recorded.

        ``Service.name`` carries no uniqueness constraint, so keying on the name
        returned both services' runs under either id.
        """
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(
                task_history_id=1,
                service_name="shared",
                service_id=1,
                backup_type="M",
            ),
        )
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(
                task_history_id=2,
                service_name="shared",
                service_id=2,
                backup_type="M",
            ),
        )

        response = await self._get(
            session, 1, inventory_mock(service_payload("shared")), regular_user
        )

        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["service_id"] == 1
