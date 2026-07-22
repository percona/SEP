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

"""Cover the ATW batch-execution surface under /api/apps/atw/.

Covers the merged execution schema, the incident-scoped batch execute, and the
incident-scoped execution history. All three consume the snippets
``ScriptSource`` seam, whose ``load_script`` opens its own request-less session,
so the suite points ``script_source.get_async_session_maker`` at the in-memory
test session (mirroring ``tests/app/sep/apps/snippets/conftest.py``).
"""

from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import status
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from pytest_mock import MockerFixture
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import URL

from app.core.auth.providers.casdoor.models import CasdoorUser
from app.core.exceptions import HTTPBadRequestException
from app.core.requests import RemoteAPI
from app.sep.apps.atw.crud import AtwIncidentExecutionManager, AtwIncidentManager
from app.sep.apps.atw.models import AtwIncident, AtwIncidentExecution
from app.sep.deps import (
    get_api_authenticated_user,
    get_current_user,
    get_session,
    get_tasks_api,
    require_bearer_for_unsafe_methods,
    validate_csrf,
)
from app.sep.main import sep_app
from app.sep.snippets.config import snippets_settings, SnippetSudoOption
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.models import Snippet
from app.tasks.models import TaskHistoryStatusEnum

SCHEMA_URL = "/api/apps/atw/execution-schema/"
INCIDENTS_BASE = "/api/apps/atw/incidents/"

_DEFAULTS_FILE_PARAM = {
    "name": "defaults-file",
    "type": "str",
    "label": "Defaults file",
    "description": "Path to the MySQL defaults file.",
}
_MINUTES_PARAM = {"name": "minutes", "type": "int", "label": "Minutes"}

_DEFAULT_TASK_ID = 7
_FIRST_TASK_ID = 11
_SECOND_TASK_ID = 12
_DUPLICATE_TASK_IDS = (21, 22)
_SEEDED_TASK_IDS = (101, 102)
_SEEDED_EXECUTION_COUNT = len(_SEEDED_TASK_IDS)


def executions_url(incident_id: object) -> str:
    """Return the incident-scoped executions URL for an incident id."""
    return f"{INCIDENTS_BASE}{incident_id}/executions/"


@pytest.fixture(autouse=True)
def request_less_session(session: AsyncSession, mocker: MockerFixture) -> AsyncSession:
    """Bind the snippets request-less session maker to the test session.

    The ATW batch endpoints resolve snippets through ``snippet_source.load_script``,
    which opens its own session via ``get_async_session_maker`` rather than the
    request-scoped ``get_session`` the client fixtures override.
    """
    maker = MagicMock()
    maker.return_value.__aenter__ = AsyncMock(return_value=session)
    maker.return_value.__aexit__ = AsyncMock(return_value=False)
    mocker.patch(
        "app.sep.apps.snippets.script_source.get_async_session_maker",
        return_value=maker,
    )
    return session


@pytest.fixture(autouse=True)
def snippets_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure a base URL so the request-less execute path can sign artifact URLs."""
    monkeypatch.setattr(
        snippets_settings, "SNIPPETS_BASE_URL", URL("http://testserver")
    )


@pytest.fixture
def snippets_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect :attr:`Snippet.BASE_DIR` to a temporary directory for the test."""
    monkeypatch.setattr(Snippet, "BASE_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def create_snippet(
    session: AsyncSession, snippets_dir: Path
) -> Callable[..., Awaitable[Snippet]]:
    """Return an async factory seeding a Snippet row, its file, and its meta."""

    async def _factory(
        filename: str,
        *,
        parameters: list[dict[str, Any]] | None = None,
        approved: bool = True,
        sudo: SnippetSudoOption | None = None,
    ) -> Snippet:
        target = snippets_dir / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("#!/bin/sh\necho hi\n")
        snippet = Snippet(filename=filename, size=20, md5_digest="a" * 32)
        meta = dict(snippet.meta)
        if parameters is not None:
            meta["parameters"] = parameters
        if sudo is not None:
            meta["sudo"] = sudo.value
        snippet.meta = meta
        snippet.__dict__.pop("validated_parameters", None)
        if approved:
            snippet.approve("Seeded as approved", "seed-user")
        return await SnippetManager.create(session, snippet)

    return _factory


@pytest.fixture
def tasks_api() -> Iterator[AsyncMock]:
    """Replace the Tasks API dependency with a spec'd async mock."""
    mock = AsyncMock(spec=RemoteAPI)
    mock.post.return_value = {"id": _DEFAULT_TASK_ID}
    sep_app.dependency_overrides[get_tasks_api] = lambda: mock
    yield mock
    sep_app.dependency_overrides.pop(get_tasks_api, None)


@pytest_asyncio.fixture
async def incident(session: AsyncSession) -> AtwIncident:
    """Seed one incident to scope batch executions and history against."""
    return await AtwIncidentManager.save(
        session, AtwIncident(created_by="alice", name="Batch incident")
    )


def field_names(fields: list[dict[str, Any]]) -> list[str]:
    """Return the ``name`` of every field in a serialised field list."""
    return [field["name"] for field in fields]


def per_snippet_fields(payload: dict[str, Any], filename: str) -> list[dict[str, Any]]:
    """Return the per-snippet field list for one filename in a schema payload."""
    entry = next(
        item for item in payload["per_snippet"] if item["snippet_filename"] == filename
    )
    return entry["fields"]


class TestAtwExecutionSchema:
    """Check GET /api/apps/atw/execution-schema/."""

    @pytest.mark.asyncio
    async def test_identical_parameter_is_merged_into_shared(
        self, api_client: TestClient, create_snippet: Callable[..., Awaitable[Snippet]]
    ) -> None:
        """Merge a byte-identical parameter declared by both snippets into ``shared``."""
        await create_snippet("a.sh", parameters=[_DEFAULTS_FILE_PARAM])
        await create_snippet("b.sh", parameters=[_DEFAULTS_FILE_PARAM])

        response = api_client.get(
            SCHEMA_URL, params={"snippet_filename": ["a.sh", "b.sh"]}
        )

        assert response.status_code == status.HTTP_200_OK
        payload = response.json()
        assert "defaults-file" in field_names(payload["shared"])
        assert per_snippet_fields(payload, "a.sh") == []
        assert per_snippet_fields(payload, "b.sh") == []

    @pytest.mark.asyncio
    async def test_shared_fields_carry_the_wire_type_key(
        self, api_client: TestClient, create_snippet: Callable[..., Awaitable[Snippet]]
    ) -> None:
        """Serialise the field discriminator under its ``type`` alias, not ``field_type``."""
        await create_snippet("a.sh", parameters=[_DEFAULTS_FILE_PARAM])
        await create_snippet("b.sh", parameters=[_DEFAULTS_FILE_PARAM])

        response = api_client.get(
            SCHEMA_URL, params={"snippet_filename": ["a.sh", "b.sh"]}
        )

        payload = response.json()
        assert all("type" in field for field in payload["shared"])
        assert not any("field_type" in field for field in payload["shared"])

    @pytest.mark.asyncio
    async def test_execution_host_is_always_shared(
        self, api_client: TestClient, create_snippet: Callable[..., Awaitable[Snippet]]
    ) -> None:
        """Prepend the batch-level executor-host field to ``shared`` for any selection."""
        await create_snippet("a.sh", parameters=[_DEFAULTS_FILE_PARAM])

        response = api_client.get(SCHEMA_URL, params={"snippet_filename": ["a.sh"]})

        payload = response.json()
        assert field_names(payload["shared"])[0] == "executor_host"

    @pytest.mark.asyncio
    async def test_single_snippet_keeps_parameters_per_snippet(
        self, api_client: TestClient, create_snippet: Callable[..., Awaitable[Snippet]]
    ) -> None:
        """Keep every parameter per-snippet when only one snippet is selected."""
        await create_snippet("a.sh", parameters=[_DEFAULTS_FILE_PARAM])

        response = api_client.get(SCHEMA_URL, params={"snippet_filename": ["a.sh"]})

        payload = response.json()
        assert field_names(per_snippet_fields(payload, "a.sh")) == ["defaults-file"]
        assert "defaults-file" not in field_names(payload["shared"])

    @pytest.mark.asyncio
    async def test_divergent_declarations_stay_per_snippet(
        self, api_client: TestClient, create_snippet: Callable[..., Awaitable[Snippet]]
    ) -> None:
        """Keep a same-named parameter per-snippet when the declarations differ."""
        await create_snippet("a.sh", parameters=[{**_MINUTES_PARAM, "required": True}])
        await create_snippet("b.sh", parameters=[{**_MINUTES_PARAM, "default": 5}])

        response = api_client.get(
            SCHEMA_URL, params={"snippet_filename": ["a.sh", "b.sh"]}
        )

        payload = response.json()
        assert "minutes" not in field_names(payload["shared"])
        assert field_names(per_snippet_fields(payload, "a.sh")) == ["minutes"]
        assert field_names(per_snippet_fields(payload, "b.sh")) == ["minutes"]

    @pytest.mark.asyncio
    async def test_duplicate_filenames_are_deduped_order_preserving(
        self, api_client: TestClient, create_snippet: Callable[..., Awaitable[Snippet]]
    ) -> None:
        """Resolve each requested filename once, preserving first-appearance order."""
        await create_snippet("a.sh", parameters=[_DEFAULTS_FILE_PARAM])
        await create_snippet("b.sh", parameters=[_DEFAULTS_FILE_PARAM])

        response = api_client.get(
            SCHEMA_URL, params={"snippet_filename": ["b.sh", "a.sh", "b.sh"]}
        )

        payload = response.json()
        assert [item["snippet_filename"] for item in payload["per_snippet"]] == [
            "b.sh",
            "a.sh",
        ]

    @pytest.mark.asyncio
    async def test_a_duplicated_single_snippet_does_not_self_merge(
        self, api_client: TestClient, create_snippet: Callable[..., Awaitable[Snippet]]
    ) -> None:
        """Reject self-merging: one snippet repeated is still a single declarer."""
        await create_snippet("a.sh", parameters=[_DEFAULTS_FILE_PARAM])

        response = api_client.get(
            SCHEMA_URL, params={"snippet_filename": ["a.sh", "a.sh"]}
        )

        payload = response.json()
        assert "defaults-file" not in field_names(payload["shared"])
        assert field_names(per_snippet_fields(payload, "a.sh")) == ["defaults-file"]

    @pytest.mark.asyncio
    async def test_snippet_without_parameters_yields_empty_field_list(
        self, api_client: TestClient, create_snippet: Callable[..., Awaitable[Snippet]]
    ) -> None:
        """Strip every synthetic field so a parameterless snippet reports no fields."""
        await create_snippet("dmesg.sh", parameters=[])

        response = api_client.get(SCHEMA_URL, params={"snippet_filename": ["dmesg.sh"]})

        payload = response.json()
        assert per_snippet_fields(payload, "dmesg.sh") == []

    @pytest.mark.asyncio
    async def test_optional_sudo_adds_a_shared_sudo_field(
        self, api_client: TestClient, create_snippet: Callable[..., Awaitable[Snippet]]
    ) -> None:
        """Add the batch-level sudo toggle when a selected snippet allows it."""
        await create_snippet("sudo.sh", parameters=[], sudo=SnippetSudoOption.OPTIONAL)

        response = api_client.get(SCHEMA_URL, params={"snippet_filename": ["sudo.sh"]})

        assert "sudo" in field_names(response.json()["shared"])

    @pytest.mark.asyncio
    async def test_sudo_default_true_snippet_starts_checked(
        self, api_client: TestClient, create_snippet: Callable[..., Awaitable[Snippet]]
    ) -> None:
        """Keep a sudo-default-on snippet checked, as its own form would render it."""
        await create_snippet(
            "sudo.sh", parameters=[], sudo=SnippetSudoOption.OPTIONAL_DEFAULT_TRUE
        )

        response = api_client.get(SCHEMA_URL, params={"snippet_filename": ["sudo.sh"]})

        sudo_field = next(
            field for field in response.json()["shared"] if field["name"] == "sudo"
        )
        assert sudo_field["default"] is True

    @pytest.mark.asyncio
    async def test_mixed_sudo_defaults_start_unchecked(
        self, api_client: TestClient, create_snippet: Callable[..., Awaitable[Snippet]]
    ) -> None:
        """Start the shared toggle unchecked when the selection disagrees on sudo."""
        await create_snippet(
            "on.sh", parameters=[], sudo=SnippetSudoOption.OPTIONAL_DEFAULT_TRUE
        )
        await create_snippet("off.sh", parameters=[], sudo=SnippetSudoOption.OPTIONAL)

        response = api_client.get(
            SCHEMA_URL, params={"snippet_filename": ["on.sh", "off.sh"]}
        )

        sudo_field = next(
            field for field in response.json()["shared"] if field["name"] == "sudo"
        )
        assert sudo_field["default"] is False

    @pytest.mark.asyncio
    async def test_no_optional_sudo_omits_the_shared_sudo_field(
        self, api_client: TestClient, create_snippet: Callable[..., Awaitable[Snippet]]
    ) -> None:
        """Omit the sudo toggle when no selected snippet has optional sudo."""
        await create_snippet("a.sh", parameters=[])

        response = api_client.get(SCHEMA_URL, params={"snippet_filename": ["a.sh"]})

        assert "sudo" not in field_names(response.json()["shared"])

    def test_missing_filename_is_rejected(self, api_client: TestClient) -> None:
        """Reject a request that selects no snippet at all."""
        response = api_client.get(SCHEMA_URL)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @pytest.mark.usefixtures("snippets_dir")
    def test_unknown_filename_fails_the_whole_request(
        self, api_client: TestClient
    ) -> None:
        """Return 404 for the whole request when one selected snippet is unknown."""
        response = api_client.get(SCHEMA_URL, params={"snippet_filename": ["gone.sh"]})

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.usefixtures("snippets_dir")
    def test_traversal_filename_is_rejected(self, api_client: TestClient) -> None:
        """Return 400 when a selected filename attempts directory traversal."""
        response = api_client.get(
            SCHEMA_URL, params={"snippet_filename": ["../etc/passwd"]}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestAtwBatchExecute:
    """Check POST /api/apps/atw/incidents/{incident_id}/executions/."""

    @pytest.mark.asyncio
    async def test_all_items_dispatch_and_are_recorded(
        self,
        api_client: TestClient,
        create_snippet: Callable[..., Awaitable[Snippet]],
        incident: AtwIncident,
        tasks_api: AsyncMock,
        session: AsyncSession,
    ) -> None:
        """Dispatch every item and persist one execution row per created task."""
        await create_snippet("a.sh", parameters=[])
        await create_snippet("b.sh", parameters=[])
        tasks_api.post.side_effect = [{"id": _FIRST_TASK_ID}, {"id": _SECOND_TASK_ID}]

        response = api_client.post(
            executions_url(incident.id),
            json={
                "executor_host": "host1",
                "items": [{"snippet_filename": "a.sh"}, {"snippet_filename": "b.sh"}],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        items = response.json()["items"]
        assert [item["task_history_id"] for item in items] == [
            _FIRST_TASK_ID,
            _SECOND_TASK_ID,
        ]
        assert all(item["error"] is None for item in items)
        rows = await AtwIncidentExecutionManager.list(session, incident_id=incident.id)
        assert sorted(row.task_history_id for row in rows) == [
            _FIRST_TASK_ID,
            _SECOND_TASK_ID,
        ]

    @pytest.mark.asyncio
    async def test_shared_args_are_filtered_to_declared_parameters(
        self,
        api_client: TestClient,
        create_snippet: Callable[..., Awaitable[Snippet]],
        incident: AtwIncident,
        tasks_api: AsyncMock,
    ) -> None:
        """Drop shared args a snippet does not declare instead of failing its item."""
        await create_snippet("a.sh", parameters=[_DEFAULTS_FILE_PARAM])

        response = api_client.post(
            executions_url(incident.id),
            json={
                "executor_host": "host1",
                "shared_args": {"defaults-file": "/etc/my.cnf", "unrelated": "x"},
                "items": [{"snippet_filename": "a.sh"}],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["items"][0]["error"] is None
        meta = tasks_api.post.await_args.kwargs["json"]["meta"]
        assert "/etc/my.cnf" in meta["args"]

    @pytest.mark.asyncio
    async def test_item_args_override_shared_args(
        self,
        api_client: TestClient,
        create_snippet: Callable[..., Awaitable[Snippet]],
        incident: AtwIncident,
        tasks_api: AsyncMock,
    ) -> None:
        """Prefer a per-item argument over the same shared argument."""
        await create_snippet("a.sh", parameters=[_DEFAULTS_FILE_PARAM])

        api_client.post(
            executions_url(incident.id),
            json={
                "executor_host": "host1",
                "shared_args": {"defaults-file": "/shared.cnf"},
                "items": [
                    {
                        "snippet_filename": "a.sh",
                        "args": {"defaults-file": "/item.cnf"},
                    }
                ],
            },
        )

        meta = tasks_api.post.await_args.kwargs["json"]["meta"]
        assert "/item.cnf" in meta["args"]
        assert "/shared.cnf" not in meta["args"]

    @pytest.mark.asyncio
    async def test_unknown_snippet_fails_only_its_item(
        self,
        api_client: TestClient,
        create_snippet: Callable[..., Awaitable[Snippet]],
        incident: AtwIncident,
        tasks_api: AsyncMock,
        session: AsyncSession,
    ) -> None:
        """Fail only the item naming an unknown filename; the rest still dispatch."""
        await create_snippet("a.sh", parameters=[])
        incident_id = incident.id

        response = api_client.post(
            executions_url(incident_id),
            json={
                "executor_host": "host1",
                "items": [
                    {"snippet_filename": "gone.sh"},
                    {"snippet_filename": "a.sh"},
                ],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        failed, succeeded = response.json()["items"]
        assert failed["error"] is not None
        assert failed["task_history_id"] is None
        assert succeeded["task_history_id"] == _DEFAULT_TASK_ID
        rows = await AtwIncidentExecutionManager.list(session, incident_id=incident_id)
        assert [row.snippet_filename for row in rows] == ["a.sh"]

    @pytest.mark.asyncio
    async def test_validation_failure_fails_only_its_item(
        self,
        api_client: TestClient,
        create_snippet: Callable[..., Awaitable[Snippet]],
        incident: AtwIncident,
        tasks_api: AsyncMock,
    ) -> None:
        """Fail only the item whose arguments do not validate, and keep dispatching."""
        await create_snippet("typed.sh", parameters=[_MINUTES_PARAM])
        await create_snippet("a.sh", parameters=[])

        response = api_client.post(
            executions_url(incident.id),
            json={
                "executor_host": "host1",
                "items": [
                    {"snippet_filename": "typed.sh", "args": {"minutes": "abc"}},
                    {"snippet_filename": "a.sh"},
                ],
            },
        )

        failed, succeeded = response.json()["items"]
        assert failed["error"] is not None
        assert succeeded["task_history_id"] == _DEFAULT_TASK_ID

    @pytest.mark.asyncio
    async def test_unapproved_snippet_fails_only_its_item(
        self,
        api_client: TestClient,
        create_snippet: Callable[..., Awaitable[Snippet]],
        incident: AtwIncident,
        tasks_api: AsyncMock,
    ) -> None:
        """Fail only the unapproved item rather than the whole batch."""
        await create_snippet("unapproved.sh", parameters=[], approved=False)
        await create_snippet("a.sh", parameters=[])

        response = api_client.post(
            executions_url(incident.id),
            json={
                "executor_host": "host1",
                "items": [
                    {"snippet_filename": "unapproved.sh"},
                    {"snippet_filename": "a.sh"},
                ],
            },
        )

        failed, succeeded = response.json()["items"]
        assert "not approved" in str(failed["error"])
        assert succeeded["task_history_id"] == _DEFAULT_TASK_ID

    @pytest.mark.asyncio
    async def test_dispatch_failure_fails_only_its_item(
        self,
        api_client: TestClient,
        create_snippet: Callable[..., Awaitable[Snippet]],
        incident: AtwIncident,
        tasks_api: AsyncMock,
        session: AsyncSession,
    ) -> None:
        """Fail only the item whose dispatch errors, and write no row for it."""
        await create_snippet("a.sh", parameters=[])
        await create_snippet("b.sh", parameters=[])
        tasks_api.post.side_effect = [
            OSError("connection refused"),
            {"id": _SECOND_TASK_ID},
        ]
        incident_id = incident.id

        response = api_client.post(
            executions_url(incident_id),
            json={
                "executor_host": "host1",
                "items": [{"snippet_filename": "a.sh"}, {"snippet_filename": "b.sh"}],
            },
        )

        failed, succeeded = response.json()["items"]
        assert failed["error"] is not None
        assert succeeded["task_history_id"] == _SECOND_TASK_ID
        rows = await AtwIncidentExecutionManager.list(session, incident_id=incident_id)
        assert [row.task_history_id for row in rows] == [_SECOND_TASK_ID]

    @pytest.mark.asyncio
    async def test_dispatch_without_task_id_is_reported_unrecorded(
        self,
        api_client: TestClient,
        create_snippet: Callable[..., Awaitable[Snippet]],
        incident: AtwIncident,
        tasks_api: AsyncMock,
        session: AsyncSession,
    ) -> None:
        """Flag a dispatch the upstream gave no task id for, and write no row."""
        await create_snippet("a.sh", parameters=[])
        tasks_api.post.return_value = {}

        response = api_client.post(
            executions_url(incident.id),
            json={"executor_host": "host1", "items": [{"snippet_filename": "a.sh"}]},
        )

        item = response.json()["items"][0]
        assert item["task_history_id"] is None
        assert item["task_name"]
        assert item["error"] is not None
        rows = await AtwIncidentExecutionManager.list(session, incident_id=incident.id)
        assert rows == []

    @pytest.mark.asyncio
    async def test_row_write_failure_rolls_back_and_later_items_succeed(
        self,
        api_client: TestClient,
        create_snippet: Callable[..., Awaitable[Snippet]],
        incident: AtwIncident,
        tasks_api: AsyncMock,
        session: AsyncSession,
        mocker: MockerFixture,
    ) -> None:
        """Roll back a failed row write so the next item still records its execution."""
        await create_snippet("a.sh", parameters=[])
        await create_snippet("b.sh", parameters=[])
        tasks_api.post.side_effect = [{"id": _FIRST_TASK_ID}, {"id": _SECOND_TASK_ID}]
        original_save = AtwIncidentExecutionManager.save
        attempts = []

        async def _flaky_save(
            db_session: AsyncSession, instance: AtwIncidentExecution, **kwargs: Any
        ) -> AtwIncidentExecution:
            attempts.append(instance)
            if len(attempts) == 1:
                raise HTTPBadRequestException(detail="write failed")
            return await original_save(db_session, instance, **kwargs)

        mocker.patch.object(AtwIncidentExecutionManager, "save", new=_flaky_save)

        response = api_client.post(
            executions_url(incident.id),
            json={
                "executor_host": "host1",
                "items": [{"snippet_filename": "a.sh"}, {"snippet_filename": "b.sh"}],
            },
        )

        failed, succeeded = response.json()["items"]
        assert failed["task_history_id"] == _FIRST_TASK_ID
        assert failed["error"] is not None
        assert succeeded["task_history_id"] == _SECOND_TASK_ID
        assert succeeded["error"] is None

    @pytest.mark.asyncio
    async def test_duplicate_items_dispatch_separately(
        self,
        api_client: TestClient,
        create_snippet: Callable[..., Awaitable[Snippet]],
        incident: AtwIncident,
        tasks_api: AsyncMock,
        session: AsyncSession,
    ) -> None:
        """Dispatch a repeated snippet once per item, recording both task ids."""
        await create_snippet("a.sh", parameters=[])
        tasks_api.post.side_effect = [
            {"id": task_id} for task_id in _DUPLICATE_TASK_IDS
        ]

        response = api_client.post(
            executions_url(incident.id),
            json={
                "executor_host": "host1",
                "items": [{"snippet_filename": "a.sh"}, {"snippet_filename": "a.sh"}],
            },
        )

        items = response.json()["items"]
        assert [item["task_history_id"] for item in items] == list(_DUPLICATE_TASK_IDS)
        rows = await AtwIncidentExecutionManager.list(session, incident_id=incident.id)
        assert len(rows) == len(_DUPLICATE_TASK_IDS)

    def test_empty_items_is_rejected(
        self, api_client: TestClient, incident: AtwIncident
    ) -> None:
        """Reject a batch that carries no items."""
        response = api_client.post(
            executions_url(incident.id),
            json={"executor_host": "host1", "items": []},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_unknown_incident_is_rejected_before_dispatch(
        self, api_client: TestClient, tasks_api: AsyncMock
    ) -> None:
        """Return 404 for an unknown incident without dispatching anything."""
        response = api_client.post(
            executions_url(uuid4()),
            json={"executor_host": "host1", "items": [{"snippet_filename": "a.sh"}]},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        tasks_api.post.assert_not_awaited()


class TestAtwListIncidentExecutions:
    """Check GET /api/apps/atw/incidents/{incident_id}/executions/."""

    @pytest_asyncio.fixture
    async def executions(
        self, session: AsyncSession, incident: AtwIncident
    ) -> list[AtwIncidentExecution]:
        """Seed two execution rows against the incident."""
        return [
            await AtwIncidentExecutionManager.save(
                session,
                AtwIncidentExecution(
                    incident_id=incident.id,
                    task_history_id=task_history_id,
                    snippet_filename=f"diag-{task_history_id}.sh",
                ),
            )
            for task_history_id in _SEEDED_TASK_IDS
        ]

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("executions")
    async def test_rows_are_hydrated_with_upstream_status(
        self,
        api_client: TestClient,
        incident: AtwIncident,
        tasks_api: AsyncMock,
    ) -> None:
        """Merge the upstream task-history status and timestamps into each row."""
        tasks_api.get.return_value = {
            "status": TaskHistoryStatusEnum.SUCCESS.value,
            "started_at": "2026-07-21T10:00:00Z",
            "finished_at": "2026-07-21T10:01:00Z",
            "has_logs": True,
        }

        response = api_client.get(executions_url(incident.id))

        assert response.status_code == status.HTTP_200_OK
        payload = response.json()
        assert payload["total"] == _SEEDED_EXECUTION_COUNT
        item = payload["items"][0]
        assert item["task_status"] == TaskHistoryStatusEnum.SUCCESS.value
        assert item["has_logs"] is True
        assert item["started_at"] is not None

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("executions")
    async def test_hydration_failure_degrades_that_row_only(
        self,
        api_client: TestClient,
        incident: AtwIncident,
        tasks_api: AsyncMock,
    ) -> None:
        """Return null status for a row whose upstream lookup fails, keeping the page."""
        tasks_api.get.side_effect = [
            HTTPBadRequestException(detail="upstream gone"),
            {"status": TaskHistoryStatusEnum.RUNNING.value, "has_logs": False},
        ]

        response = api_client.get(executions_url(incident.id))

        assert response.status_code == status.HTTP_200_OK
        degraded, hydrated = response.json()["items"]
        assert degraded["task_status"] is None
        assert degraded["has_logs"] is None
        assert degraded["task_history_id"] is not None
        assert hydrated["task_status"] == TaskHistoryStatusEnum.RUNNING.value

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("executions")
    async def test_connection_failure_degrades_that_row_only(
        self,
        api_client: TestClient,
        incident: AtwIncident,
        tasks_api: AsyncMock,
    ) -> None:
        """Return null status for a row whose upstream call raises a transport error."""
        tasks_api.get.side_effect = [
            OSError("connection refused"),
            {"status": TaskHistoryStatusEnum.PENDING.value},
        ]

        response = api_client.get(executions_url(incident.id))

        degraded, hydrated = response.json()["items"]
        assert degraded["task_status"] is None
        assert hydrated["task_status"] == TaskHistoryStatusEnum.PENDING.value

    @pytest.mark.asyncio
    async def test_incident_without_executions_returns_empty_page(
        self, api_client: TestClient, incident: AtwIncident, tasks_api: AsyncMock
    ) -> None:
        """Return an empty page without calling the Tasks API at all."""
        response = api_client.get(executions_url(incident.id))

        assert response.status_code == status.HTTP_200_OK
        payload = response.json()
        assert payload["items"] == []
        assert payload["total"] == 0
        tasks_api.get.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("executions")
    async def test_pagination_window_narrows_the_page(
        self,
        api_client: TestClient,
        incident: AtwIncident,
        tasks_api: AsyncMock,
    ) -> None:
        """Narrow the page to the offset/limit window and hydrate only that slice."""
        tasks_api.get.return_value = {"status": TaskHistoryStatusEnum.SUCCESS.value}

        response = api_client.get(
            executions_url(incident.id), params={"limit": 1, "offset": 1}
        )

        payload = response.json()
        assert payload["total"] == _SEEDED_EXECUTION_COUNT
        assert len(payload["items"]) == 1
        assert payload["offset"] == 1
        assert tasks_api.get.await_count == 1

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("executions")
    async def test_page_beyond_range_is_empty_with_correct_total(
        self, api_client: TestClient, incident: AtwIncident, tasks_api: AsyncMock
    ) -> None:
        """Return an empty item list but the true total past the last page."""
        response = api_client.get(
            executions_url(incident.id), params={"limit": 5, "offset": 50}
        )

        payload = response.json()
        assert payload["items"] == []
        assert payload["total"] == _SEEDED_EXECUTION_COUNT

    def test_unknown_incident_returns_404(self, api_client: TestClient) -> None:
        """Return 404 when the incident does not exist."""
        response = api_client.get(executions_url(uuid4()))

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestAtwBatchExecuteOnRealPostgres:
    """Guard the batch loop's shared-session rollback against a real aborted transaction."""

    @pytest.mark.postgres
    @pytest.mark.asyncio
    async def test_row_write_failure_does_not_poison_the_next_item(
        self,
        postgres_session: AsyncSession,
        snippets_dir: Path,
        regular_user: CasdoorUser,
        tasks_api: AsyncMock,
        mocker: MockerFixture,
    ) -> None:
        """Record the second item after the first item's row write aborts the transaction.

        Real-PostgreSQL sibling of
        ``test_row_write_failure_rolls_back_and_later_items_succeed``. SQLite keeps
        a transaction usable after a failed statement, so only PostgreSQL proves
        the per-item ``session.rollback()`` is load-bearing: the first item's
        insert violates the incident foreign key, aborting the transaction, and
        without the rollback every later statement on the shared session raises
        instead of recording the surviving item.
        """
        for filename in ("a.sh", "b.sh"):
            target = snippets_dir / filename
            target.write_text("#!/bin/sh\necho hi\n")
            snippet = Snippet(filename=filename, size=20, md5_digest="a" * 32)
            snippet.approve("Seeded as approved", "seed-user")
            await SnippetManager.create(postgres_session, snippet)
        incident = await AtwIncidentManager.save(
            postgres_session, AtwIncident(created_by="alice", name="pg batch")
        )
        incident_id = incident.id

        maker = MagicMock()
        maker.return_value.__aenter__ = AsyncMock(return_value=postgres_session)
        maker.return_value.__aexit__ = AsyncMock(return_value=False)
        mocker.patch(
            "app.sep.apps.snippets.script_source.get_async_session_maker",
            return_value=maker,
        )
        tasks_api.post.side_effect = [
            {"id": _FIRST_TASK_ID},
            {"id": _SECOND_TASK_ID},
        ]

        original_save = AtwIncidentExecutionManager.save
        attempts = []

        async def _flaky_save(
            db_session: AsyncSession, instance: AtwIncidentExecution, **kwargs: Any
        ) -> AtwIncidentExecution:
            attempts.append(instance)
            if len(attempts) == 1:
                instance.incident_id = uuid4()
            return await original_save(db_session, instance, **kwargs)

        mocker.patch.object(AtwIncidentExecutionManager, "save", new=_flaky_save)

        sep_app.dependency_overrides[validate_csrf] = lambda: True
        sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
        sep_app.dependency_overrides[get_current_user] = lambda: regular_user
        sep_app.dependency_overrides[get_api_authenticated_user] = lambda: regular_user
        sep_app.dependency_overrides[get_session] = lambda: postgres_session
        client = AsyncClient(
            transport=ASGITransport(app=sep_app), base_url="http://test"
        )
        try:
            response = await client.post(
                executions_url(incident_id),
                json={
                    "executor_host": "host1",
                    "items": [
                        {"snippet_filename": "a.sh"},
                        {"snippet_filename": "b.sh"},
                    ],
                },
            )
        finally:
            await client.aclose()
            sep_app.dependency_overrides = {}

        assert response.status_code == status.HTTP_201_CREATED
        failed, succeeded = response.json()["items"]
        assert failed["error"] is not None
        assert succeeded["task_history_id"] == _SECOND_TASK_ID
        assert succeeded["error"] is None
        rows = await AtwIncidentExecutionManager.list(
            postgres_session, incident_id=incident_id
        )
        assert [row.task_history_id for row in rows] == [_SECOND_TASK_ID]
