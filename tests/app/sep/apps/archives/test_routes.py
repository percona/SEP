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

"""Define tests for the app.sep.apps.archives.routes module."""

import re
from datetime import datetime, timedelta, UTC
from unittest.mock import AsyncMock

import pytest
import yaml
from fastapi import status

from app.core.pagination import MAX_PAGINATION_LIMIT
from app.core.requests import RemoteAPI
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.archives.constants import SwapDropEnum
from app.sep.apps.archives.deps import (
    build_archives_task_payload,
    get_archives_index_context,
    get_archives_task,
)
from app.sep.connectivity import (
    clear_connectivity_caches,
    get_latest_connectivity_result,
)
from app.sep.deps import get_inventory_api
from app.sep.main import sep_app
from app.tasks.models import (
    TaskBackendEnum,
    TaskHistoryStatusEnum,
)
from tests.app.factories import GeneratedTaskFactory, TaskFactory


@pytest.fixture
def mock_inventory_api_dep(mock_remote_api: RemoteAPI) -> AsyncMock:
    """Mock the InventoryAPI dependency."""
    mock = AsyncMock(spec=RemoteAPI)
    sep_app.dependency_overrides[get_inventory_api] = lambda: mock
    yield mock
    sep_app.dependency_overrides = {}


@pytest.fixture
def created_archives() -> dict:
    """Return flat legacy-form data for the Jinja create route (Purge Only)."""
    return {
        "alias": "purge_only",
        "hostname": "source_db",
        "service_id": 1,
        "source_db_id": 10,
        "source_table_id": 20,
        "swap_drop": SwapDropEnum.PURGE_ONLY.value,
        "where": "id > 1",
        "delete_data": 1,
    }


@pytest.fixture
def _mock_archives_task_payload(generated_task):
    """Mock the TaskDep dependency."""
    sep_app.dependency_overrides[build_archives_task_payload] = lambda: generated_task
    yield
    sep_app.dependency_overrides = {}


@pytest.fixture
def created_task():
    """Return a fake created Task instance."""
    return TaskFactory.build(owner="ARCHIVER")


@pytest.fixture
def _mock_get_archives_task_dep(created_task):
    """Mock the TaskDep dependency."""
    sep_app.dependency_overrides[get_archives_task] = lambda: created_task
    yield
    sep_app.dependency_overrides = {}


@pytest.fixture
def _mock_get_archives_index_context_dep():
    """Mock the get_archives_index_context dependency with default user context."""
    sep_app.dependency_overrides[get_archives_index_context] = lambda: {
        "user": "default_user",
        "connectivity_check_default": True,
        # An executor host is required for the index to render the create form,
        # which exercises the dest_file markup guard asserted below.
        "executor_hosts": [{"value": "host1", "label": "host1"}],
        "services": [],
    }
    yield
    sep_app.dependency_overrides = {}


@pytest.mark.usefixtures("_mock_get_archives_index_context_dep")
def test_archives_index(
    test_client,
):
    """Test listing archives tasks."""
    response = test_client.get("/archives/")
    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.headers.get("deprecation") == "true"
    # Render guard only: name="dest_file" is always in the server HTML; the
    # inline JS strips it at runtime, which this does not exercise.
    assert 'name="dest_file"' in response.text


@pytest.mark.usefixtures("_mock_archives_task_payload")
def test_archives_create(
    test_client,
    mock_task_api_dep,
    created_archives,
    generated_task,
):
    """Test creating a new archives task."""
    response = test_client.post(
        "/archives/", data=created_archives, follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert (
        response.headers["location"]
        == f"{test_client.base_url}/archives/{generated_task.name}"
    )
    mock_task_api_dep.post.assert_any_await(
        "/",
        json=generated_task.model_dump(),
    )


def test_archives_create_full_form_dependency_chain_without_payload_override(
    test_client,
    mock_task_api_dep,
    mock_inventory_api_dep,
    created_service,
    created_schema,
    created_table,
):
    """Test POST /archives/ route without overriding build_archives_task_payload."""
    flat = {
        "alias": "arch_full_chain",
        "hostname": "source_db",
        "service_id": created_service.id,
        "source_db_id": created_schema.id,
        "source_table_id": created_table.id,
        "swap_drop": SwapDropEnum.PURGE_ONLY.value,
        "where": "id > 1",
        "delete_data": 1,
    }
    mock_inventory_api_dep.get = AsyncMock(
        side_effect=[
            created_service.model_dump(),
            created_schema.model_dump(),
            created_table.model_dump(),
        ]
    )
    mock_task_api_dep.post.return_value = AsyncMock()

    response = test_client.post("/archives/", data=flat, follow_redirects=False)
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"].endswith("/archives/arch_full_chain")
    mock_task_api_dep.post.assert_awaited_once()
    assert mock_task_api_dep.post.await_args.args[0] == "/"
    posted = mock_task_api_dep.post.await_args.kwargs["json"]
    assert posted["name"] == "arch_full_chain"
    assert posted["owner"] == "ARCHIVER"
    assert posted["data"]["meta"]["_service_name"] == created_service.name


class TestArchivesUpdateFormChain:
    """Exercise the real ``Form()`` dependency chain on POST /archives/{task_name}/update."""

    def test_full_form_dependency_chain_without_payload_override(
        self,
        test_client,
        mock_task_api_dep,
        mock_inventory_api_dep,
        created_service,
        created_schema,
        created_table,
    ):
        """Forward the submitted body to ``tasks_api.put`` through the real form chain."""
        task_name = "arch_update_full_chain"
        flat = {
            "alias": task_name,
            "hostname": "source_db",
            "service_id": created_service.id,
            "source_db_id": created_schema.id,
            "source_table_id": created_table.id,
            "swap_drop": SwapDropEnum.PURGE_ONLY.value,
            "where": "id > 1",
            "delete_data": 1,
        }
        mock_inventory_api_dep.get = AsyncMock(
            side_effect=[
                created_service.model_dump(),
                created_schema.model_dump(),
                created_table.model_dump(),
            ]
        )
        mock_task_api_dep.put.return_value = AsyncMock()

        response = test_client.post(
            f"/archives/{task_name}/update", data=flat, follow_redirects=False
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"].endswith(f"/archives/{task_name}")
        mock_task_api_dep.put.assert_awaited_once()
        assert mock_task_api_dep.put.await_args.args[0] == f"/{task_name}"
        put_payload = mock_task_api_dep.put.await_args.kwargs["json"]
        assert put_payload["name"] == task_name
        assert put_payload["owner"] == "ARCHIVER"
        assert put_payload["data"]["meta"]["_service_name"] == created_service.name
        # Submitted ``where`` clause must survive the real form chain into the payload.
        purge_config = yaml.safe_load(put_payload["data"]["meta"]["config"])
        assert purge_config["PURGE_LIST"][0]["WHERE"] == "id > 1"

    def test_forwards_path_name_but_redirects_to_form_name(
        self,
        test_client,
        mock_task_api_dep,
        mock_inventory_api_dep,
        created_service,
        created_schema,
        created_table,
    ):
        """Forward the path ``task_name`` to put while the form alias drives the redirect."""
        path_name = "arch_url_path"
        form_name = "arch_form_name"
        flat = {
            "alias": form_name,
            "hostname": "source_db",
            "service_id": created_service.id,
            "source_db_id": created_schema.id,
            "source_table_id": created_table.id,
            "swap_drop": SwapDropEnum.PURGE_ONLY.value,
            "where": "id > 1",
            "delete_data": 1,
        }
        mock_inventory_api_dep.get = AsyncMock(
            side_effect=[
                created_service.model_dump(),
                created_schema.model_dump(),
                created_table.model_dump(),
            ]
        )
        mock_task_api_dep.put.return_value = AsyncMock()

        response = test_client.post(
            f"/archives/{path_name}/update", data=flat, follow_redirects=False
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert mock_task_api_dep.put.await_args.args[0] == f"/{path_name}"
        assert mock_task_api_dep.put.await_args.kwargs["json"]["name"] == form_name
        assert response.headers["location"].endswith(f"/archives/{form_name}")

    def test_invalid_form_flashes_and_redirects_without_forwarding(
        self,
        test_client,
        mock_task_api_dep,
    ):
        """Flash and redirect (never forward) when the update form fails validation."""
        # ``where`` is required for a Purge Only run, so omitting it fails
        # ``ArchivesCreate`` validation before any inventory lookup or forward.
        data = {
            "alias": "arch_invalid",
            "hostname": "source_db",
            "service_id": 1,
            "source_db_id": 10,
            "source_table_id": 20,
            "swap_drop": SwapDropEnum.PURGE_ONLY.value,
            "delete_data": 1,
        }

        response = test_client.post(
            "/archives/arch_invalid/update", data=data, follow_redirects=False
        )
        assert response.status_code == status.HTTP_303_SEE_OTHER
        assert response.headers["location"] == "/"
        assert "messages=" in response.headers.get("set-cookie", "")
        mock_task_api_dep.put.assert_not_awaited()


def test_archives_create_accepts_empty_dest_port(
    test_client,
    mock_task_api_dep,
    mock_inventory_api_dep,
    created_service,
    created_schema,
    created_table,
):
    """POST /archives/ coerces empty-string optional ints to None.

    Goes through the real form-parsing chain (no ``build_archives_task_payload``
    override) so the ``EmptyStrToNone`` ``BeforeValidator`` is the only thing
    stopping the previous 422 response.
    """
    payload = {
        "alias": "arch_empty_port",
        "hostname": "source_db",
        "service_id": created_service.id,
        "source_db_id": created_schema.id,
        "source_table_id": created_table.id,
        "swap_drop": SwapDropEnum.PURGE_ONLY.value,
        "where": "id > 1",
        "delete_data": 1,
        "dest_port": "",
        "limit": "",
    }
    mock_inventory_api_dep.get = AsyncMock(
        side_effect=[
            created_service.model_dump(),
            created_schema.model_dump(),
            created_table.model_dump(),
        ]
    )
    mock_task_api_dep.post.return_value = AsyncMock()

    response = test_client.post("/archives/", data=payload, follow_redirects=False)
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"].endswith("/archives/arch_empty_port")
    mock_task_api_dep.post.assert_awaited_once()


def test_archives_update_accepts_empty_dest_port(
    test_client,
    mock_task_api_dep,
    mock_inventory_api_dep,
    created_service,
    created_schema,
    created_table,
):
    """POST /archives/{task_name}/update coerces empty-string optional ints to None.

    Same real-form-binding pattern as the create test — the update route shares
    the ``ArchivesGeneratedTask`` dep, so the empty-string fix has to cover it too.
    """
    payload = {
        "alias": "arch_update_empty_port",
        "hostname": "source_db",
        "service_id": created_service.id,
        "source_db_id": created_schema.id,
        "source_table_id": created_table.id,
        "swap_drop": SwapDropEnum.PURGE_ONLY.value,
        "where": "id > 1",
        "delete_data": 1,
        "dest_port": "",
        "limit": "",
    }
    mock_inventory_api_dep.get = AsyncMock(
        side_effect=[
            created_service.model_dump(),
            created_schema.model_dump(),
            created_table.model_dump(),
        ]
    )
    mock_task_api_dep.put.return_value = AsyncMock()

    response = test_client.post(
        "/archives/arch_update_empty_port/update",
        data=payload,
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"].endswith("/archives/arch_update_empty_port")
    mock_task_api_dep.put.assert_awaited_once()


def test_archives_create_same_as_source_with_manual_dest_schema(
    test_client,
    mock_task_api_dep,
    mock_inventory_api_dep,
    created_service,
    created_schema,
    created_table,
):
    """POST /archives/ with same-as-source host and a manual destination schema.

    With no ``dest_service_id`` and no ``dest_host`` but a typed ``dest_db_name``,
    the posted purge config must carry ``DEST_DB`` (archive to a different schema
    on the same host) and omit ``DEST_HOST`` entirely. Goes through the real
    form-binding chain (no ``build_archives_task_payload`` override).
    """
    flat = {
        "alias": "arch_same_host_manual_schema",
        "hostname": "source_db",
        "service_id": created_service.id,
        "source_db_id": created_schema.id,
        "source_table_id": created_table.id,
        "swap_drop": SwapDropEnum.PURGE_ONLY.value,
        "where": "id > 1",
        "dest_table_name": "archived_tbl",
        "dest_db_name": "archive_db",
    }
    mock_inventory_api_dep.get = AsyncMock(
        side_effect=[
            created_service.model_dump(),
            created_schema.model_dump(),
            created_table.model_dump(),
        ]
    )
    mock_task_api_dep.post.return_value = AsyncMock()

    response = test_client.post("/archives/", data=flat, follow_redirects=False)
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"].endswith(
        "/archives/arch_same_host_manual_schema"
    )
    mock_task_api_dep.post.assert_awaited_once()
    posted = mock_task_api_dep.post.await_args.kwargs["json"]
    purge_config = yaml.safe_load(posted["data"]["meta"]["config"])
    purge_item = purge_config["PURGE_LIST"][0]
    assert purge_item["DEST_DB"] == "archive_db"
    assert "DEST_HOST" not in purge_item


def test_archives_update_same_as_source_with_manual_dest_schema(
    test_client,
    mock_task_api_dep,
    mock_inventory_api_dep,
    created_service,
    created_schema,
    created_table,
):
    """POST /archives/{task_name}/update with same-as-source + manual dest schema.

    The update route shares the form-binding chain, so the same same-host
    manual-schema path has to reach ``DEST_DB`` (and omit ``DEST_HOST``) on the
    PUT payload too.
    """
    flat = {
        "alias": "arch_update_same_host_manual_schema",
        "hostname": "source_db",
        "service_id": created_service.id,
        "source_db_id": created_schema.id,
        "source_table_id": created_table.id,
        "swap_drop": SwapDropEnum.PURGE_ONLY.value,
        "where": "id > 1",
        "dest_table_name": "archived_tbl",
        "dest_db_name": "archive_db",
    }
    mock_inventory_api_dep.get = AsyncMock(
        side_effect=[
            created_service.model_dump(),
            created_schema.model_dump(),
            created_table.model_dump(),
        ]
    )
    mock_task_api_dep.put.return_value = AsyncMock()

    response = test_client.post(
        "/archives/arch_update_same_host_manual_schema/update",
        data=flat,
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"].endswith(
        "/archives/arch_update_same_host_manual_schema"
    )
    mock_task_api_dep.put.assert_awaited_once()
    put_payload = mock_task_api_dep.put.await_args.kwargs["json"]
    purge_config = yaml.safe_load(put_payload["data"]["meta"]["config"])
    purge_item = purge_config["PURGE_LIST"][0]
    assert purge_item["DEST_DB"] == "archive_db"
    assert "DEST_HOST" not in purge_item


def test_archives_update_rejects_non_purge_only_swap_drop(
    test_client,
    mock_task_api_dep,
    mock_inventory_api_dep,
):
    """Resubmitting a legacy SWAP_DROP task via the update route is rejected.

    Existing SWAP_DROP / SWAP_ARCHIVE_DROP tasks load read-only, but saving an
    edit re-validates through ``ArchivesCreate``; only Purge Only is accepted,
    so a crafted ``swap_drop=1`` form fails validation (422) regardless of the
    disabled UI.
    """
    # Posted as a raw form dict because ArchivesCreate refuses to construct a
    # non-Purge-Only payload in the first place.
    payload = {
        "alias": "legacy_swap_drop",
        "hostname": "source_db",
        "service_id": 1,
        "source_db_id": 10,
        "source_table_id": 20,
        "swap_drop": SwapDropEnum.SWAP_DROP.value,
    }

    # HTML form routes surface validation failures as a flash + redirect back to
    # the submitting page (the Referer), so set one and assert we return to it
    # rather than to the detail page.
    referer = "http://testserver/archives/legacy_swap_drop/edit"
    response = test_client.post(
        "/archives/legacy_swap_drop/update",
        data=payload,
        headers={"referer": referer},
        follow_redirects=False,
    )

    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == referer
    # The task is never updated when validation rejects the payload.
    mock_task_api_dep.put.assert_not_awaited()


def test_archives_create_skips_connectivity_check_when_opted_out(
    test_client, mock_task_api_dep, created_archives
):
    """POST /archives/ skips the connectivity check when the checkbox is unchecked."""
    clear_connectivity_caches()

    fake_task_write = GeneratedTaskFactory.build(
        name="fake_task",
        backend=TaskBackendEnum.PROXY,
        owner="ARCHIVER",
        data={
            "task": "fake-task",
            "meta": {
                "target": "node1",
                "_connectivity_host": "10.0.0.1",
                "_connectivity_port": 3306,
                "_connectivity_service_type": ServiceTypeEnum.MYSQL.value,
            },
            "payload": "",
        },
    )

    sep_app.dependency_overrides[build_archives_task_payload] = lambda: fake_task_write

    response = test_client.post(
        "/archives/", data=created_archives, follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert (
        response.headers["location"]
        == f"{test_client.base_url}/archives/{fake_task_write.name}"
    )

    assert mock_task_api_dep.post.call_count == 1
    call = mock_task_api_dep.post.call_args_list[0]
    assert call.args[0] == "/"
    assert call.kwargs["json"] == fake_task_write.model_dump()
    assert get_latest_connectivity_result("node1", "mysql") is None

    clear_connectivity_caches()
    sep_app.dependency_overrides = {}


@pytest.mark.parametrize(
    ("disable_bulk_insert", "checkbox_checked"),
    [
        (None, False),
        (1, True),
    ],
    ids=["bulk_insert_default", "bulk_insert_checked"],
)
@pytest.mark.usefixtures("_mock_get_archives_task_dep", "mock_get_username_mapping")
def test_archives_detail(
    test_client,
    created_task,
    mock_task_api_dep,
    mock_inventory_api_dep,
    disable_bulk_insert,
    checkbox_checked,
):
    """Test the archives detail page, including the DISABLE_BULK_INSERT checkbox state.

    The ``DISABLE_BULK_INSERT`` flag in the ``PURGE_LIST`` meta config drives whether the
    ``disable_bulk_insert`` checkbox renders as ``checked``.
    """
    purge_entry = {
        "ALIAS": "test_archiver_task",
        "SOURCE_DB": "mock_source_db",
        "SOURCE_TABLE": "mock_source_table",
        "SWAP_DROP": 1,
    }
    if disable_bulk_insert is not None:
        purge_entry["DISABLE_BULK_INSERT"] = disable_bulk_insert
    mock_meta_config = yaml.dump(
        {
            "ALL": {
                "SOURCE_HOST": "127.0.0.1",
                "SOURCE_PORT": 3306,
            },
            "PURGE_LIST": [purge_entry],
        }
    )

    mock_data = {
        "meta": {
            "config": mock_meta_config,
            "target": "mock_target",
        },
        "hostname": "mock_nomad_host_name",
    }
    created_task.data = mock_data
    mock_inventory_api_dep.get.return_value = {
        "items": [],
        "total": 0,
        "offset": 0,
        "limit": 50,
    }
    mock_task_api_dep.get.side_effect = [
        {"127.0.0.1": "localhost"},  # for /hosts/ (dependency)
        {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": 50,
        },  # for /{task.name}/history/
        {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": 50,
        },  # for running tasks at /{task.name}/history/
        [],  # for /stats/{task.name}
        {"items": [], "total": 0, "offset": 0, "limit": 50},  # chainable_tasks
    ]
    response = test_client.get(f"/archives/{created_task.name}")
    assert response.status_code == status.HTTP_200_OK
    assert created_task.name in response.text
    assert f"/archives/{created_task.name}/delete" in response.text
    assert f"/tasks/{created_task.name}/delete" not in response.text
    assert 'name="disable_bulk_insert"' in response.text
    # Render guard only (see test_archives_index); does not exercise the
    # inline-JS gating.
    assert 'name="dest_file"' in response.text
    checkbox_is_checked = bool(
        re.search(r'name="disable_bulk_insert"[^>]*checked', response.text)
    )
    assert checkbox_is_checked is checkbox_checked
    mock_task_api_dep.get.assert_any_await(f"/{created_task.name}/history/")
    mock_task_api_dep.get.assert_any_await(
        f"/{created_task.name}/history/",
        params={"status": TaskHistoryStatusEnum.RUNNING},
    )
    mock_task_api_dep.get.assert_any_await(f"/stats/{created_task.name}")
    mock_task_api_dep.get.assert_any_await("/hosts/")
    mock_inventory_api_dep.get.assert_any_await(
        "/services/",
        params={
            "service_type": ServiceTypeEnum.MYSQL,
            "offset": 0,
            "limit": MAX_PAGINATION_LIMIT,
        },
    )


@pytest.mark.usefixtures("_mock_get_archives_task_dep", "mock_get_username_mapping")
def test_archives_detail_with_remote_destination(
    test_client, created_task, mock_task_api_dep, mock_inventory_api_dep
):
    """Test archives detail page renders DEST_HOST, DEST_PORT, DEST_DB correctly."""
    mock_meta_config = yaml.dump(
        {
            "ALL": {
                "SOURCE_HOST": "127.0.0.1",
                "SOURCE_PORT": 3306,
            },
            "PURGE_LIST": [
                {
                    "ALIAS": "test_remote_archiver",
                    "SOURCE_DB": "source_db",
                    "SOURCE_TABLE": "source_table",
                    "DEST_TABLE": "dest_table",
                    "DEST_HOST": "remote.host",
                    "DEST_PORT": 3307,
                    "DEST_DB": "remote_db",
                    "SWAP_DROP": 1,
                }
            ],
        }
    )

    mock_data = {
        "meta": {
            "config": mock_meta_config,
            "target": "mock_target",
        },
        "hostname": "mock_nomad_host_name",
    }
    created_task.data = mock_data
    mock_inventory_api_dep.get.return_value = {
        "items": [],
        "total": 0,
        "offset": 0,
        "limit": 50,
    }
    mock_task_api_dep.get.side_effect = [
        {"127.0.0.1": "localhost"},
        {"items": [], "total": 0, "offset": 0, "limit": 50},
        {"items": [], "total": 0, "offset": 0, "limit": 50},
        [],
        {"items": [], "total": 0, "offset": 0, "limit": 50},
    ]
    response = test_client.get(f"/archives/{created_task.name}")
    assert response.status_code == status.HTTP_200_OK
    # Destination table should be qualified with DEST_DB not SOURCE_DB
    assert "dest_table" in response.text
    # Destination host should be displayed
    assert "remote.host" in response.text
    # Destination port should be displayed
    assert "3307" in response.text
    # Remote database should be displayed
    assert "remote_db" in response.text


def test_archives_create_form_renders_dest_schema_name_field(test_client):
    """GET /archives/ renders the standalone manual destination-schema field.

    The ``dest_db_name`` input lives in its own ``#dest_schema_name_field``
    container (decoupled from the manual-host block) so it can be shown when the
    destination host is the same as the source.
    """
    sep_app.dependency_overrides[get_archives_index_context] = lambda: {
        "user": "default_user",
        "connectivity_check_default": True,
        "csrf_token": "test-csrf",
        "services": [],
        "executor_hosts": [{"value": "host1", "label": "Host 1"}],
        "tasks": [],
        "history_tasks": [],
    }
    try:
        response = test_client.get("/archives/")
    finally:
        sep_app.dependency_overrides.pop(get_archives_index_context, None)

    assert response.status_code == status.HTTP_200_OK
    assert 'id="dest_schema_name_field"' in response.text
    assert 'name="dest_db_name"' in response.text


def test_archives_create_form_renders_delete_data_label(test_client):
    """Verify GET /archives/ renders the delete_data toggle with its disambiguated label.

    The legacy Jinja create form is still reachable via a direct ``/archives``
    URL (deprecated route), so its misleading ``DELETE_DATA`` label must read as
    "Delete Without Archiving" to match the React form and avoid the data-loss
    confusion.
    """
    sep_app.dependency_overrides[get_archives_index_context] = lambda: {
        "user": "default_user",
        "connectivity_check_default": True,
        "csrf_token": "test-csrf",
        "services": [],
        "executor_hosts": [{"value": "host1", "label": "Host 1"}],
        "tasks": [],
        "history_tasks": [],
    }
    try:
        response = test_client.get("/archives/")
    finally:
        sep_app.dependency_overrides.pop(get_archives_index_context, None)

    assert response.status_code == status.HTTP_200_OK
    assert "Delete Without Archiving" in response.text
    assert "DELETE_DATA" not in response.text


@pytest.mark.usefixtures("_mock_get_archives_task_dep", "mock_get_username_mapping")
def test_archives_detail_same_as_source_rehydrates_dest_schema(
    test_client, created_task, mock_task_api_dep, mock_inventory_api_dep
):
    """Edit form rehydrates a same-as-source task's manual destination schema.

    A task saved with a destination schema but no destination host (``DEST_DB``
    set, ``DEST_HOST`` absent) must render the standalone
    ``#dest_schema_name_field`` container with the saved schema pre-filled.
    """
    mock_meta_config = yaml.dump(
        {
            "ALL": {
                "SOURCE_HOST": "127.0.0.1",
                "SOURCE_PORT": 3306,
            },
            "PURGE_LIST": [
                {
                    "ALIAS": "test_same_host_manual_schema",
                    "SOURCE_DB": "source_db",
                    "SOURCE_TABLE": "source_table",
                    "DEST_TABLE": "dest_table",
                    "DEST_DB": "archive_db",
                    "SWAP_DROP": 1,
                }
            ],
        }
    )

    mock_data = {
        "meta": {
            "config": mock_meta_config,
            "target": "mock_target",
        },
        "hostname": "mock_nomad_host_name",
    }
    created_task.data = mock_data
    mock_inventory_api_dep.get.return_value = AsyncMock()
    mock_task_api_dep.get.side_effect = [
        {"127.0.0.1": "localhost"},
        {"items": [], "total": 0, "offset": 0, "limit": 50},
        {"items": [], "total": 0, "offset": 0, "limit": 50},
        [],
        {"items": [], "total": 0, "offset": 0, "limit": 50},
    ]
    response = test_client.get(f"/archives/{created_task.name}")
    assert response.status_code == status.HTTP_200_OK
    # The manual destination-schema field is its own container...
    assert 'id="dest_schema_name_field"' in response.text
    # ...and the saved schema name is server-rendered into that input.
    assert re.search(r'id="dest_db_name"[^>]*value="archive_db"', response.text)


@pytest.mark.usefixtures(
    "_mock_get_archives_task_dep", "_mock_check_for_conflicted_running_tasks"
)
def test_archives_execute(
    test_client,
    created_task,
    mock_task_api_dep,
):
    """Test executing an archives task."""
    mock_task_api_dep.post.return_value = AsyncMock()
    eta = datetime.now(tz=UTC) + timedelta(days=1)
    response = test_client.post(
        f"/archives/{created_task.name}", data={"eta": str(eta)}, follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert (
        response.headers["location"]
        == f"{test_client.base_url}/archives/{created_task.name}"
    )


@pytest.mark.usefixtures("_mock_get_archives_task_dep")
def test_archives_delete(
    test_client,
    created_task,
    mock_task_api_dep,
):
    """Test deleting an archives task."""
    mock_task_api_dep.delete.return_value = AsyncMock()

    response = test_client.post(
        f"/archives/{created_task.name}/delete", follow_redirects=False
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == "/archives"
    mock_task_api_dep.delete.assert_awaited_once_with(f"/{created_task.name}")
