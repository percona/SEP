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

"""Tests for the dipper plugin JSON API routes under /api/apps/dipper/."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from pydantic import BaseModel

from app.core.exceptions import HTTPNotFoundException
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.dipper.deps import get_pmm_api
from app.sep.deps import BEARER_REQUIRED_DETAIL
from app.sep.main import sep_app

API_BASE = "/api/apps/dipper"
FORWARDED_OFFSET = 5
FORWARDED_LIMIT = 10
FAKE_TASK_ID = 99


def _named(*names: str) -> list[SimpleNamespace]:
    """Build a list of objects exposing a ``name`` attribute (PMM node/service stand-ins)."""
    return [SimpleNamespace(name=name) for name in names]


def build_fake_service(
    service_id: int = 1,
    service_type: str = ServiceTypeEnum.MYSQL.value,
) -> dict:
    """Build a fake inventory service dict for use in dipper API tests."""
    return {
        "id": service_id,
        "service_id": f"/service_id/{service_id}",
        "name": "test-service",
        "type": service_type,
        "port": 3306,
        "node_id": 1,
        "node": {
            "id": 1,
            "node_id": "/node_id/1",
            "name": "test-node",
            "address": "127.0.0.1",
            "type": "generic",
        },
    }


class TestDipperSchemaEndpoint:
    """Tests for ``GET /api/apps/dipper/schema``."""

    def test_schema_returns_200(self, test_client):
        """Schema endpoint returns HTTP 200 with JSON content."""
        response = test_client.get(f"{API_BASE}/schema")

        assert response.status_code == status.HTTP_200_OK
        assert "application/json" in response.headers["content-type"]

    def test_schema_contains_plugin_name(self, test_client):
        """Schema body carries the correct plugin name."""
        response = test_client.get(f"{API_BASE}/schema")

        assert response.json()["name"] == "dipper"

    def test_schema_contains_expected_fields(self, test_client):
        """Schema includes required form field names."""
        response = test_client.get(f"{API_BASE}/schema")

        all_fields = [
            field for section in response.json()["forms"] for field in section["fields"]
        ]
        field_names = {f["name"] for f in all_fields}
        assert "service_id" in field_names
        assert "collector_type" in field_names
        assert "executor_host" in field_names

    def test_schema_has_no_static_script_preview_field(self, test_client):
        """Static schema does not include a script_preview field (preview lives in the dynamic form schema)."""
        response = test_client.get(f"{API_BASE}/schema")

        all_fields = [
            field for section in response.json()["forms"] for field in section["fields"]
        ]
        preview_fields = [f for f in all_fields if f["type"] == "script_preview"]
        assert len(preview_fields) == 0


class TestDipperListEndpoint:
    """Tests for ``GET /api/apps/dipper/``."""

    def test_list_returns_dipper_history_rows(self, test_client, mock_task_api_dep):
        """List endpoint returns task-history rows filtered to Dipper executions."""
        mock_task_api_dep.get = AsyncMock(
            return_value={
                "items": [
                    {
                        "id": 1,
                        "execution_request": {
                            "meta": {
                                "_snippet_filename": "dipper/1/pcs-collect-environment-mysql.sh"
                            }
                        },
                    },
                    {
                        "id": 2,
                        "execution_request": {
                            "meta": {"_snippet_filename": "snippets/example.sh"}
                        },
                    },
                ],
                "total": 2,
                "offset": 0,
                "limit": 100,
            }
        )

        response = test_client.get(f"{API_BASE}/")

        assert response.status_code == status.HTTP_200_OK
        assert "application/json" in response.headers["content-type"]
        body = response.json()
        assert body["total"] == 1  # filtered Dipper subset, not the upstream count
        assert [item["id"] for item in body["items"]] == [1]

    def test_list_total_reflects_filtered_subset(self, test_client, mock_task_api_dep):
        """Report ``total`` as the Dipper-filtered subset, not the upstream total."""
        mock_task_api_dep.get = AsyncMock(
            return_value={
                "items": [
                    {
                        "id": 10,
                        "execution_request": {
                            "meta": {
                                "_snippet_filename": "dipper/1/pcs-collect-environment-mysql.sh"
                            }
                        },
                    },
                    {
                        "id": 11,
                        "execution_request": {
                            "meta": {"_snippet_filename": "snippets/other.sh"}
                        },
                    },
                    {
                        "id": 12,
                        "execution_request": {
                            "meta": {"_snippet_filename": "snippets/another.sh"}
                        },
                    },
                ],
                "total": 500,
                "offset": 0,
                "limit": 3,
            }
        )

        response = test_client.get(f"{API_BASE}/")

        body = response.json()
        assert body["total"] == 1
        assert [item["id"] for item in body["items"]] == [10]

    def test_list_forwards_offset_and_limit(self, test_client, mock_task_api_dep):
        """Forward offset/limit query params to the upstream history call."""
        mock_task_api_dep.get = AsyncMock(
            return_value={
                "items": [],
                "total": 0,
                "offset": FORWARDED_OFFSET,
                "limit": FORWARDED_LIMIT,
            }
        )

        response = test_client.get(
            f"{API_BASE}/?offset={FORWARDED_OFFSET}&limit={FORWARDED_LIMIT}"
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["offset"] == FORWARDED_OFFSET
        assert body["limit"] == FORWARDED_LIMIT
        mock_task_api_dep.get.assert_awaited_once_with(
            "/history/",
            params={"offset": FORWARDED_OFFSET, "limit": FORWARDED_LIMIT},
        )


class TestDipperFormSchemaEndpoint:
    """Tests for ``GET /api/apps/dipper/form-schema``."""

    def test_mysql_environment_schema_contains_payload_fields(
        self, test_client, mock_inventory_api_dep, mock_task_api_dep
    ):
        """MySQL environment schema includes legacy dynamic payload args."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value=build_fake_service(service_type=ServiceTypeEnum.MYSQL.value)
        )
        mock_task_api_dep.get = AsyncMock(return_value={})

        response = test_client.get(
            f"{API_BASE}/form-schema",
            params={"service_id": 1, "collector_type": "environment"},
        )

        assert response.status_code == status.HTTP_200_OK
        fields = [
            field for section in response.json()["forms"] for field in section["fields"]
        ]
        field_names = {field["name"] for field in fields}
        assert {
            "o",
            "d",
            "i",
            "t",
            "p",
            "n",
            "executor_host",
            "script_preview",
        } <= field_names

    def test_pmm_schema_contains_defaults(
        self, test_client, mock_inventory_api_dep, mock_task_api_dep
    ):
        """PMM schema includes PMM args seeded from the selected service."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value=build_fake_service(service_type=ServiceTypeEnum.MYSQL.value)
        )
        mock_task_api_dep.get = AsyncMock(return_value={})

        response = test_client.get(
            f"{API_BASE}/form-schema",
            params={"service_id": 1, "collector_type": "pmm"},
        )

        assert response.status_code == status.HTTP_200_OK
        fields = [
            field for section in response.json()["forms"] for field in section["fields"]
        ]
        by_name = {field["name"]: field for field in fields}
        assert {"pmmserver", "node", "service"} <= set(by_name)
        assert by_name["node"]["default"] == "test-node"
        assert by_name["service"]["default"] == "test-service"

    def test_pmm_schema_omits_hidden_apikey_field(
        self, test_client, mock_inventory_api_dep, mock_task_api_dep
    ):
        """The hidden apikey param must not surface in the React form schema."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value=build_fake_service(service_type=ServiceTypeEnum.MYSQL.value)
        )
        mock_task_api_dep.get = AsyncMock(return_value={})

        response = test_client.get(
            f"{API_BASE}/form-schema",
            params={"service_id": 1, "collector_type": "pmm"},
        )

        assert response.status_code == status.HTTP_200_OK
        by_name = self._fields_by_name(response)
        assert "apikey" not in by_name

    def _fields_by_name(self, response) -> dict:
        fields = [
            field for section in response.json()["forms"] for field in section["fields"]
        ]
        return {field["name"]: field for field in fields}

    def test_pmm_schema_renders_dropdowns_from_pmm_inventory(
        self, test_client, mock_inventory_api_dep, mock_task_api_dep, mock_pmm_api_dep
    ):
        """node/service render as choice dropdowns sourced from PMM inventory."""
        mock_inventory_api_dep.get = AsyncMock(return_value=build_fake_service())
        mock_task_api_dep.get = AsyncMock(return_value={})
        mock_pmm_api_dep.get_nodes.return_value = _named("test-node", "other-node")
        mock_pmm_api_dep.get_services.return_value = _named("test-service", "svc-2")

        response = test_client.get(
            f"{API_BASE}/form-schema",
            params={"service_id": 1, "collector_type": "pmm"},
        )

        assert response.status_code == status.HTTP_200_OK
        by_name = self._fields_by_name(response)
        assert by_name["node"]["type"] == "choice"
        assert by_name["service"]["type"] == "choice"
        assert {c["value"] for c in by_name["node"]["choices"]} == {
            "test-node",
            "other-node",
        }
        assert {c["value"] for c in by_name["service"]["choices"]} == {
            "test-service",
            "svc-2",
        }

    def test_pmm_dropdown_preselects_inventory_default_when_present(
        self, test_client, mock_inventory_api_dep, mock_task_api_dep, mock_pmm_api_dep
    ):
        """The inventory-derived default is pre-selected when it is a valid option."""
        mock_inventory_api_dep.get = AsyncMock(return_value=build_fake_service())
        mock_task_api_dep.get = AsyncMock(return_value={})
        mock_pmm_api_dep.get_nodes.return_value = _named("test-node", "other-node")
        mock_pmm_api_dep.get_services.return_value = _named("test-service", "svc-2")

        response = test_client.get(
            f"{API_BASE}/form-schema",
            params={"service_id": 1, "collector_type": "pmm"},
        )

        by_name = self._fields_by_name(response)
        assert by_name["node"]["default"] == "test-node"
        assert by_name["service"]["default"] == "test-service"

    def test_pmm_dropdown_omits_default_when_not_in_options(
        self, test_client, mock_inventory_api_dep, mock_task_api_dep, mock_pmm_api_dep
    ):
        """No default is set when the inventory value is absent from PMM options."""
        mock_inventory_api_dep.get = AsyncMock(return_value=build_fake_service())
        mock_task_api_dep.get = AsyncMock(return_value={})
        mock_pmm_api_dep.get_nodes.return_value = _named("other-node")
        mock_pmm_api_dep.get_services.return_value = _named("svc-2")

        response = test_client.get(
            f"{API_BASE}/form-schema",
            params={"service_id": 1, "collector_type": "pmm"},
        )

        by_name = self._fields_by_name(response)
        assert by_name["node"]["type"] == "choice"
        assert by_name["node"].get("default") is None
        assert by_name["service"].get("default") is None

    def test_pmm_schema_falls_back_to_text_when_pmm_empty(
        self, test_client, mock_inventory_api_dep, mock_task_api_dep, mock_pmm_api_dep
    ):
        """Empty PMM inventory keeps node/service as free-text StringFields."""
        mock_inventory_api_dep.get = AsyncMock(return_value=build_fake_service())
        mock_task_api_dep.get = AsyncMock(return_value={})
        mock_pmm_api_dep.get_nodes.return_value = []
        mock_pmm_api_dep.get_services.return_value = []

        response = test_client.get(
            f"{API_BASE}/form-schema",
            params={"service_id": 1, "collector_type": "pmm"},
        )

        assert response.status_code == status.HTTP_200_OK
        by_name = self._fields_by_name(response)
        assert by_name["node"]["type"] == "string"
        assert by_name["service"]["type"] == "string"
        assert by_name["node"]["default"] == "test-node"

    def test_pmm_schema_falls_back_to_text_when_pmm_unconfigured(
        self, test_client, mock_inventory_api_dep, mock_task_api_dep
    ):
        """Unconfigured PMM (client is ``None``) keeps free-text fields and returns 200."""
        mock_inventory_api_dep.get = AsyncMock(return_value=build_fake_service())
        mock_task_api_dep.get = AsyncMock(return_value={})
        sentinel = object()
        previous = sep_app.dependency_overrides.get(get_pmm_api, sentinel)
        sep_app.dependency_overrides[get_pmm_api] = lambda: None
        try:
            response = test_client.get(
                f"{API_BASE}/form-schema",
                params={"service_id": 1, "collector_type": "pmm"},
            )
        finally:
            if previous is sentinel:
                sep_app.dependency_overrides.pop(get_pmm_api, None)
            else:
                sep_app.dependency_overrides[get_pmm_api] = previous

        assert response.status_code == status.HTTP_200_OK
        by_name = self._fields_by_name(response)
        assert by_name["node"]["type"] == "string"
        assert by_name["service"]["type"] == "string"

    def test_pmm_schema_falls_back_to_text_when_pmm_unreachable(
        self, test_client, mock_inventory_api_dep, mock_task_api_dep, mock_pmm_api_dep
    ):
        """A raising PMM client must not fail the form — return 200 with free-text."""
        mock_inventory_api_dep.get = AsyncMock(return_value=build_fake_service())
        mock_task_api_dep.get = AsyncMock(return_value={})
        mock_pmm_api_dep.get_nodes.side_effect = RuntimeError("connection refused")
        mock_pmm_api_dep.get_services.side_effect = RuntimeError("connection refused")

        response = test_client.get(
            f"{API_BASE}/form-schema",
            params={"service_id": 1, "collector_type": "pmm"},
        )

        assert response.status_code == status.HTTP_200_OK
        by_name = self._fields_by_name(response)
        assert by_name["node"]["type"] == "string"
        assert by_name["service"]["type"] == "string"

    def test_environment_collector_does_not_query_pmm(
        self, test_client, mock_inventory_api_dep, mock_task_api_dep, mock_pmm_api_dep
    ):
        """The environment collector must not trigger any PMM inventory fetch."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value=build_fake_service(service_type=ServiceTypeEnum.MYSQL.value)
        )
        mock_task_api_dep.get = AsyncMock(return_value={})

        response = test_client.get(
            f"{API_BASE}/form-schema",
            params={"service_id": 1, "collector_type": "environment"},
        )

        assert response.status_code == status.HTTP_200_OK
        mock_pmm_api_dep.get_nodes.assert_not_awaited()
        mock_pmm_api_dep.get_services.assert_not_awaited()


class TestDipperScriptPreviewEndpoint:
    """Tests for ``GET /api/apps/dipper/script-preview``."""

    def test_preview_returns_content_for_mysql_environment(
        self, test_client, mock_inventory_api_dep
    ):
        """Preview endpoint returns script content for a MySQL + environment combination."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value=build_fake_service(service_type=ServiceTypeEnum.MYSQL.value)
        )

        response = test_client.get(
            f"{API_BASE}/script-preview",
            params={"service_id": 1, "collector_type": "environment"},
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert isinstance(body["content"], str)
        assert len(body["content"]) > 0
        assert isinstance(body["language"], str)
        assert isinstance(body["is_truncated"], bool)

    def test_preview_returns_bash_language_for_shell_script(
        self, test_client, mock_inventory_api_dep
    ):
        """Shell scripts carry the ``bash`` language hint in the response."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value=build_fake_service(service_type=ServiceTypeEnum.MYSQL.value)
        )

        response = test_client.get(
            f"{API_BASE}/script-preview",
            params={"service_id": 1, "collector_type": "environment"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["language"] == "bash"

    def test_preview_returns_422_for_pmm_with_mongodb_service(
        self, test_client, mock_inventory_api_dep
    ):
        """Preview returns 422 when PMM collector is requested for a MongoDB service."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value=build_fake_service(service_type=ServiceTypeEnum.MONGODB.value)
        )

        response = test_client.get(
            f"{API_BASE}/script-preview",
            params={"service_id": 1, "collector_type": "pmm"},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_preview_returns_404_when_service_not_found(
        self, test_client, mock_inventory_api_dep
    ):
        """Preview returns 404 when the inventory service does not exist."""
        mock_inventory_api_dep.get = AsyncMock(side_effect=HTTPNotFoundException())

        response = test_client.get(
            f"{API_BASE}/script-preview",
            params={"service_id": 9999, "collector_type": "environment"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_preview_returns_422_for_invalid_collector_type(
        self, test_client, mock_inventory_api_dep
    ):
        """Preview returns 422 for an unrecognised collector_type value."""
        response = test_client.get(
            f"{API_BASE}/script-preview",
            params={"service_id": 1, "collector_type": "invalid"},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_inventory_api_dep.get.assert_not_called()


class TestDipperBearerGate:
    """Cover Bearer-gate behavior on dipper JSON mutation."""

    def test_cookie_only_execute_returns_401(
        self, api_admin_client_no_bearer, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Cookie-auth admin POST without Bearer header is 401'd before downstream calls."""
        response = api_admin_client_no_bearer.post(
            f"{API_BASE}/",
            json={
                "service_id": 1,
                "collector_type": "environment",
                "executor_host": "node1",
            },
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["detail"] == BEARER_REQUIRED_DETAIL
        mock_task_api_dep.post.assert_not_called()
        mock_inventory_api_dep.get.assert_not_called()

    def test_cookie_only_post_with_empty_body_still_gate_rejected(
        self, api_admin_client_no_bearer, mock_task_api_dep, mock_inventory_api_dep
    ) -> None:
        """An empty JSON body cannot trick the gate into 422 before 401.

        Regression guard: the framework gate must run before request-body
        validation, so the response is always the 401 detail (never a 422
        Pydantic error). Otherwise a malformed body could probe authorization
        ordering.
        """
        response = api_admin_client_no_bearer.post(f"{API_BASE}/", json={})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["detail"] == BEARER_REQUIRED_DETAIL
        mock_task_api_dep.post.assert_not_called()
        mock_inventory_api_dep.get.assert_not_called()


class TestDipperExecuteEndpoint:
    """Tests for ``POST /api/apps/dipper/``."""

    def test_execute_returns_201(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Execute endpoint returns HTTP 201 with execution response body."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value=build_fake_service(service_type=ServiceTypeEnum.MYSQL.value)
        )
        mock_task_api_dep.post = AsyncMock(return_value={"id": FAKE_TASK_ID})

        response = test_client.post(
            f"{API_BASE}/",
            json={
                "service_id": 1,
                "collector_type": "environment",
                "executor_host": "node1",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_execute_response_body_contains_expected_fields(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Execute response body carries task_id, snippet_filename, service_id, collector_type."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value=build_fake_service(service_type=ServiceTypeEnum.MYSQL.value)
        )
        mock_task_api_dep.post = AsyncMock(return_value={"id": FAKE_TASK_ID})

        response = test_client.post(
            f"{API_BASE}/",
            json={
                "service_id": 1,
                "collector_type": "environment",
                "executor_host": "node1",
            },
        )

        body = response.json()
        assert body["task_id"] == FAKE_TASK_ID
        assert body["service_id"] == 1
        assert body["collector_type"] == "environment"
        assert "dipper/1/" in body["snippet_filename"]

    def test_execute_posts_to_tasks_api(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Execute endpoint posts to the tasks API execute path with meta payload."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value=build_fake_service(service_type=ServiceTypeEnum.MYSQL.value)
        )
        mock_task_api_dep.post = AsyncMock(return_value={"id": FAKE_TASK_ID})

        test_client.post(
            f"{API_BASE}/",
            json={
                "service_id": 1,
                "collector_type": "environment",
                "executor_host": "node1",
            },
        )

        mock_task_api_dep.post.assert_awaited_once()
        path_arg = mock_task_api_dep.post.call_args.args[0]
        assert path_arg.startswith("/execute/")
        meta = mock_task_api_dep.post.call_args.kwargs["json"]["meta"]
        assert meta["target"] == "node1"
        assert "dipper/1/" in meta["_snippet_filename"]
        assert meta["interpreter"].startswith("sudo ")

    def test_execute_sudo_false_overrides_script_default(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Explicit sudo=false in the request body disables sudo even when the script defaults to sudo."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value=build_fake_service(service_type=ServiceTypeEnum.MYSQL.value)
        )
        mock_task_api_dep.post = AsyncMock(return_value={"id": FAKE_TASK_ID})

        test_client.post(
            f"{API_BASE}/",
            json={
                "service_id": 1,
                "collector_type": "environment",
                "executor_host": "node1",
                "sudo": False,
            },
        )

        mock_task_api_dep.post.assert_awaited_once()
        meta = mock_task_api_dep.post.call_args.kwargs["json"]["meta"]
        assert not meta["interpreter"].startswith("sudo ")

    def test_execute_preserves_zero_arg(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Execute keeps integer 0 values instead of dropping them as falsy."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value=build_fake_service(service_type=ServiceTypeEnum.MYSQL.value)
        )
        mock_task_api_dep.post = AsyncMock(return_value={"id": FAKE_TASK_ID})

        response = test_client.post(
            f"{API_BASE}/",
            json={
                "service_id": 1,
                "collector_type": "environment",
                "executor_host": "node1",
                "args": {"n": 0},
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        meta = mock_task_api_dep.post.call_args.kwargs["json"]["meta"]
        assert "-n 0" in meta["args"]

    def test_execute_returns_422_when_required_fields_missing(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Execute returns 422 when executor_host is absent."""
        response = test_client.post(
            f"{API_BASE}/",
            json={"service_id": 1, "collector_type": "environment"},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()

    def test_execute_returns_404_when_service_not_found(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Execute returns 404 when the inventory service does not exist."""
        mock_inventory_api_dep.get = AsyncMock(side_effect=HTTPNotFoundException())

        response = test_client.post(
            f"{API_BASE}/",
            json={
                "service_id": 9999,
                "collector_type": "environment",
                "executor_host": "node1",
            },
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_task_api_dep.post.assert_not_called()

    def test_execute_pmm_with_pmmserver_returns_201(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """PMM execute with an explicit pmmserver returns 201 for a MySQL service."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value=build_fake_service(service_type=ServiceTypeEnum.MYSQL.value)
        )
        mock_task_api_dep.post = AsyncMock(return_value={"id": 42})

        response = test_client.post(
            f"{API_BASE}/",
            json={
                "service_id": 1,
                "collector_type": "pmm",
                "executor_host": "node1",
                "args": {
                    "pmmserver": "https://pmm.example.com:8443",
                    "node": "test-node",
                    "service": "test-svc",
                },
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["collector_type"] == "pmm"
        mock_task_api_dep.post.assert_awaited_once()

    @pytest.mark.parametrize(
        "service_type",
        [ServiceTypeEnum.MONGODB.value, ServiceTypeEnum.POSTGRESQL.value],
    )
    def test_execute_pmm_returns_422_for_unsupported_service_type(
        self, service_type, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """PMM execute returns 422 for service types that have no PMM script."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value=build_fake_service(service_type=service_type)
        )

        response = test_client.post(
            f"{API_BASE}/",
            json={
                "service_id": 1,
                "collector_type": "pmm",
                "executor_host": "node1",
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()

    def test_execute_returns_422_when_args_fail_schema_validation(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Execute returns 422 when body args fail the script's execution model."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value=build_fake_service(service_type=ServiceTypeEnum.MYSQL.value)
        )

        class _StrictModel(BaseModel):
            required_field: str

        mock_script = MagicMock()
        mock_script.get_execution_model.return_value = _StrictModel
        mock_script.sudo = None

        with patch(
            "app.sep.apps.dipper.deps.DipperScript.from_path",
            new=AsyncMock(return_value=mock_script),
        ):
            response = test_client.post(
                f"{API_BASE}/",
                json={
                    "service_id": 1,
                    "collector_type": "environment",
                    "executor_host": "node1",
                },
            )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()

    def test_execute_pmm_returns_422_when_no_pmmserver_configured(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Execute returns 422 for PMM when no pmmserver in args and none configured."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value=build_fake_service(service_type=ServiceTypeEnum.MYSQL.value)
        )
        mock_pmm = MagicMock()
        mock_pmm.endpoint = None
        mock_pmm.api_key = None

        with patch("app.sep.apps.dipper.deps.settings") as mock_settings:
            mock_settings.PMM = mock_pmm
            response = test_client.post(
                f"{API_BASE}/",
                json={
                    "service_id": 1,
                    "collector_type": "pmm",
                    "executor_host": "node1",
                },
            )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()


class TestDipperValkeyCollectors:
    """Valkey is selectable for both the environment and PMM collectors."""

    @staticmethod
    def _fields_by_name(response) -> dict:
        fields = [
            field for section in response.json()["forms"] for field in section["fields"]
        ]
        return {field["name"]: field for field in fields}

    def test_preview_returns_bash_for_valkey_environment(
        self, test_client, mock_inventory_api_dep
    ):
        """The Valkey environment collector previews as a bash script."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value=build_fake_service(service_type=ServiceTypeEnum.VALKEY.value)
        )

        response = test_client.get(
            f"{API_BASE}/script-preview",
            params={"service_id": 1, "collector_type": "environment"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["language"] == "bash"

    def test_preview_returns_python_for_valkey_pmm(
        self, test_client, mock_inventory_api_dep
    ):
        """Valkey is the first non-MySQL service to resolve a PMM collector."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value=build_fake_service(service_type=ServiceTypeEnum.VALKEY.value)
        )

        response = test_client.get(
            f"{API_BASE}/script-preview",
            params={"service_id": 1, "collector_type": "pmm"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["language"] == "python"

    def test_valkey_environment_schema_contains_payload_fields(
        self, test_client, mock_inventory_api_dep, mock_task_api_dep
    ):
        """The Valkey environment form exposes its getopts-derived parameters."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value=build_fake_service(service_type=ServiceTypeEnum.VALKEY.value)
        )
        mock_task_api_dep.get = AsyncMock(return_value={})

        response = test_client.get(
            f"{API_BASE}/form-schema",
            params={"service_id": 1, "collector_type": "environment"},
        )

        assert response.status_code == status.HTTP_200_OK
        field_names = set(self._fields_by_name(response))
        assert {"o", "d", "i", "t", "p", "l", "c", "s"} <= field_names

    def test_valkey_pmm_schema_omits_hidden_fields(
        self, test_client, mock_inventory_api_dep, mock_task_api_dep
    ):
        """The Valkey PMM form surfaces PMM fields but hides apikey and sentinel."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value=build_fake_service(service_type=ServiceTypeEnum.VALKEY.value)
        )
        mock_task_api_dep.get = AsyncMock(return_value={})

        response = test_client.get(
            f"{API_BASE}/form-schema",
            params={"service_id": 1, "collector_type": "pmm"},
        )

        assert response.status_code == status.HTTP_200_OK
        by_name = self._fields_by_name(response)
        assert {"pmmserver", "node", "service", "cluster"} <= set(by_name)
        assert "apikey" not in by_name
        assert "sentinel" not in by_name

    def test_execute_valkey_pmm_returns_201(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """PMM execute for a Valkey service runs end-to-end through the deps stack.

        The body-model dep is intentionally not overridden so the PMM-config
        fallback in ``build_dipper_execution_meta`` is exercised for the second
        PMM-capable service type.
        """
        mock_inventory_api_dep.get = AsyncMock(
            return_value=build_fake_service(service_type=ServiceTypeEnum.VALKEY.value)
        )
        mock_task_api_dep.post = AsyncMock(return_value={"id": FAKE_TASK_ID})

        response = test_client.post(
            f"{API_BASE}/",
            json={
                "service_id": 1,
                "collector_type": "pmm",
                "executor_host": "node1",
                "args": {
                    "pmmserver": "https://pmm.example.com:8443",
                    "node": "test-node",
                    "service": "test-svc",
                },
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["collector_type"] == "pmm"
        mock_task_api_dep.post.assert_awaited_once()
