# Copyright (C) 2025 Percona LLC
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

"""Define tests for the alerting methods of app.sep.clients.pmm."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, call, MagicMock

import pytest
from aiohttp import ClientResponse

from app.sep.clients.pmm import (
    AlertRule,
    AlertTemplate,
    ContactPoint,
    Folder,
    NotificationPolicy,
    PMMRemoteAPI,
)

ALERTING_HEADERS = {"X-Disable-Provenance": "true"}


@pytest.fixture
def pmm_remote_api() -> PMMRemoteAPI:
    """Return a PMMRemoteAPI instance."""
    return PMMRemoteAPI(endpoint="http://localhost", api_key="test-key")


@pytest.fixture
def mock_request(mocker) -> AsyncMock:
    """Mock the request method on PMMRemoteAPI."""
    return mocker.patch.object(PMMRemoteAPI, "request", new_callable=AsyncMock)


@pytest.fixture
def mock_get_version(mocker) -> AsyncMock:
    """Mock get_version on PMMRemoteAPI."""
    return mocker.patch(
        "app.sep.clients.pmm.PMMRemoteAPI.get_version", new_callable=AsyncMock
    )


class TestAlertingHeaders:
    """Test the alerting_headers property."""

    def test_alerting_headers_returns_x_disable_provenance(
        self, pmm_remote_api: PMMRemoteAPI
    ) -> None:
        """Test alerting_headers returns the X-Disable-Provenance header."""
        assert pmm_remote_api.alerting_headers == {"X-Disable-Provenance": "true"}


class TestCreateTemplate:
    """Test the create_template method."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("pmm_version", "expected_path"),
        [
            ("2.0.0", "/v1/management/alerting/Templates/Create"),
            ("3.0.0", "/v1/alerting/templates"),
        ],
    )
    async def test_create_template_calls_correct_endpoint(
        self,
        mock_request: AsyncMock,
        mock_get_version: AsyncMock,
        pmm_remote_api: PMMRemoteAPI,
        pmm_version: str,
        expected_path: str,
    ) -> None:
        """Test create_template uses the correct PMM v2/v3 endpoint."""
        mock_get_version.return_value = pmm_version
        mock_request.return_value = {
            "name": "cpu-high",
            "summary": "CPU usage is high",
            "template": "name: cpu-high\n",
        }

        result = await pmm_remote_api.create_template("name: cpu-high\n")

        assert isinstance(result, AlertTemplate)
        assert result.name == "cpu-high"
        assert result.summary == "CPU usage is high"
        mock_request.assert_awaited_once_with(
            "POST",
            expected_path,
            json={"yaml": "name: cpu-high\n"},
            headers=ALERTING_HEADERS,
        )
        pmm_remote_api.is_older_than_v3.cache_clear()


class TestListTemplates:
    """Test the list_templates method."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("pmm_version", "expected_method", "expected_path", "expected_kwargs"),
        [
            (
                "2.0.0",
                "POST",
                "/v1/management/alerting/Templates/List",
                {"json": {}, "headers": ALERTING_HEADERS},
            ),
            (
                "3.0.0",
                "GET",
                "/v1/alerting/templates",
                {
                    "params": {},
                    "headers": ALERTING_HEADERS,
                },
            ),
        ],
    )
    async def test_list_templates_calls_correct_endpoint(
        self,
        mock_request: AsyncMock,
        mock_get_version: AsyncMock,
        pmm_remote_api: PMMRemoteAPI,
        pmm_version: str,
        expected_method: str,
        expected_path: str,
        expected_kwargs: dict,
    ) -> None:
        """Test list_templates uses the correct PMM v2/v3 endpoint."""
        mock_get_version.return_value = pmm_version
        mock_request.return_value = {
            "templates": [
                {"name": "tmpl-1", "summary": "Summary 1", "template": "yaml1"},
                {"name": "tmpl-2", "summary": "Summary 2", "template": "yaml2"},
            ]
        }

        expected_template_count = 2

        result = await pmm_remote_api.list_templates()

        assert len(result) == expected_template_count
        assert all(isinstance(t, AlertTemplate) for t in result)
        assert result[0].name == "tmpl-1"
        assert result[1].name == "tmpl-2"
        mock_request.assert_awaited_once_with(
            expected_method, expected_path, **expected_kwargs
        )
        pmm_remote_api.is_older_than_v3.cache_clear()

    @pytest.mark.asyncio
    async def test_list_templates_returns_empty_list_when_no_templates(
        self,
        mock_request: AsyncMock,
        mock_get_version: AsyncMock,
        pmm_remote_api: PMMRemoteAPI,
    ) -> None:
        """Test list_templates returns empty list when response has no templates."""
        mock_get_version.return_value = "3.0.0"
        mock_request.return_value = {"templates": []}

        result = await pmm_remote_api.list_templates()

        assert result == []
        pmm_remote_api.is_older_than_v3.cache_clear()


class TestTemplateExists:
    """Test the template_exists method."""

    @pytest.mark.asyncio
    async def test_template_exists_returns_true_when_found(
        self, mocker, pmm_remote_api: PMMRemoteAPI
    ) -> None:
        """Test template_exists returns True when a matching template exists."""
        mocker.patch.object(
            PMMRemoteAPI,
            "list_templates",
            new=AsyncMock(
                return_value=[
                    AlertTemplate(name="target-template", summary="", template=""),
                    AlertTemplate(name="other-template", summary="", template=""),
                ]
            ),
        )

        result = await pmm_remote_api.template_exists("target-template")

        assert result is True

    @pytest.mark.asyncio
    async def test_template_exists_returns_false_when_not_found(
        self, mocker, pmm_remote_api: PMMRemoteAPI
    ) -> None:
        """Test template_exists returns False when no matching template exists."""
        mocker.patch.object(
            PMMRemoteAPI,
            "list_templates",
            new=AsyncMock(
                return_value=[
                    AlertTemplate(name="other-template", summary="", template=""),
                ]
            ),
        )

        result = await pmm_remote_api.template_exists("missing-template")

        assert result is False

    @pytest.mark.asyncio
    async def test_template_exists_returns_false_when_list_is_empty(
        self, mocker, pmm_remote_api: PMMRemoteAPI
    ) -> None:
        """Test template_exists returns False when template list is empty."""
        mocker.patch.object(
            PMMRemoteAPI,
            "list_templates",
            new=AsyncMock(return_value=[]),
        )

        result = await pmm_remote_api.template_exists("any-template")

        assert result is False


class TestCreateRule:
    """Test the create_rule method."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("pmm_version", "expected_path"),
        [
            ("2.0.0", "/v1/management/alerting/Rules/Create"),
            ("3.0.0", "/v1/alerting/rules"),
        ],
    )
    async def test_create_rule_calls_correct_endpoint(
        self,
        mock_request: AsyncMock,
        mock_get_version: AsyncMock,
        pmm_remote_api: PMMRemoteAPI,
        pmm_version: str,
        expected_path: str,
    ) -> None:
        """Test create_rule uses the correct PMM v2/v3 endpoint."""
        mock_get_version.return_value = pmm_version
        mock_request.return_value = {
            "uid": "rule-abc",
            "title": "High CPU",
            "labels": {"severity": "critical"},
            "annotations": {},
            "data": [],
        }

        result = await pmm_remote_api.create_rule(
            name="High CPU",
            template_name="cpu-high",
            folder_uid="folder-1",
            for_duration="5m",
            group="infra-alerts",
            labels={"severity": "critical"},
        )

        assert isinstance(result, AlertRule)
        assert result.uid == "rule-abc"
        assert result.title == "High CPU"
        mock_request.assert_awaited_once_with(
            "POST",
            expected_path,
            json={
                "name": "High CPU",
                "template_name": "cpu-high",
                "folder_uid": "folder-1",
                "for": "5m",
                "group": "infra-alerts",
                "labels": {"severity": "critical"},
            },
            headers=ALERTING_HEADERS,
        )
        pmm_remote_api.is_older_than_v3.cache_clear()

    @pytest.mark.asyncio
    async def test_create_rule_with_params(
        self,
        mock_request: AsyncMock,
        mock_get_version: AsyncMock,
        pmm_remote_api: PMMRemoteAPI,
    ) -> None:
        """Test create_rule includes params in the request body when provided."""
        mock_get_version.return_value = "3.0.0"
        mock_request.return_value = {
            "uid": "rule-xyz",
            "title": "Disk Full",
            "labels": {},
            "annotations": {},
            "data": [],
        }
        params = [{"name": "threshold", "type": "FLOAT", "float": "0.9"}]

        await pmm_remote_api.create_rule(
            name="Disk Full",
            template_name="disk-full",
            folder_uid="folder-1",
            for_duration="10m",
            group="disk-alerts",
            params=params,
        )

        call_json = mock_request.call_args.kwargs["json"]
        assert call_json["params"] == params
        pmm_remote_api.is_older_than_v3.cache_clear()

    @pytest.mark.asyncio
    async def test_create_rule_omits_none_labels_and_params(
        self,
        mock_request: AsyncMock,
        mock_get_version: AsyncMock,
        pmm_remote_api: PMMRemoteAPI,
    ) -> None:
        """Test create_rule omits labels and params from body when they are None."""
        mock_get_version.return_value = "3.0.0"
        mock_request.return_value = {
            "uid": "rule-min",
            "title": "Minimal Rule",
            "labels": {},
            "annotations": {},
            "data": [],
        }

        await pmm_remote_api.create_rule(
            name="Minimal Rule",
            template_name="tmpl",
            folder_uid="folder-1",
            for_duration="1m",
            group="group-1",
        )

        call_json = mock_request.call_args.kwargs["json"]
        assert "labels" not in call_json
        assert "params" not in call_json
        pmm_remote_api.is_older_than_v3.cache_clear()


class TestListRules:
    """Test the list_rules method."""

    @pytest.mark.asyncio
    async def test_list_rules_flattens_nested_response(
        self, mock_request: AsyncMock, pmm_remote_api: PMMRemoteAPI
    ) -> None:
        """Test list_rules flattens the nested folder/group/rules structure."""
        mock_request.return_value = {
            "folder-1": [
                {
                    "name": "group-1",
                    "rules": [
                        {
                            "grafana_alert": {
                                "uid": "rule-1",
                                "title": "Rule 1",
                                "labels": {"env": "prod"},
                                "annotations": {"summary": "Alert summary"},
                                "data": [{"refId": "A"}],
                            }
                        }
                    ],
                }
            ],
            "folder-2": [
                {
                    "name": "group-2",
                    "rules": [
                        {
                            "grafana_alert": {
                                "uid": "rule-2",
                                "title": "Rule 2",
                                "labels": {},
                                "annotations": {},
                                "data": [],
                            }
                        }
                    ],
                }
            ],
        }

        expected_rule_count = 2

        result = await pmm_remote_api.list_rules()

        assert len(result) == expected_rule_count
        assert all(isinstance(r, AlertRule) for r in result)
        uids = {r.uid for r in result}
        assert uids == {"rule-1", "rule-2"}
        rule1 = next(r for r in result if r.uid == "rule-1")
        assert rule1.title == "Rule 1"
        assert rule1.labels == {"env": "prod"}
        mock_request.assert_awaited_once_with(
            "GET",
            "/graph/api/ruler/grafana/api/v1/rules/",
            headers=ALERTING_HEADERS,
        )

    @pytest.mark.asyncio
    async def test_list_rules_returns_empty_list_when_no_rules(
        self, mock_request: AsyncMock, pmm_remote_api: PMMRemoteAPI
    ) -> None:
        """Test list_rules returns an empty list when the response is empty."""
        mock_request.return_value = {}

        result = await pmm_remote_api.list_rules()

        assert result == []


class TestDeleteRule:
    """Test the delete_rule method."""

    @pytest.mark.asyncio
    async def test_delete_rule_sends_delete_with_correct_uid_and_headers(
        self, mocker, pmm_remote_api: PMMRemoteAPI
    ) -> None:
        """Test delete_rule sends a DELETE request with the uid and alerting headers."""
        mock_response = MagicMock(spec=ClientResponse)
        mock_response.raise_for_status = MagicMock()
        captured = []

        @asynccontextmanager
        async def fake_request(self_arg, method: str, path: str, **kwargs):
            captured.append({"method": method, "path": path, "kwargs": kwargs})
            yield mock_response

        mocker.patch.object(PMMRemoteAPI, "_request", fake_request)

        await pmm_remote_api.delete_rule("rule-uid-123")

        assert len(captured) == 1
        assert captured[0]["method"] == "DELETE"
        assert (
            captured[0]["path"] == "/graph/api/v1/provisioning/alert-rules/rule-uid-123"
        )
        assert captured[0]["kwargs"].get("headers") == ALERTING_HEADERS
        mock_response.raise_for_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_rule_returns_none(
        self, mocker, pmm_remote_api: PMMRemoteAPI
    ) -> None:
        """Test delete_rule returns None on success."""
        mock_response = MagicMock(spec=ClientResponse)
        mock_response.raise_for_status = MagicMock()

        @asynccontextmanager
        async def fake_request(self_arg, method: str, path: str, **kwargs):
            yield mock_response

        mocker.patch.object(PMMRemoteAPI, "_request", fake_request)

        result = await pmm_remote_api.delete_rule("rule-uid-123")

        assert result is None


class TestUpdateRule:
    """Test the update_rule method."""

    @pytest.mark.asyncio
    async def test_update_rule_calls_delete_then_create_in_order(
        self, mocker, pmm_remote_api: PMMRemoteAPI
    ) -> None:
        """Test update_rule deletes the old rule then creates the new one, in order."""
        expected_rule = AlertRule(
            uid="new-uid",
            title="Updated Rule",
            labels={},
            annotations={},
            data=[],
        )
        manager = MagicMock()
        delete_mock = AsyncMock()
        create_mock = AsyncMock(return_value=expected_rule)
        manager.attach_mock(delete_mock, "delete_rule")
        manager.attach_mock(create_mock, "create_rule")

        mocker.patch.object(PMMRemoteAPI, "delete_rule", delete_mock)
        mocker.patch.object(PMMRemoteAPI, "create_rule", create_mock)

        result = await pmm_remote_api.update_rule(
            uid="old-uid",
            name="Updated Rule",
            template_name="tmpl",
            folder_uid="folder-1",
            for_duration="10m",
            group="group-1",
        )

        assert isinstance(result, AlertRule)
        assert result.uid == "new-uid"
        assert manager.mock_calls == [
            call.delete_rule("old-uid"),
            call.create_rule(
                name="Updated Rule",
                template_name="tmpl",
                folder_uid="folder-1",
                for_duration="10m",
                group="group-1",
                labels=None,
                params=None,
            ),
        ]


class TestListFolders:
    """Test the list_folders method."""

    @pytest.mark.asyncio
    async def test_list_folders_returns_folder_list(
        self, mock_request: AsyncMock, pmm_remote_api: PMMRemoteAPI
    ) -> None:
        """Test list_folders fetches and returns a list of Folder objects."""
        mock_request.return_value = [
            {"uid": "folder-1", "title": "Folder One", "id": 1},
            {"uid": "folder-2", "title": "Folder Two", "id": 2},
        ]

        expected_folder_count = 2

        result = await pmm_remote_api.list_folders()

        assert len(result) == expected_folder_count
        assert all(isinstance(f, Folder) for f in result)
        assert result[0].uid == "folder-1"
        assert result[0].title == "Folder One"
        assert result[0].id == 1
        mock_request.assert_awaited_once_with(
            "GET", "/graph/api/folders/", headers=ALERTING_HEADERS
        )


class TestCreateFolder:
    """Test the create_folder method."""

    @pytest.mark.asyncio
    async def test_create_folder_posts_and_returns_folder(
        self, mock_request: AsyncMock, pmm_remote_api: PMMRemoteAPI
    ) -> None:
        """Test create_folder sends POST and returns a Folder object."""
        mock_request.return_value = {
            "uid": "new-folder-uid",
            "title": "SEP Alerts",
            "id": 42,
        }

        expected_id = 42

        result = await pmm_remote_api.create_folder("SEP Alerts")

        assert isinstance(result, Folder)
        assert result.uid == "new-folder-uid"
        assert result.title == "SEP Alerts"
        assert result.id == expected_id
        mock_request.assert_awaited_once_with(
            "POST",
            "/graph/api/folders/",
            json={"title": "SEP Alerts"},
            headers=ALERTING_HEADERS,
        )


class TestListContactPoints:
    """Test the list_contact_points method."""

    @pytest.mark.asyncio
    async def test_list_contact_points_returns_contact_point_list(
        self, mock_request: AsyncMock, pmm_remote_api: PMMRemoteAPI
    ) -> None:
        """Test list_contact_points fetches and returns a list of ContactPoint objects."""
        mock_request.return_value = [
            {
                "uid": "cp-1",
                "name": "Slack",
                "type": "slack",
                "settings": {"url": "https://hooks.slack.com/test"},
            },
        ]

        result = await pmm_remote_api.list_contact_points()

        assert len(result) == 1
        assert isinstance(result[0], ContactPoint)
        assert result[0].uid == "cp-1"
        assert result[0].name == "Slack"
        assert result[0].type == "slack"
        mock_request.assert_awaited_once_with(
            "GET",
            "/graph/api/v1/provisioning/contact-points/",
            headers=ALERTING_HEADERS,
        )


class TestCreateContactPoint:
    """Test the create_contact_point method."""

    @pytest.mark.asyncio
    async def test_create_contact_point_posts_to_provisioning_endpoint(
        self, mock_request: AsyncMock, pmm_remote_api: PMMRemoteAPI
    ) -> None:
        """Test create_contact_point posts to the Grafana provisioning endpoint."""
        mock_request.return_value = {
            "uid": "cp-new",
            "name": "Email",
            "type": "email",
            "settings": {"addresses": "admin@example.com"},
        }

        result = await pmm_remote_api.create_contact_point(
            name="Email",
            type_="email",
            settings={"addresses": "admin@example.com"},
        )

        assert isinstance(result, ContactPoint)
        assert result.uid == "cp-new"
        assert result.type == "email"
        mock_request.assert_awaited_once_with(
            "POST",
            "/graph/api/v1/provisioning/contact-points/",
            json={
                "name": "Email",
                "type": "email",
                "settings": {"addresses": "admin@example.com"},
            },
            headers=ALERTING_HEADERS,
        )


class TestUpdateContactPoint:
    """Test the update_contact_point method."""

    @pytest.mark.asyncio
    async def test_update_contact_point_puts_to_provisioning_endpoint(
        self, mocker, pmm_remote_api: PMMRemoteAPI
    ) -> None:
        """Test update_contact_point sends a PUT with uid and alerting headers."""
        mock_response = MagicMock(spec=ClientResponse)
        mock_response.raise_for_status = MagicMock()
        captured = []

        @asynccontextmanager
        async def fake_request(self_arg, method: str, path: str, **kwargs):
            captured.append({"method": method, "path": path, "kwargs": kwargs})
            yield mock_response

        mocker.patch.object(PMMRemoteAPI, "_request", fake_request)

        await pmm_remote_api.update_contact_point(
            uid="cp-123",
            name="Updated Email",
            type_="email",
            settings={"addresses": "new@example.com"},
        )

        assert len(captured) == 1
        assert captured[0]["method"] == "PUT"
        assert captured[0]["path"] == "/graph/api/v1/provisioning/contact-points/cp-123"
        assert captured[0]["kwargs"].get("json") == {
            "uid": "cp-123",
            "name": "Updated Email",
            "type": "email",
            "settings": {"addresses": "new@example.com"},
        }
        assert captured[0]["kwargs"].get("headers") == ALERTING_HEADERS
        mock_response.raise_for_status.assert_called_once()


class TestGetNotificationPolicy:
    """Test the get_notification_policy method."""

    @pytest.mark.asyncio
    async def test_get_notification_policy_returns_policy(
        self, mock_request: AsyncMock, pmm_remote_api: PMMRemoteAPI
    ) -> None:
        """Test get_notification_policy fetches and returns the policy tree."""
        mock_request.return_value = {
            "receiver": "grafana-default-email",
            "group_by": ["alertname"],
            "routes": [{"receiver": "slack", "match": {"severity": "critical"}}],
        }

        result = await pmm_remote_api.get_notification_policy()

        assert isinstance(result, NotificationPolicy)
        assert result.receiver == "grafana-default-email"
        assert result.group_by == ["alertname"]
        assert len(result.routes) == 1
        mock_request.assert_awaited_once_with(
            "GET", "/graph/api/v1/provisioning/policies", headers=ALERTING_HEADERS
        )


class TestUpdateNotificationPolicy:
    """Test the update_notification_policy method."""

    @pytest.mark.asyncio
    async def test_update_notification_policy_puts_serialized_policy(
        self, mock_request: AsyncMock, pmm_remote_api: PMMRemoteAPI
    ) -> None:
        """Test update_notification_policy sends a PUT with the serialized policy."""
        policy = NotificationPolicy(
            receiver="slack",
            group_by=["alertname", "cluster"],
            routes=[{"receiver": "pagerduty", "match": {"severity": "critical"}}],
        )
        mock_request.return_value = {
            "receiver": "slack",
            "group_by": ["alertname", "cluster"],
            "routes": [{"receiver": "pagerduty", "match": {"severity": "critical"}}],
        }

        result = await pmm_remote_api.update_notification_policy(policy)

        assert isinstance(result, NotificationPolicy)
        assert result.receiver == "slack"
        mock_request.assert_awaited_once_with(
            "PUT",
            "/graph/api/v1/provisioning/policies",
            json=policy.model_dump(exclude_none=True),
            headers=ALERTING_HEADERS,
        )
