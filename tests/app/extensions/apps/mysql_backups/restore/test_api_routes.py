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

"""Tests for the MySQL Restores JSON API routes under /api/apps/mysql_backups/restore/."""

from typing import Any
from unittest.mock import AsyncMock

from fastapi import HTTPException, status

from app.core.auth.providers.casdoor.models import CasdoorUser
from app.extensions.apps.mysql_backups.restore.models import OWNER
from app.tasks.models import TaskBackendEnum
from tests.app.factories import MOCK_CREATOR_ID, TaskFactory

API_BASE = "/api/apps/mysql_backups/restore"
_TASK_NAME = "restore-task"


def build_restore_task(**overrides: Any) -> dict[str, Any]:
    """Build a MySQL restore task payload shaped like the Tasks API response."""
    task = TaskFactory.build(
        name=_TASK_NAME,
        owner=OWNER,
        backend=TaskBackendEnum.PROXY,
        data={"task": "run-python", "meta": {"target": "executor-1", "config": ""}},
        **overrides,
    )
    return task.model_dump(mode="json")


def serve_single_restore(tasks_api: AsyncMock, task: dict[str, Any]) -> None:
    """Serve ``task`` as the only restore on the list and detail upstream calls.

    :param tasks_api: The Tasks-API mock installed on the production mount.
    :param task: The restore task payload to serve.
    """

    async def _get(path: str, **_: Any) -> dict[str, Any]:
        if path == "/":
            return {"items": [task], "total": 1, "offset": 0, "limit": 50}
        if path == f"/{_TASK_NAME}":
            return task
        if path == f"/{_TASK_NAME}/history/":
            return {"items": []}
        raise AssertionError(f"Unexpected tasks_api.get path: {path!r}")

    tasks_api.get = AsyncMock(side_effect=_get)
    tasks_api.post = AsyncMock(return_value={})


class TestRestoreApiActors:
    """Cover how the Restores list and detail render their actor fields."""

    def test_list_resolves_actor_usernames(
        self,
        test_client,
        mock_task_api_dep,
        known_actors: tuple[CasdoorUser, CasdoorUser],
    ) -> None:
        """Render both actors' usernames on the Restores list rows."""
        creator, updater = known_actors
        serve_single_restore(
            mock_task_api_dep,
            build_restore_task(
                created_by=str(creator.id), last_updated_by=str(updater.id)
            ),
        )

        response = test_client.get(f"{API_BASE}/")

        assert response.status_code == status.HTTP_200_OK
        row = response.json()["items"][0]
        assert (row["created_by"], row["last_updated_by"]) == (
            creator.username,
            updater.username,
        )

    def test_detail_resolves_actor_usernames(
        self,
        test_client,
        mock_task_api_dep,
        known_actors: tuple[CasdoorUser, CasdoorUser],
    ) -> None:
        """Render both actors' usernames on the Restores detail response."""
        creator, updater = known_actors
        serve_single_restore(
            mock_task_api_dep,
            build_restore_task(
                created_by=str(creator.id), last_updated_by=str(updater.id)
            ),
        )

        response = test_client.get(f"{API_BASE}/{_TASK_NAME}")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert (body["created_by"], body["last_updated_by"]) == (
            creator.username,
            updater.username,
        )

    def test_list_keeps_raw_ids_when_the_provider_fails(
        self, test_client, mock_task_api_dep, provider_users: AsyncMock
    ) -> None:
        """Serve the list with the stored ids when the provider lookup fails."""
        provider_users.side_effect = HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="provider unreachable"
        )
        serve_single_restore(
            mock_task_api_dep, build_restore_task(created_by=MOCK_CREATOR_ID)
        )

        response = test_client.get(f"{API_BASE}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["items"][0]["created_by"] == MOCK_CREATOR_ID
