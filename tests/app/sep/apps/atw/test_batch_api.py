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
from app.sep.snippets.masking import SENSITIVE_ARG_MASK
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
_SEEDED_MD5 = "a" * 32


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
        "app.sep.snippets.script_source.get_async_session_maker",
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
        snippet = Snippet(filename=filename, size=20, md5_digest=_SEEDED_MD5)
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
    async def test_whole_selection_resolves_in_one_snippet_lookup(
        self,
        api_client: TestClient,
        create_snippet: Callable[..., Awaitable[Snippet]],
        mocker: MockerFixture,
    ) -> None:
        """Resolve the whole selection with one batch lookup, not one per snippet."""
        await create_snippet("a.sh", parameters=[_DEFAULTS_FILE_PARAM])
        await create_snippet("b.sh", parameters=[_DEFAULTS_FILE_PARAM])
        await create_snippet("c.sh", parameters=[_DEFAULTS_FILE_PARAM])
        batch = mocker.spy(SnippetManager, "list")
        single = mocker.spy(SnippetManager, "get_or_404")

        response = api_client.get(
            SCHEMA_URL, params={"snippet_filename": ["a.sh", "b.sh", "c.sh"]}
        )

        assert response.status_code == status.HTTP_200_OK
        assert batch.call_count == 1
        assert single.call_count == 0

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
    async def test_whole_batch_resolves_in_one_snippet_lookup(
        self,
        api_client: TestClient,
        create_snippet: Callable[..., Awaitable[Snippet]],
        incident: AtwIncident,
        tasks_api: AsyncMock,
        mocker: MockerFixture,
    ) -> None:
        """Resolve every item's snippet with one batch lookup before the dispatch loop."""
        await create_snippet("a.sh", parameters=[])
        await create_snippet("b.sh", parameters=[])
        tasks_api.post.side_effect = [{"id": _FIRST_TASK_ID}, {"id": _SECOND_TASK_ID}]
        batch = mocker.spy(SnippetManager, "list")
        single = mocker.spy(SnippetManager, "get_or_404")

        response = api_client.post(
            executions_url(incident.id),
            json={
                "executor_host": "host1",
                "items": [{"snippet_filename": "a.sh"}, {"snippet_filename": "b.sh"}],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert batch.call_count == 1
        assert single.call_count == 0

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
    async def test_traversal_filename_fails_the_whole_batch(
        self,
        api_client: TestClient,
        create_snippet: Callable[..., Awaitable[Snippet]],
        incident: AtwIncident,
        tasks_api: AsyncMock,
    ) -> None:
        """Reject the whole batch with 400 when any item names an unsafe filename.

        A traversal string is malformed input, not an unknown snippet: the seam's
        guard runs before any lookup, so it fails the request rather than
        degrading to a per-item error, and nothing dispatches.
        """
        await create_snippet("a.sh", parameters=[])

        response = api_client.post(
            executions_url(incident.id),
            json={
                "executor_host": "host1",
                "items": [
                    {"snippet_filename": "../secret.sh"},
                    {"snippet_filename": "a.sh"},
                ],
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        tasks_api.post.assert_not_awaited()

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


class TestAtwIncidentExecutionMaskedArgs:
    """Check the recorded arguments GET .../executions/ reports for each row.

    Snippet resolution is deliberately left unstubbed so the real
    ``resolve_snippets`` -> ``get_execution_model`` -> ``mask_snippet_args`` chain
    runs end to end through the routing and DI stack.
    """

    @pytest_asyncio.fixture
    async def seed_execution(
        self, session: AsyncSession, incident: AtwIncident
    ) -> Callable[..., Awaitable[AtwIncidentExecution]]:
        """Return an async factory recording one execution against the incident."""

        async def _factory(
            filename: str, *, task_history_id: int = _FIRST_TASK_ID
        ) -> AtwIncidentExecution:
            return await AtwIncidentExecutionManager.save(
                session,
                AtwIncidentExecution(
                    incident_id=incident.id,
                    task_history_id=task_history_id,
                    snippet_filename=filename,
                ),
            )

        return _factory

    @staticmethod
    def _history(
        args: str | None, *, md5_checksum: str = _SEEDED_MD5
    ) -> dict[str, Any]:
        """Return an upstream task-history payload carrying ``args``.

        The digest is recorded alongside the arguments at execution time, and
        masking compares it against the snippet's current one, so it has to be
        present for a row to resolve.

        :param args: The recorded argument string, or ``None`` to record none.
        :param md5_checksum: The snippet digest recorded with the execution;
            override it to simulate a snippet edited since the run.
        :return: The payload shape the history endpoint returns.
        """
        meta = {"md5_checksum": md5_checksum}
        if args is not None:
            meta["args"] = args
        return {
            "status": TaskHistoryStatusEnum.SUCCESS.value,
            "has_logs": True,
            "execution_request": {"meta": meta},
        }

    @staticmethod
    def _rows_by_task_id(response: Any) -> dict[int, dict[str, Any]]:
        """Return the page's rows keyed by task-history id.

        ``utc_now`` zeroes microseconds, so two rows seeded in one test share a
        ``created_at`` and the newest-first sort between them is a tie the DB
        breaks arbitrarily. Keying off the id keeps a multi-row assertion from
        depending on which side of that tie the page landed.

        :param response: The executions-list response.
        :return: A mapping of each row's ``task_history_id`` to the row.
        """
        return {item["task_history_id"]: item for item in response.json()["items"]}

    @pytest.mark.asyncio
    async def test_masked_args_are_returned(
        self,
        api_client: TestClient,
        incident: AtwIncident,
        tasks_api: AsyncMock,
        create_snippet: Callable[..., Awaitable[Snippet]],
        seed_execution: Callable[..., Awaitable[AtwIncidentExecution]],
    ) -> None:
        """Mask a credential-named parameter's value and never emit the raw secret."""
        secret = "hunter2SuperSecret"
        await create_snippet(
            "mongo-check.sh",
            parameters=[
                {"name": "port", "type": "int", "required": True},
                {"name": "password", "type": "str", "required": True},
            ],
        )
        await seed_execution("mongo-check.sh")
        tasks_api.get.return_value = self._history(f"--port 27017 --password {secret}")

        response = api_client.get(executions_url(incident.id))

        assert response.status_code == status.HTTP_200_OK
        item = response.json()["items"][0]
        assert item["args_withheld"] is False
        assert item["masked_args"] == f"--port 27017 --password {SENSITIVE_ARG_MASK}"
        assert secret not in response.text

    @pytest.mark.asyncio
    async def test_credential_uri_password_is_masked(
        self,
        api_client: TestClient,
        incident: AtwIncident,
        tasks_api: AsyncMock,
        create_snippet: Callable[..., Awaitable[Snippet]],
        seed_execution: Callable[..., Awaitable[AtwIncidentExecution]],
    ) -> None:
        """Mask a password embedded in a URI whose name matches no credential word."""
        await create_snippet(
            "pbm-diagnostics.sh",
            parameters=[{"name": "mongodb-uri", "type": "str", "required": True}],
        )
        await seed_execution("pbm-diagnostics.sh")
        tasks_api.get.return_value = self._history(
            "--mongodb-uri mongodb://USER:PASSWORD@localhost:27017/?authSource=admin"
        )

        response = api_client.get(executions_url(incident.id))

        assert response.status_code == status.HTTP_200_OK
        masked = response.json()["items"][0]["masked_args"]
        assert SENSITIVE_ARG_MASK in masked
        assert "USER" in masked
        assert "localhost:27017" in masked
        assert "PASSWORD" not in response.text

    @pytest.mark.asyncio
    async def test_args_withheld_when_snippet_unresolvable(
        self,
        api_client: TestClient,
        incident: AtwIncident,
        tasks_api: AsyncMock,
        seed_execution: Callable[..., Awaitable[AtwIncidentExecution]],
    ) -> None:
        """Withhold a row whose snippet no longer resolves, so nothing is unmasked."""
        await seed_execution("deleted-since.sh")
        tasks_api.get.return_value = self._history("--password s3cr3t")

        response = api_client.get(executions_url(incident.id))

        assert response.status_code == status.HTTP_200_OK
        item = response.json()["items"][0]
        assert item["masked_args"] is None
        assert item["args_withheld"] is True
        assert "s3cr3t" not in response.text

    @pytest.mark.asyncio
    async def test_execution_without_arguments_reports_the_empty_state(
        self,
        api_client: TestClient,
        incident: AtwIncident,
        tasks_api: AsyncMock,
        create_snippet: Callable[..., Awaitable[Snippet]],
        seed_execution: Callable[..., Awaitable[AtwIncidentExecution]],
    ) -> None:
        """Report no arguments distinctly from withholding them."""
        await create_snippet("no-params.sh", parameters=[])
        await seed_execution("no-params.sh")
        tasks_api.get.return_value = self._history(None)

        response = api_client.get(executions_url(incident.id))

        item = response.json()["items"][0]
        assert item["masked_args"] is None
        assert item["args_withheld"] is False

    @pytest.mark.asyncio
    async def test_hydration_failure_withholds_that_row_only(
        self,
        api_client: TestClient,
        incident: AtwIncident,
        tasks_api: AsyncMock,
        create_snippet: Callable[..., Awaitable[Snippet]],
        seed_execution: Callable[..., Awaitable[AtwIncidentExecution]],
    ) -> None:
        """Withhold a row whose upstream lookup failed while its sibling resolves."""
        await create_snippet(
            "mongo-check.sh",
            parameters=[{"name": "password", "type": "str", "required": True}],
        )
        await seed_execution("mongo-check.sh", task_history_id=_FIRST_TASK_ID)
        await seed_execution("mongo-check.sh", task_history_id=_SECOND_TASK_ID)

        def history_or_upstream_failure(path: str) -> dict[str, Any]:
            if path.endswith(f"/{_FIRST_TASK_ID}"):
                raise HTTPBadRequestException(detail="upstream gone")
            return self._history("--password s3cr3t")

        tasks_api.get.side_effect = history_or_upstream_failure

        response = api_client.get(executions_url(incident.id))

        assert response.status_code == status.HTTP_200_OK
        rows = self._rows_by_task_id(response)
        assert rows[_FIRST_TASK_ID]["masked_args"] is None
        assert rows[_FIRST_TASK_ID]["args_withheld"] is True
        assert rows[_SECOND_TASK_ID]["masked_args"] == (
            f"--password {SENSITIVE_ARG_MASK}"
        )
        assert "s3cr3t" not in response.text

    @pytest.mark.asyncio
    async def test_unresolvable_snippet_does_not_fail_the_page(
        self,
        api_client: TestClient,
        incident: AtwIncident,
        tasks_api: AsyncMock,
        create_snippet: Callable[..., Awaitable[Snippet]],
        seed_execution: Callable[..., Awaitable[AtwIncidentExecution]],
    ) -> None:
        """Keep the page alive when only some of its snippets still resolve."""
        await create_snippet(
            "mongo-check.sh",
            parameters=[{"name": "password", "type": "str", "required": True}],
        )
        await seed_execution("mongo-check.sh", task_history_id=_FIRST_TASK_ID)
        await seed_execution("deleted-since.sh", task_history_id=_SECOND_TASK_ID)
        tasks_api.get.return_value = self._history("--password s3cr3t")

        response = api_client.get(executions_url(incident.id))

        assert response.status_code == status.HTTP_200_OK
        rows = self._rows_by_task_id(response)
        assert rows[_FIRST_TASK_ID]["masked_args"] == f"--password {SENSITIVE_ARG_MASK}"
        assert rows[_SECOND_TASK_ID]["args_withheld"] is True
        assert "s3cr3t" not in response.text

    @pytest.mark.asyncio
    async def test_snippet_edited_since_the_run_withholds_that_row(
        self,
        api_client: TestClient,
        incident: AtwIncident,
        tasks_api: AsyncMock,
        create_snippet: Callable[..., Awaitable[Snippet]],
        seed_execution: Callable[..., Awaitable[AtwIncidentExecution]],
    ) -> None:
        """Withhold a row whose snippet changed after the execution was recorded.

        Masking reads the snippet's *current* frontmatter, so an edit that dropped
        or de-sensitised a parameter would leave its recorded value unrecognised
        and rendered in the clear. A digest that no longer matches is the signal
        that the metadata may not describe this recording.
        """
        await create_snippet(
            "edited-since.sh",
            parameters=[{"name": "blob", "type": "str", "required": True}],
        )
        await seed_execution("edited-since.sh")
        tasks_api.get.return_value = self._history(
            "--blob s3cr3t", md5_checksum="b" * 32
        )

        response = api_client.get(executions_url(incident.id))

        assert response.status_code == status.HTTP_200_OK
        item = response.json()["items"][0]
        assert item["masked_args"] is None
        assert item["args_withheld"] is True
        assert "s3cr3t" not in response.text

    @pytest.mark.asyncio
    async def test_execution_without_a_recorded_digest_withholds_that_row(
        self,
        api_client: TestClient,
        incident: AtwIncident,
        tasks_api: AsyncMock,
        create_snippet: Callable[..., Awaitable[Snippet]],
        seed_execution: Callable[..., Awaitable[AtwIncidentExecution]],
    ) -> None:
        """Withhold a row whose payload carries no digest to compare against."""
        await create_snippet(
            "no-digest.sh",
            parameters=[{"name": "password", "type": "str", "required": True}],
        )
        await seed_execution("no-digest.sh")
        history = self._history("--password s3cr3t")
        del history["execution_request"]["meta"]["md5_checksum"]
        tasks_api.get.return_value = history

        response = api_client.get(executions_url(incident.id))

        assert response.status_code == status.HTTP_200_OK
        item = response.json()["items"][0]
        assert item["masked_args"] is None
        assert item["args_withheld"] is True
        assert "s3cr3t" not in response.text

    @pytest.mark.asyncio
    async def test_unusable_snippet_metadata_withholds_that_row(
        self,
        api_client: TestClient,
        incident: AtwIncident,
        tasks_api: AsyncMock,
        create_snippet: Callable[..., Awaitable[Snippet]],
        seed_execution: Callable[..., Awaitable[AtwIncidentExecution]],
    ) -> None:
        """Withhold a row whose stored ``arg_format`` cannot be tokenised."""
        await create_snippet(
            "stale-meta.sh",
            parameters=[
                {
                    "name": "password",
                    "type": "str",
                    "required": True,
                    "arg_format": "--password '${value}",
                }
            ],
        )
        await seed_execution("stale-meta.sh")
        tasks_api.get.return_value = self._history("--password s3cr3t")

        response = api_client.get(executions_url(incident.id))

        assert response.status_code == status.HTTP_200_OK
        item = response.json()["items"][0]
        assert item["masked_args"] is None
        assert item["args_withheld"] is True
        assert "s3cr3t" not in response.text

    @pytest.mark.asyncio
    async def test_every_snippet_unresolvable_still_returns_the_page(
        self,
        api_client: TestClient,
        incident: AtwIncident,
        tasks_api: AsyncMock,
        seed_execution: Callable[..., Awaitable[AtwIncidentExecution]],
    ) -> None:
        """Return 200 with every row withheld when no filename on the page resolves."""
        await seed_execution("gone-a.sh", task_history_id=_FIRST_TASK_ID)
        await seed_execution("gone-b.sh", task_history_id=_SECOND_TASK_ID)
        tasks_api.get.return_value = self._history("--password s3cr3t")

        response = api_client.get(executions_url(incident.id))

        assert response.status_code == status.HTTP_200_OK
        rows = self._rows_by_task_id(response)
        assert [row["args_withheld"] for row in rows.values()] == [True, True]
        assert "s3cr3t" not in response.text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "history",
        [
            pytest.param(
                {"execution_request": "--password s3cr3t"},
                id="execution-request-is-not-a-mapping",
            ),
            pytest.param(
                {"execution_request": {"meta": ["--password s3cr3t"]}},
                id="meta-is-not-a-mapping",
            ),
        ],
    )
    async def test_non_mapping_upstream_payload_withholds_that_row(
        self,
        api_client: TestClient,
        incident: AtwIncident,
        tasks_api: AsyncMock,
        create_snippet: Callable[..., Awaitable[Snippet]],
        seed_execution: Callable[..., Awaitable[AtwIncidentExecution]],
        history: dict[str, Any],
    ) -> None:
        """Withhold a row whose payload nests something other than a mapping.

        The tasks service's response body is not validated on this side, so reading
        ``args`` off a truthy non-mapping would raise past the masking guard and
        fail the whole page rather than degrading this row.
        """
        await create_snippet(
            "bad-shape.sh",
            parameters=[{"name": "password", "type": "str", "required": True}],
        )
        await seed_execution("bad-shape.sh")
        tasks_api.get.return_value = {
            "status": TaskHistoryStatusEnum.SUCCESS.value,
            "has_logs": True,
            **history,
        }

        response = api_client.get(executions_url(incident.id))

        assert response.status_code == status.HTTP_200_OK
        item = response.json()["items"][0]
        assert item["masked_args"] is None
        assert item["args_withheld"] is True
        assert "s3cr3t" not in response.text


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
            "app.sep.snippets.script_source.get_async_session_maker",
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
