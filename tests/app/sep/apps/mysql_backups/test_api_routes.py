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

"""Tests for the mysql_backups plugin JSON API routes."""

from datetime import datetime, UTC
from unittest.mock import AsyncMock

import pytest
import yaml
from fastapi import status

from app.sep.apps.mysql_backups.models import BackupType
from app.sep.deps import BEARER_REQUIRED_DETAIL
from app.tasks.models import TaskBackendEnum, TaskHistoryStatusEnum

BEARER_HEADERS = {"Authorization": "Bearer test-token"}


def build_backup_task(
    name: str = "backup-task", backup_type: BackupType = BackupType.MYDUMPER
) -> dict:
    """Build a fake backups task payload for route tests."""
    config = yaml.dump(
        {
            "ALL_SERVERS": {"compress": False},
            "SERVER_LIST": [
                {
                    "ALIAS": "node1",
                    "HOST": "localhost",
                    "PORT": 3306,
                    "BACKUP_TYPE": backup_type.value,
                    "UPLOAD": [],
                }
            ],
        }
    )
    return {
        "id": 1,
        "name": name,
        "backend": TaskBackendEnum.PROXY,
        "owner": "BACKUPS",
        "is_template": False,
        "protected": False,
        "alert_on_fail": False,
        "data": {
            "task": "run-python",
            "meta": {
                "target": "host1",
                "config": config,
                "_service_name": "svc",
            },
            "payload": "file:///dev/null",
        },
        "created_at": datetime.now(UTC),
        "updated_at": None,
        "created_by": "user@example.com",
        "last_updated_by": "user@example.com",
    }


def build_backup_write_body(
    task_name: str = "backup-task",
    hostname: str = "host1",
    service_id: int = 1,
    backup_type: BackupType = BackupType.MYDUMPER,
    **kwargs,
) -> dict:
    """Build a valid backup-create JSON body.

    ``upload`` is required and non-empty per the explicit
    MultiChoice contract; the default ``S3 + s3_bucket`` pair keeps the
    bidirectional validator happy. Tests assert on the contract by
    overriding ``upload`` and/or ``s3_bucket`` explicitly.
    """
    body = {
        "task_name": task_name,
        "hostname": hostname,
        "service_id": service_id,
        "backup_type": backup_type.value,
        "upload": ["S3"],
        "s3_bucket": "bkt",
    }
    body.update(kwargs)
    return body


class TestSchemaEndpoint:
    """Tests for GET /api/apps/mysql_backups/schema."""

    def test_schema_returns_200(self, test_client):
        """The schema endpoint returns 200 and JSON content."""
        response = test_client.get("/api/apps/mysql_backups/schema")
        assert response.status_code == status.HTTP_200_OK
        assert "application/json" in response.headers["content-type"]

    def test_schema_contains_plugin_name(self, test_client):
        """Body carries the plugin name."""
        response = test_client.get("/api/apps/mysql_backups/schema")
        assert response.json()["name"] == "mysql_backups"

    def test_schema_capabilities(self, test_client):
        """Capabilities mirror Jinja2: chaining + alerts + scheduling.

        ``stats`` is the framework default (``False``); MySQL Backups does not
        render an aggregated execution-stats card today.
        """
        caps = test_client.get("/api/apps/mysql_backups/schema").json()["capabilities"]
        assert caps == {
            "chaining": True,
            "alert_on_fail": True,
            "scheduling": True,
            "stats": False,
            "pii_anonymization": False,
        }

    def test_schema_includes_backup_type_field(self, test_client):
        """The mode-discriminator field is present."""
        body = test_client.get("/api/apps/mysql_backups/schema").json()
        names = {f["name"] for s in body["forms"] for f in s["fields"]}
        assert "backup_type" in names
        assert "upload" in names

    def test_schema_declares_restore_related_app(self, test_client):
        """Link the backups schema to the separately registered restore app."""
        body = test_client.get("/api/apps/mysql_backups/schema").json()
        assert body["related_apps"] == [
            {
                "app_key": "mysql_backups/restore",
                "label": "Restore",
                "route_segment": "restores",
            },
        ]

    def test_schema_anonymous_returns_401(self, unauthenticated_client):
        """Anonymous schema fetch is rejected by IsApiAuthenticated."""
        response = unauthenticated_client.get("/api/apps/mysql_backups/schema")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestListEndpoint:
    """Tests for GET /api/apps/mysql_backups/."""

    def test_list_returns_data(self, test_client, mock_task_api_dep):
        """The list endpoint returns the registered backups tasks."""
        task = build_backup_task()
        mock_task_api_dep.get = AsyncMock(
            return_value={"items": [task], "total": 1, "offset": 0, "limit": 50}
        )
        mock_task_api_dep.post = AsyncMock(
            return_value={
                task["name"]: {
                    "status": TaskHistoryStatusEnum.SUCCESS.value,
                    "finished_at": None,
                }
            }
        )
        response = test_client.get("/api/apps/mysql_backups/")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == 1
        assert body["offset"] == 0
        assert body["limit"] == 50  # noqa: PLR2004
        items = body["items"]
        assert len(items) == 1
        row = items[0]
        assert row["name"] == task["name"]
        assert row["status"] == TaskHistoryStatusEnum.SUCCESS.value
        assert row["backup_type"] == BackupType.MYDUMPER.value
        assert "service_type" not in row
        assert "owner" not in row
        assert "anonymize_mask" in row
        assert "anonymized_entities" in row
        mock_task_api_dep.post.assert_awaited_once_with(
            "/history/latest", json={"names": [task["name"]]}
        )

    def test_list_returns_empty(self, test_client, mock_task_api_dep):
        """Empty backup list returns an empty paginated envelope."""
        mock_task_api_dep.get.return_value = {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": 50,
        }
        response = test_client.get("/api/apps/mysql_backups/")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["items"] == []
        assert body["total"] == 0

    def test_list_paginates(self, test_client, mock_task_api_dep):
        """offset/limit query params propagate to the underlying Tasks API call."""
        mock_get = AsyncMock(
            return_value={"items": [], "total": 0, "offset": 25, "limit": 10}
        )
        mock_task_api_dep.get = mock_get
        response = test_client.get("/api/apps/mysql_backups/?offset=25&limit=10")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["offset"] == 25  # noqa: PLR2004
        assert body["limit"] == 10  # noqa: PLR2004
        # First (and only) Tasks API call carries the pagination params.
        _, kwargs = mock_get.call_args_list[0]
        assert kwargs["params"]["offset"] == 25  # noqa: PLR2004
        assert kwargs["params"]["limit"] == 10  # noqa: PLR2004

    @pytest.mark.parametrize(
        "query",
        ["offset=-1", "limit=0", "limit=-5", "limit=51", "limit=99999"],
    )
    def test_list_rejects_out_of_range_pagination(
        self, test_client, mock_task_api_dep, query
    ):
        """Negative/zero/oversized pagination params are rejected with 422."""
        mock_task_api_dep.get = AsyncMock()
        response = test_client.get(f"/api/apps/mysql_backups/?{query}")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        mock_task_api_dep.get.assert_not_called()


class TestDetailEndpoint:
    """Tests for GET /api/apps/mysql_backups/{task_name}."""

    def test_detail_returns_task(self, test_client, mock_task_api_dep):
        """The detail endpoint returns a single backup task."""
        task = build_backup_task()
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                task,
                {"items": [], "total": 0, "offset": 0, "limit": 50},
            ]
        )
        response = test_client.get(f"/api/apps/mysql_backups/{task['name']}")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["name"] == task["name"]
        assert body["backup_type"] == BackupType.MYDUMPER.value
        assert "service_type" not in body
        assert "owner" not in body
        assert "anonymize_mask" in body
        assert "anonymized_entities" in body

    def test_detail_returns_404_for_missing(self, test_client, mock_task_api_dep):
        """Missing task returns 404."""
        response = test_client.get("/api/apps/mysql_backups/nope")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_detail_returns_404_for_wrong_owner(self, test_client, mock_task_api_dep):
        """Task owned by another plugin returns 404 (no cross-plugin enumeration)."""
        response = test_client.get("/api/apps/mysql_backups/some-checksums-task")

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestCreateEndpoint:
    """Tests for POST /api/apps/mysql_backups/."""

    def test_create_returns_201(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """Happy path: backup_type=M creates a task with 201."""
        task = build_backup_task()
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        mock_task_api_dep.post = AsyncMock(return_value=task)
        body = build_backup_write_body(
            service_id=created_service.id, backup_type=BackupType.MYDUMPER
        )
        response = test_client.post(
            "/api/apps/mysql_backups/", json=body, headers=BEARER_HEADERS
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text
        assert response.json()["name"] == task["name"]

    def test_create_xtrabackup_happy_path(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """backup_type=X with xtrabackup field creates a task."""
        task = build_backup_task(backup_type=BackupType.XTRABACKUP)
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        mock_task_api_dep.post = AsyncMock(return_value=task)
        body = build_backup_write_body(
            service_id=created_service.id,
            backup_type=BackupType.XTRABACKUP,
            xtrabackup_extra_args="--no-version-check",
        )
        response = test_client.post(
            "/api/apps/mysql_backups/", json=body, headers=BEARER_HEADERS
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_create_binlog_happy_path(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """backup_type=B with binlog field creates a task."""
        task = build_backup_task(backup_type=BackupType.BINLOG)
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        mock_task_api_dep.post = AsyncMock(return_value=task)
        body = build_backup_write_body(
            service_id=created_service.id,
            backup_type=BackupType.BINLOG,
            binlog_prefix="bp",
        )
        response = test_client.post(
            "/api/apps/mysql_backups/", json=body, headers=BEARER_HEADERS
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_create_rejects_cross_mode_field(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """backup_type=M + xtrabackup_extra_args is rejected with 422."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        body = build_backup_write_body(
            service_id=created_service.id,
            backup_type=BackupType.MYDUMPER,
            xtrabackup_extra_args="--foo",
        )
        response = test_client.post(
            "/api/apps/mysql_backups/", json=body, headers=BEARER_HEADERS
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param(
                {"encryption_recipient": "ops@example.com"},
                id="recipient-without-encrypt",
            ),
            pytest.param({"encrypt_using_tmpdir": True}, id="tmpdir-without-encrypt"),
            pytest.param({"post_run_encrypt": True}, id="post-run-without-recipient"),
            pytest.param(
                {
                    "encrypt": True,
                    "encrypt_using_tmpdir": True,
                    "post_run_encrypt": True,
                    "encryption_recipient": "ops@example.com",
                },
                id="tmpdir-and-post-run-together",
            ),
        ],
    )
    def test_create_rejects_invalid_encryption_combo(
        self,
        test_client,
        mock_task_api_dep,
        mock_inventory_api_dep,
        created_service,
        overrides,
    ):
        """Reject an invalid encryption combination with 422 before any POST."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        body = build_backup_write_body(service_id=created_service.id, **overrides)
        response = test_client.post(
            "/api/apps/mysql_backups/", json=body, headers=BEARER_HEADERS
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()

    def test_create_rejects_missing_required_fields(
        self, test_client, mock_task_api_dep
    ):
        """Empty body returns 422 (required fields missing)."""
        response = test_client.post(
            "/api/apps/mysql_backups/", json={}, headers=BEARER_HEADERS
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()

    def test_create_rejects_empty_upload_list(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """``upload=[]`` violates the explicit MultiChoice contract → 422.

        The legacy bucket-inference path is gone; submitting with no provider
        selected must surface 422 instead of silently inferring S3 from
        ``s3_bucket``.
        """
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        body = build_backup_write_body(
            service_id=created_service.id, backup_type=BackupType.MYDUMPER
        )
        body["upload"] = []
        response = test_client.post(
            "/api/apps/mysql_backups/", json=body, headers=BEARER_HEADERS
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()

    def test_create_rejects_bucket_without_matching_provider(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """``s3_bucket`` set with ``S3`` absent from ``upload`` → 422.

        Pins the cross-field contract from both the schema-level ``forbidden``
        gate (Contains predicate) and the ``validate_upload_provider_consistency``
        model validator.
        """
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        body = build_backup_write_body(
            service_id=created_service.id,
            backup_type=BackupType.MYDUMPER,
            upload=["RSYNC"],
            rsync_path="/r",
            s3_bucket="bkt",
        )
        response = test_client.post(
            "/api/apps/mysql_backups/", json=body, headers=BEARER_HEADERS
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()

    def test_create_rejects_skip_s3_safety_check_without_s3_upload(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """``skip_s3_safety_check=True`` with ``S3`` absent from ``upload`` → 422.

        Pins the per-field schema gate on the BoolField. With
        ``_field_is_present`` treating ``False`` as absent, the gate now
        fires only on an explicit ``True`` toggle, matching the
        ``validate_upload_provider_consistency`` model-validator path.
        """
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        body = build_backup_write_body(
            service_id=created_service.id,
            backup_type=BackupType.MYDUMPER,
            upload=["RSYNC"],
            rsync_path="/r",
            skip_s3_safety_check=True,
        )
        response = test_client.post(
            "/api/apps/mysql_backups/", json=body, headers=BEARER_HEADERS
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()

    def test_create_accepts_skip_s3_safety_check_default_with_non_s3_upload(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """Regression guard: ``skip_s3_safety_check`` defaults to ``False``.

        After the ``_field_is_present`` change, ``False`` is treated as absent
        so a non-S3 upload with the default bool value must still be accepted.
        """
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        mock_task_api_dep.post = AsyncMock(return_value=build_backup_task())
        body = build_backup_write_body(
            service_id=created_service.id,
            backup_type=BackupType.MYDUMPER,
            upload=["RSYNC"],
            rsync_path="/r",
            skip_s3_safety_check=False,
        )
        # Drop the S3 destination field carried by the default body.
        body.pop("s3_bucket", None)
        response = test_client.post(
            "/api/apps/mysql_backups/", json=body, headers=BEARER_HEADERS
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text

    def test_create_anonymous_returns_401(
        self, unauthenticated_client, mock_task_api_dep
    ):
        """Anonymous create is rejected by IsApiAuthenticated."""
        body = build_backup_write_body()
        response = unauthenticated_client.post("/api/apps/mysql_backups/", json=body)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestDeleteEndpoint:
    """Tests for DELETE /api/apps/mysql_backups/{task_name}."""

    def test_delete_returns_204(self, test_client, mock_task_api_dep):
        """Successful delete returns 204."""
        task = build_backup_task()

        async def _get(path, params=None, **_):
            return {"items": []} if path.endswith("/history/") else task

        mock_task_api_dep.get = AsyncMock(side_effect=_get)
        mock_task_api_dep.delete = AsyncMock()
        response = test_client.delete(
            f"/api/apps/mysql_backups/{task['name']}", headers=BEARER_HEADERS
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_task_api_dep.delete.assert_awaited_once_with(f"/{task['name']}")

    def test_delete_returns_404_for_missing(self, test_client, mock_task_api_dep):
        """Delete of unknown task returns 404."""
        response = test_client.delete(
            "/api/apps/mysql_backups/nope", headers=BEARER_HEADERS
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestExecuteEndpoint:
    """Tests for POST /api/apps/mysql_backups/{task_name}/execute."""

    def _execute_response(self, task_id: int = 99) -> dict:
        return {
            "id": task_id,
            "execution_request": {"task": "run-python", "target": "host1"},
            "task": {**build_backup_task(), "deleted_at": None},
        }

    def test_execute_returns_201(self, test_client, mock_task_api_dep):
        """Happy path: execute returns 201 with task_id."""
        task = build_backup_task()
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                {"items": [], "total": 0, "offset": 0, "limit": 50},  # running
                {"items": [], "total": 0, "offset": 0, "limit": 50},  # pending
                task,  # the framework task dep
            ]
        )
        mock_task_api_dep.post = AsyncMock(return_value=self._execute_response())
        response = test_client.post(
            f"/api/apps/mysql_backups/{task['name']}/execute",
            json={},
            headers=BEARER_HEADERS,
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text
        body = response.json()
        assert body["task_name"] == task["name"]
        assert body["task_id"] == 99  # noqa: PLR2004

    def test_execute_with_chain(self, test_client, mock_task_api_dep):
        """Chain args propagate to the Tasks API."""
        task = build_backup_task()
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                {"items": [], "total": 0, "offset": 0, "limit": 50},
                {"items": [], "total": 0, "offset": 0, "limit": 50},
                task,
            ]
        )
        mock_task_api_dep.post = AsyncMock(return_value=self._execute_response())
        response = test_client.post(
            f"/api/apps/mysql_backups/{task['name']}/execute",
            json={
                "chain_task_names": ["other-task"],
                "chain_on_failure": True,
            },
            headers=BEARER_HEADERS,
        )
        assert response.status_code == status.HTTP_201_CREATED
        _, kwargs = mock_task_api_dep.post.call_args
        assert kwargs["json"] == {
            "chain_task_names": ["other-task"],
            "chain_on_failure": True,
        }

    def test_execute_returns_404_for_missing(self, test_client, mock_task_api_dep):
        """Execute against an unknown task returns 404."""
        # 1, 2: HasNoConflictedRunningTasks (running, pending histories).
        # 3: the task dep fetches the task; unparseable response → 404
        #    via the same ValidationError → HTTPNotFoundException path used
        #    by the detail endpoint tests.
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                {"items": [], "total": 0, "offset": 0, "limit": 50},
                {"items": [], "total": 0, "offset": 0, "limit": 50},
                {},
            ]
        )
        response = test_client.post(
            "/api/apps/mysql_backups/nope/execute",
            json={},
            headers=BEARER_HEADERS,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_execute_with_cookie_only_returns_401(
        self, api_admin_client_no_bearer, mock_task_api_dep
    ):
        """Execute without Bearer header is rejected as 401."""
        response = api_admin_client_no_bearer.post(
            "/api/apps/mysql_backups/some-task/execute", json={}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["detail"] == BEARER_REQUIRED_DETAIL
        mock_task_api_dep.post.assert_not_called()


class TestBearerAuthGate:
    """Mutations must include an ``Authorization: Bearer`` header."""

    def test_create_with_cookie_only_returns_401(
        self, api_admin_client_no_bearer, mock_task_api_dep
    ):
        """POST without Bearer header is rejected as 401."""
        body = build_backup_write_body()
        response = api_admin_client_no_bearer.post(
            "/api/apps/mysql_backups/", json=body
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["detail"] == BEARER_REQUIRED_DETAIL
        mock_task_api_dep.post.assert_not_called()

    def test_delete_with_cookie_only_returns_401(
        self, api_admin_client_no_bearer, mock_task_api_dep
    ):
        """DELETE without Bearer header is rejected as 401."""
        response = api_admin_client_no_bearer.delete(
            "/api/apps/mysql_backups/some-task"
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["detail"] == BEARER_REQUIRED_DETAIL
        mock_task_api_dep.delete.assert_not_called()

    def test_list_with_cookie_only_returns_200(self, test_client, mock_task_api_dep):
        """Read endpoints still accept cookie-only auth."""
        mock_task_api_dep.get.return_value = {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": 50,
        }
        response = test_client.get("/api/apps/mysql_backups/")
        assert response.status_code == status.HTTP_200_OK
