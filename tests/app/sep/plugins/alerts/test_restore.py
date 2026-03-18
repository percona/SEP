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

"""Define tests for restore from backup functionality."""

from unittest.mock import AsyncMock

import pytest
from fastapi import status
from fastapi.exceptions import HTTPException

from app.sep.clients.pmm import (
    AlertRule,
    ContactPoint,
    NotificationPolicy,
    PMMRemoteAPI,
)
from app.sep.clients.pmm import (
    AlertTemplate as PMMAlertTemplate,
)
from app.sep.plugins.alerts.backup import AlertBackup
from app.sep.plugins.alerts.restore import restore_from_backup

_SAMPLE_TEMPLATE_COUNT = 2
_SAMPLE_CONTACT_POINT_COUNT = 2


def _sample_backup_data():
    """Return sample backup data for testing."""
    return {
        "templates": [
            {"name": "t1", "summary": "Template 1", "template": "yaml1"},
            {"name": "t2", "summary": "Template 2", "template": "yaml2"},
        ],
        "rules": [
            {
                "uid": "r1",
                "title": "Rule 1",
                "labels": {"template_name": "t1"},
                "folder_uid": "f1",
                "for": "5m",
                "group": "SEP Alerts",
            },
        ],
        "contact_points": [
            {
                "uid": "cp1",
                "name": "Email",
                "type": "email",
                "settings": {"to": "a@b.com"},
            },
            {
                "uid": "cp2",
                "name": "Slack",
                "type": "slack",
                "settings": {"url": "https://hooks.slack.com/x"},
            },
        ],
        "notification_policies": {
            "receiver": "Email",
            "group_by": ["alertname"],
            "routes": [],
        },
        "folders": [
            {"uid": "f1", "title": "Folder 1", "id": 1},
        ],
    }


class TestRestoreFromBackup:
    """Test the ``restore_from_backup`` helper function."""

    @pytest.mark.asyncio
    async def test_full_restore(self):
        """Assert all resource types are restored with correct counts."""
        mock_api = AsyncMock(spec=PMMRemoteAPI)
        mock_api.list_rules.return_value = [
            AlertRule(uid="existing1", title="Old Rule"),
        ]
        mock_api.template_exists.side_effect = [False, True]
        mock_api.create_template.return_value = PMMAlertTemplate(
            name="t1", summary="Template 1", template="yaml1"
        )
        mock_api.create_rule.return_value = AlertRule(uid="new1", title="Rule 1")
        mock_api.list_contact_points.return_value = [
            ContactPoint(uid="existing-cp", name="Email", type="email"),
        ]
        mock_api.update_notification_policy.return_value = NotificationPolicy(
            receiver="Email"
        )

        backup = AlertBackup(
            id=1,
            data=_sample_backup_data(),
            metadata_={"template_count": 2, "rule_count": 1},
        )

        results = await restore_from_backup(mock_api, backup)

        assert results["rules_deleted"] == 1
        assert results["templates"]["created"] == 1
        assert results["templates"]["skipped"] == 1
        assert results["rules_created"] == 1
        assert results["contact_points"]["created"] == 1
        assert results["contact_points"]["updated"] == 1
        assert results["notification_policies"] == "restored"

        mock_api.delete_rule.assert_awaited_once_with("existing1")
        mock_api.create_rule.assert_awaited_once()
        mock_api.update_contact_point.assert_awaited_once()
        mock_api.create_contact_point.assert_awaited_once()
        mock_api.update_notification_policy.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_templates_all_skipped_when_existing(self):
        """Assert existing templates are skipped and not recreated."""
        mock_api = AsyncMock(spec=PMMRemoteAPI)
        mock_api.list_rules.return_value = []
        mock_api.template_exists.return_value = True
        mock_api.list_contact_points.return_value = []

        backup = AlertBackup(
            id=1,
            data=_sample_backup_data(),
            metadata_={},
        )

        results = await restore_from_backup(mock_api, backup)

        assert results["templates"]["created"] == 0
        assert results["templates"]["skipped"] == _SAMPLE_TEMPLATE_COUNT
        mock_api.create_template.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_contact_points_upserted(self):
        """Assert existing contact points are updated and new ones created."""
        mock_api = AsyncMock(spec=PMMRemoteAPI)
        mock_api.list_rules.return_value = []
        mock_api.template_exists.return_value = True
        mock_api.list_contact_points.return_value = [
            ContactPoint(uid="existing-cp", name="Email", type="email"),
            ContactPoint(uid="existing-cp2", name="Slack", type="slack"),
        ]

        backup = AlertBackup(
            id=1,
            data=_sample_backup_data(),
            metadata_={},
        )

        results = await restore_from_backup(mock_api, backup)

        assert results["contact_points"]["updated"] == _SAMPLE_CONTACT_POINT_COUNT
        assert results["contact_points"]["created"] == 0

    @pytest.mark.asyncio
    async def test_empty_backup_data(self):
        """Assert an empty backup produces zero counts without errors."""
        mock_api = AsyncMock(spec=PMMRemoteAPI)
        mock_api.list_rules.return_value = []
        mock_api.list_contact_points.return_value = []

        backup = AlertBackup(
            id=1,
            data={},
            metadata_={},
        )

        results = await restore_from_backup(mock_api, backup)

        assert results["rules_deleted"] == 0
        assert results["templates"]["created"] == 0
        assert results["templates"]["skipped"] == 0
        assert results["rules_created"] == 0
        assert results["contact_points"]["created"] == 0
        assert results["contact_points"]["updated"] == 0
        assert results["notification_policies"] == "skipped"

    @pytest.mark.asyncio
    async def test_no_notification_policies(self):
        """Assert restore skips notification policies when not in backup."""
        mock_api = AsyncMock(spec=PMMRemoteAPI)
        mock_api.list_rules.return_value = []
        mock_api.list_contact_points.return_value = []

        backup = AlertBackup(
            id=1,
            data={"templates": [], "rules": [], "contact_points": []},
            metadata_={},
        )

        results = await restore_from_backup(mock_api, backup)

        assert results["notification_policies"] == "skipped"
        mock_api.update_notification_policy.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_api_error_propagates(self):
        """Assert API errors are not silenced during restore."""
        mock_api = AsyncMock(spec=PMMRemoteAPI)
        mock_api.list_rules.side_effect = HTTPException(
            status_code=502, detail="Bad Gateway"
        )

        backup = AlertBackup(
            id=1,
            data=_sample_backup_data(),
            metadata_={},
        )

        with pytest.raises(HTTPException):
            await restore_from_backup(mock_api, backup)


class TestRestoreRoute:
    """Test the POST /alerts/restore route."""

    @pytest.fixture
    def _mock_pmm_api_dep(self):
        """Override the PMM API dependency."""
        from app.sep.main import sep_app
        from app.sep.plugins.alerts.deps import get_pmm_api

        mock_api = AsyncMock(spec=PMMRemoteAPI)
        mock_api.list_rules.return_value = []
        mock_api.template_exists.return_value = False
        mock_api.create_template.return_value = PMMAlertTemplate(
            name="t1", summary="s", template="y"
        )
        mock_api.create_rule.return_value = AlertRule(uid="r1", title="Rule 1")
        mock_api.list_contact_points.return_value = []
        mock_api.update_notification_policy.return_value = NotificationPolicy(
            receiver="default"
        )
        sep_app.dependency_overrides[get_pmm_api] = lambda: mock_api
        yield mock_api
        sep_app.dependency_overrides = {}

    @pytest.fixture
    def _mock_pmm_api_none_dep(self):
        """Override the PMM API dependency to return None."""
        from app.sep.main import sep_app
        from app.sep.plugins.alerts.deps import get_pmm_api

        sep_app.dependency_overrides[get_pmm_api] = lambda: None
        yield
        sep_app.dependency_overrides = {}

    @pytest.fixture
    def _mock_backup_get(self, mocker):
        """Mock AlertBackupManager.get_or_404 to return a sample backup."""
        backup = AlertBackup(
            id=1,
            data=_sample_backup_data(),
            metadata_={"template_count": 2, "rule_count": 1},
        )
        mocker.patch(
            "app.sep.plugins.alerts.routes.AlertBackupManager.get_or_404",
            new=AsyncMock(return_value=backup),
        )

    @pytest.fixture
    def _mock_backup_not_found(self, mocker):
        """Mock AlertBackupManager.get_or_404 to raise 404."""
        from app.core.exceptions import HTTPNotFoundException

        mocker.patch(
            "app.sep.plugins.alerts.routes.AlertBackupManager.get_or_404",
            new=AsyncMock(side_effect=HTTPNotFoundException()),
        )

    @pytest.mark.usefixtures("_mock_pmm_api_dep", "_mock_backup_get")
    def test_restore_success(self, test_client):
        """Assert POST /alerts/restore returns success JSON."""
        response = test_client.post(
            "/alerts/restore",
            data={"backup_id": "1"},
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status"] == "success"
        assert "details" in body

    @pytest.mark.usefixtures("_mock_pmm_api_none_dep")
    def test_restore_pmm_not_configured(self, test_client):
        """Assert 503 when PMM is not configured."""
        response = test_client.post(
            "/alerts/restore",
            data={"backup_id": "1"},
        )
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "PMM is not configured" in response.json()["message"]

    @pytest.mark.usefixtures("_mock_pmm_api_dep", "_mock_backup_not_found")
    def test_restore_backup_not_found(self, test_client):
        """Assert 502 JSON error when backup_id does not exist."""
        response = test_client.post(
            "/alerts/restore",
            data={"backup_id": "999"},
        )
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        body = response.json()
        assert body["status"] == "error"

    @pytest.mark.usefixtures("_mock_pmm_api_dep", "_mock_backup_get")
    def test_restore_pmm_api_error(self, test_client, mocker):
        """Assert 502 when PMM API fails during restore."""
        mocker.patch(
            "app.sep.plugins.alerts.routes.restore_from_backup",
            new=AsyncMock(
                side_effect=HTTPException(status_code=502, detail="Bad Gateway")
            ),
        )
        response = test_client.post(
            "/alerts/restore",
            data={"backup_id": "1"},
        )
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        body = response.json()
        assert body["status"] == "error"


class TestBackupListRoute:
    """Test the GET /alerts/backups route."""

    @pytest.fixture(autouse=True)
    def _mock_session_dep(self):
        """Override the session dependency to avoid needing a real DB."""
        from app.sep.deps import get_session
        from app.sep.main import sep_app

        async def _mock_session():
            return AsyncMock()

        sep_app.dependency_overrides[get_session] = _mock_session
        yield
        sep_app.dependency_overrides = {}

    @pytest.fixture
    def _mock_backup_list(self, mocker):
        """Mock AlertBackupManager.list to return sample backups."""
        backups = [
            AlertBackup(
                id=i,
                data={},
                metadata_={"template_count": i, "rule_count": i},
            )
            for i in range(1, 4)
        ]
        mocker.patch(
            "app.sep.plugins.alerts.routes.AlertBackupManager.list",
            new=AsyncMock(return_value=backups),
        )

    @pytest.mark.usefixtures("_mock_backup_list", "mock_get_username_mapping")
    def test_backup_list_endpoint(self, test_client):
        """Assert GET /alerts/backups returns 200 with backup data."""
        response = test_client.get("/alerts/backups")
        assert response.status_code == status.HTTP_200_OK
        assert response.headers["content-type"] == "text/html; charset=utf-8"


class TestGetRecentBackups:
    """Test the ``get_recent_backups`` dependency."""

    @pytest.mark.asyncio
    async def test_returns_backups_from_manager(self, mocker):
        """Assert recent backups are fetched via AlertBackupManager.list."""
        from app.sep.plugins.alerts.deps import get_recent_backups

        backups = [AlertBackup(id=i, data={}, metadata_={}) for i in range(1, 6)]
        mock_list = AsyncMock(return_value=backups)
        mocker.patch(
            "app.sep.plugins.alerts.deps.AlertBackupManager.list",
            new=mock_list,
        )
        mock_session = AsyncMock()

        result = await get_recent_backups(mock_session)

        assert result == backups
        mock_list.assert_awaited_once_with(mock_session)

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_backups(self, mocker):
        """Assert an empty list is returned when no backups exist."""
        from app.sep.plugins.alerts.deps import get_recent_backups

        mock_list = AsyncMock(return_value=[])
        mocker.patch(
            "app.sep.plugins.alerts.deps.AlertBackupManager.list",
            new=mock_list,
        )
        mock_session = AsyncMock()

        result = await get_recent_backups(mock_session)

        assert result == []
