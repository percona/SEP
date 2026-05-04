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

"""Tests for the dipper plugin JSON API routes under /api/plugins/dipper/."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from pydantic import BaseModel

from app.core.exceptions import HTTPNotFoundException
from app.inventory.models import ServiceTypeEnum

API_BASE = "/api/plugins/dipper"
FAKE_TASK_ID = 99


def build_fake_service(
    service_id: int = 1,
    service_type: str = ServiceTypeEnum.MYSQL.value,
) -> dict:
    """Build a fake inventory service dict for use in dipper API tests."""
    return {
        "id": service_id,
        "name": "test-service",
        "type": service_type,
        "port": 3306,
        "node_id": 1,
        "node": {
            "id": 1,
            "name": "test-node",
            "address": "127.0.0.1",
            "type": "generic",
        },
    }


class TestDipperSchemaEndpoint:
    """Tests for ``GET /api/plugins/dipper/schema``."""

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

    def test_schema_contains_script_preview_field(self, test_client):
        """Schema includes a script_preview field pointing at the preview endpoint."""
        response = test_client.get(f"{API_BASE}/schema")

        all_fields = [
            field for section in response.json()["forms"] for field in section["fields"]
        ]
        preview_fields = [f for f in all_fields if f["type"] == "script_preview"]
        assert len(preview_fields) == 1
        assert "dipper" in preview_fields[0]["endpointUrl"]


class TestDipperListEndpoint:
    """Tests for ``GET /api/plugins/dipper/``."""

    def test_list_returns_empty_array(self, test_client):
        """List endpoint returns an empty JSON array (dipper has no saved tasks)."""
        response = test_client.get(f"{API_BASE}/")

        assert response.status_code == status.HTTP_200_OK
        assert "application/json" in response.headers["content-type"]
        assert response.json() == []


class TestDipperScriptPreviewEndpoint:
    """Tests for ``GET /api/plugins/dipper/script-preview``."""

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

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

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

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        mock_inventory_api_dep.get.assert_not_called()


class TestDipperExecuteEndpoint:
    """Tests for ``POST /api/plugins/dipper/``."""

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

    def test_execute_returns_422_when_required_fields_missing(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Execute returns 422 when executor_host is absent."""
        response = test_client.post(
            f"{API_BASE}/",
            json={"service_id": 1, "collector_type": "environment"},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
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

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
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
            "app.sep.plugins.dipper.deps.DipperScript.from_path",
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

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
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

        with patch("app.sep.plugins.dipper.deps.settings") as mock_settings:
            mock_settings.PMM = mock_pmm
            response = test_client.post(
                f"{API_BASE}/",
                json={
                    "service_id": 1,
                    "collector_type": "pmm",
                    "executor_host": "node1",
                },
            )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        mock_task_api_dep.post.assert_not_called()
