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

"""Define HTTP integration tests for the alerts plugin JSON API routes."""

from collections.abc import Iterator, Mapping
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import status
from fastapi.exceptions import HTTPException
from fastapi.testclient import TestClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import HTTPNotFoundException
from app.sep.apps.alerts.crud import AlertBackupManager
from app.sep.apps.alerts.deps import (
    get_alert_templates,
    get_or_create_alert_folder,
    get_pmm_api,
    get_pmm_present_names,
)
from app.sep.apps.alerts.models import (
    AlertBackup,
    AlertSeverity,
    AlertTemplate,
    ServiceType,
)
from app.sep.clients.pmm import (
    AlertRule,
    ContactPoint,
    Folder,
    NotificationPolicy,
    PMMRemoteAPI,
)
from app.sep.deps import get_session, require_bearer_for_unsafe_methods
from app.sep.main import sep_app

API_BASE = "/api/apps/alerts"
BEARER_HEADERS = {"Authorization": "Bearer test-token"}
#: The parent of every logger the request path emits through. Naming it keeps the
#: "no record carries the secret" assertions from passing on an empty capture.
_APP_LOGGER = "app"


_TEMPLATE_A = AlertTemplate(
    name="High CPU",
    service_type=ServiceType.GENERIC,
    expression="cpu > 80",
    default_threshold=80.0,
    severity=AlertSeverity.WARNING,
    description="CPU usage is above threshold.",
    summary="High CPU on {{ $labels.instance }}",
)

_TEMPLATE_B = AlertTemplate(
    name="Disk Full",
    service_type=ServiceType.GENERIC,
    expression="disk_used_percent > 90",
    default_threshold=90.0,
    severity=AlertSeverity.CRITICAL,
    description="Disk usage is above threshold.",
    summary="Disk full on {{ $labels.instance }}",
)

_ALERT_TEMPLATES: Mapping[ServiceType, tuple[AlertTemplate, ...]] = {
    ServiceType.GENERIC: (_TEMPLATE_A, _TEMPLATE_B),
    ServiceType.MYSQL: (),
    ServiceType.MONGODB: (),
    ServiceType.POSTGRESQL: (),
}

_FOLDER = Folder(uid="folder-1", title="SEP Alerts", id=1)


@pytest.fixture
def api_client(test_client: TestClient, session: AsyncSession) -> TestClient:
    """Return an authenticated TestClient wired to the in-memory test session.

    Set a default ``Authorization: Bearer`` header so requests satisfy the
    framework-level ``RequireBearerForUnsafeMethods`` guard on the
    ``/api/apps`` router — the guard inspects the raw request
    header, not the (overridden) user dep, so without this header cookie-only
    mutations would (correctly) 401.
    """
    sep_app.dependency_overrides[get_session] = lambda: session
    test_client.headers["Authorization"] = BEARER_HEADERS["Authorization"]
    return test_client


@pytest.fixture
def cookie_only_api_client(
    test_client: TestClient, session: AsyncSession
) -> TestClient:
    """Return a cookie-authenticated TestClient with NO Bearer header.

    Used to assert that mutating routes reject cookie-only callers (CSRF
    guard via framework-level ``RequireBearerForUnsafeMethods`` on the
    ``/api/apps`` router). The shared ``test_client`` fixture overrides
    the framework Bearer guard to a no-op so cookie auth works in tests; pop
    that override here so the real guard runs and the 401 path is exercised.
    """
    sep_app.dependency_overrides[get_session] = lambda: session
    sep_app.dependency_overrides.pop(require_bearer_for_unsafe_methods, None)
    test_client.headers.pop("Authorization", None)
    return test_client


@pytest.fixture
def unauthenticated_api_client(session: AsyncSession) -> Iterator[TestClient]:
    """Yield a TestClient with no auth overrides — API calls should 401."""
    sep_app.dependency_overrides[get_session] = lambda: session
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest.fixture
def mock_pmm_api(api_client: TestClient) -> AsyncMock:
    """Return a mock PMMRemoteAPI wired into dependency overrides."""
    mock = AsyncMock(spec=PMMRemoteAPI)
    mock.list_folders.return_value = [_FOLDER]
    mock.list_templates.return_value = []
    mock.create_template.return_value = AsyncMock()
    mock.create_rule.return_value = AsyncMock()
    sep_app.dependency_overrides[get_pmm_api] = lambda: mock
    sep_app.dependency_overrides[get_alert_templates] = lambda: _ALERT_TEMPLATES
    sep_app.dependency_overrides[get_or_create_alert_folder] = lambda: _FOLDER
    sep_app.dependency_overrides[get_pmm_present_names] = lambda: set()
    return mock


@pytest.fixture
def _mock_pmm_unavailable(api_client: TestClient) -> None:
    """Override the PMM API dependency to return ``None`` — should yield 503."""
    sep_app.dependency_overrides[get_pmm_api] = lambda: None


@pytest_asyncio.fixture
async def seeded_backup(session: AsyncSession) -> AlertBackup:
    """Insert one backup row with a representative payload."""
    backup = AlertBackup(
        data={
            "templates": [{"name": "High CPU", "summary": "summary-a"}],
            "rules": [{"title": "High CPU"}],
            "contact_points": [
                {
                    "name": "SEP PagerDuty",
                    "type": "pagerduty",
                    "settings": {"integrationKey": "k"},
                }
            ],
            "folders": [{"title": "SEP Alerts"}],
            "notification_policy": {"receiver": "default", "routes": []},
        },
        metadata_={"templates": 1, "rules": 1, "contact_points": 1, "folders": 1},
    )
    return await AlertBackupManager.create(session, backup)


class TestAlertsIndexApi:
    """Tests for the ``GET /`` index endpoint backing the React list page."""

    def test_index_returns_groups_status_and_backups(
        self, api_client, mock_pmm_api, seeded_backup
    ):
        """Aggregate templates, PMM connectivity, PagerDuty status, and backups."""
        mock_pmm_api.list_contact_points.return_value = []

        response = api_client.get(f"{API_BASE}/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # Only the GENERIC service type has templates in the fixture; empty
        # groups are filtered out.
        assert [g["service_type"] for g in data["groups"]] == ["generic"]
        generic = data["groups"][0]
        assert generic["label"] == "Generic"
        assert {t["name"] for t in generic["templates"]} == {"High CPU", "Disk Full"}
        # present_names is an empty set (PMM reachable, nothing pushed yet).
        assert all(t["in_pmm"] is False for t in generic["templates"])
        assert data["pmm_connected"] is True
        assert data["pagerduty"] == {"configured": False, "uid": None}
        assert [b["id"] for b in data["recent_backups"]] == [seeded_backup.id]

    def test_index_marks_templates_present_in_pmm(self, api_client, mock_pmm_api):
        """Flag ``in_pmm`` for templates whose names are already present in PMM."""
        mock_pmm_api.list_contact_points.return_value = []
        sep_app.dependency_overrides[get_pmm_present_names] = lambda: {"High CPU"}

        response = api_client.get(f"{API_BASE}/")

        assert response.status_code == status.HTTP_200_OK
        present = {
            t["name"]: t["in_pmm"] for t in response.json()["groups"][0]["templates"]
        }
        assert present == {"High CPU": True, "Disk Full": False}

    def test_index_reports_configured_pagerduty(self, api_client, mock_pmm_api):
        """Surface the PagerDuty UID when a SEP contact point exists."""
        mock_pmm_api.list_contact_points.return_value = [
            ContactPoint(
                uid="cp-1",
                name="SEP PagerDuty",
                type="pagerduty",
                settings={"integrationKey": "k"},
            ),
        ]

        response = api_client.get(f"{API_BASE}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["pagerduty"] == {"configured": True, "uid": "cp-1"}

    @pytest.mark.usefixtures("_mock_pmm_unavailable")
    def test_index_degrades_when_pmm_unavailable(self, api_client):
        """Report ``pmm_connected=False`` and null PagerDuty when PMM is down."""
        sep_app.dependency_overrides[get_alert_templates] = lambda: _ALERT_TEMPLATES

        response = api_client.get(f"{API_BASE}/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["pmm_connected"] is False
        assert data["pagerduty"] is None
        assert all(t["in_pmm"] is False for g in data["groups"] for t in g["templates"])


class TestApiAuthentication:
    """Assert each JSON endpoint requires authentication."""

    def test_index_requires_auth(self, unauthenticated_api_client):
        """Reject unauthenticated GET / with 401."""
        response = unauthenticated_api_client.get(f"{API_BASE}/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_list_backups_requires_auth(self, unauthenticated_api_client):
        """Reject unauthenticated GET /backups with 401."""
        response = unauthenticated_api_client.get(f"{API_BASE}/backups")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_backup_detail_requires_auth(self, unauthenticated_api_client):
        """Reject unauthenticated GET /backups/{id} with 401."""
        response = unauthenticated_api_client.get(f"{API_BASE}/backups/1")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_restore_requires_auth(self, unauthenticated_api_client):
        """Reject unauthenticated POST /restore with 401."""
        response = unauthenticated_api_client.post(
            f"{API_BASE}/restore", json={"backup_id": 1}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_pagerduty_save_requires_auth(self, unauthenticated_api_client):
        """Reject unauthenticated POST /pagerduty with 401."""
        response = unauthenticated_api_client.post(
            f"{API_BASE}/pagerduty", json={"integration_key": "k"}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_pagerduty_delete_requires_auth(self, unauthenticated_api_client):
        """Reject unauthenticated POST /pagerduty/delete with 401."""
        response = unauthenticated_api_client.post(f"{API_BASE}/pagerduty/delete")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_push_requires_auth(self, unauthenticated_api_client):
        """Reject unauthenticated POST /push with 401."""
        response = unauthenticated_api_client.post(
            f"{API_BASE}/push", json={"selected_templates": ["x"]}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_restore_rejects_malformed_bearer_header(self, cookie_only_api_client):
        """Reject an Authorization header that is not ``Bearer <token>``.

        The framework-level Bearer guard inspects the raw header prefix; a
        non-Bearer scheme (e.g. ``Basic``, ``NotBearer``) must surface as
        401, never as a 500 or a silent pass-through.
        """
        cookie_only_api_client.headers["Authorization"] = "NotBearer abc"
        response = cookie_only_api_client.post(
            f"{API_BASE}/restore", json={"backup_id": 1}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Bearer authentication required" in response.json()["detail"]


class TestApiInputHardening:
    """Pin abuse-shaped input contracts: oversize, control chars, echo-back."""

    def test_push_handles_extremely_long_template_name(self, api_client, mock_pmm_api):
        """Treat a 10 KiB template name as a plain unknown template (no 500).

        Guards against unbounded lookup paths or accidental DoS via giant
        request bodies — the unknown name must funnel through the standard
        ``"Template not found"`` branch.
        """
        huge_name = "x" * 10_000
        response = api_client.post(
            f"{API_BASE}/push", json={"selected_templates": [huge_name]}
        )
        assert response.status_code == status.HTTP_200_OK
        result = response.json()["results"][0]
        assert result["status"] == "error"
        assert result["message"] == "Template not found"
        mock_pmm_api.create_template.assert_not_awaited()

    def test_pagerduty_integration_key_with_control_chars_not_echoed(
        self, api_client, mock_pmm_api, caplog
    ):
        """Forward a control-char-laden key to PMM without echoing or logging it.

        ``NonEmptyStr`` does not strip control characters, so the value passes
        validation. The contract is: the key is forwarded verbatim to the PMM
        client, but never appears in the response body or in any log record.
        """
        mock_pmm_api.list_contact_points.return_value = []
        mock_pmm_api.create_contact_point.return_value = ContactPoint(
            uid="new", name="SEP PagerDuty", type="pagerduty", settings={}
        )
        mock_pmm_api.get_notification_policy.return_value = NotificationPolicy(
            receiver="default", routes=[]
        )
        bad_key = "key\x00\nctrl"
        with caplog.at_level("DEBUG", logger=_APP_LOGGER):
            response = api_client.post(
                f"{API_BASE}/pagerduty", json={"integration_key": bad_key}
            )
        assert response.status_code == status.HTTP_200_OK
        assert bad_key not in response.text
        for record in caplog.records:
            assert bad_key not in record.getMessage()
        forwarded_settings = mock_pmm_api.create_contact_point.call_args[0][2]
        assert forwarded_settings == {"integrationKey": bad_key}


class TestBearerAuthGate:
    """Cookie-authenticated mutations must be rejected without a Bearer token.

    ``IsApiAuthenticated`` alone accepts cookie auth — the ``/api`` tier has
    no CSRF check, so without the framework-level
    ``RequireBearerForUnsafeMethods`` guard a logged-in browser could be
    CSRF'd into mutating PMM state from a malicious origin.
    """

    def test_restore_with_cookie_only_returns_401(self, cookie_only_api_client):
        """Reject cookie-only POST /restore (no Bearer) with 401."""
        response = cookie_only_api_client.post(
            f"{API_BASE}/restore", json={"backup_id": 1}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Bearer authentication required" in response.json()["detail"]

    def test_pagerduty_save_with_cookie_only_returns_401(self, cookie_only_api_client):
        """Reject cookie-only POST /pagerduty (no Bearer) with 401."""
        response = cookie_only_api_client.post(
            f"{API_BASE}/pagerduty", json={"integration_key": "k"}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Bearer authentication required" in response.json()["detail"]

    def test_pagerduty_delete_with_cookie_only_returns_401(
        self, cookie_only_api_client
    ):
        """Reject cookie-only POST /pagerduty/delete (no Bearer) with 401."""
        response = cookie_only_api_client.post(f"{API_BASE}/pagerduty/delete")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Bearer authentication required" in response.json()["detail"]

    def test_push_with_cookie_only_returns_401(self, cookie_only_api_client):
        """Reject cookie-only POST /push (no Bearer) with 401."""
        response = cookie_only_api_client.post(
            f"{API_BASE}/push", json={"selected_templates": ["x"]}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Bearer authentication required" in response.json()["detail"]

    def test_list_backups_with_cookie_only_returns_200(
        self, cookie_only_api_client, session: AsyncSession
    ):
        """Allow cookie-only GET /backups (no Bearer) — reads carry no CSRF risk."""
        response = cookie_only_api_client.get(f"{API_BASE}/backups")
        assert response.status_code == status.HTTP_200_OK

    def test_backup_detail_with_cookie_only_returns_404(self, cookie_only_api_client):
        """Allow cookie-only GET /backups/{id} (no Bearer) past the auth gate.

        Reach the handler — a missing-row 404 (not 401) confirms the read
        path accepts cookie-only auth.
        """
        response = cookie_only_api_client.get(f"{API_BASE}/backups/9999")
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
class TestListBackups:
    """Tests for the list-backups endpoint."""

    async def test_returns_empty_page_when_no_backups(self, api_client):
        """Return an empty paginated envelope when no backups exist."""
        response = api_client.get(f"{API_BASE}/backups")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["items"] == []
        assert body["total"] == 0
        assert body["offset"] == 0
        assert body["limit"] > 0

    async def test_returns_recent_backups_ordered_desc(
        self, api_client, session: AsyncSession
    ):
        """Return backups ordered by id descending (created_at tiebreak)."""
        await AlertBackupManager.create(
            session, AlertBackup(data={}, metadata_={"templates": 1})
        )
        await AlertBackupManager.create(
            session, AlertBackup(data={}, metadata_={"templates": 2})
        )
        response = api_client.get(f"{API_BASE}/backups")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        items = body["items"]
        assert len(items) == 2  # noqa: PLR2004
        assert items[0]["id"] > items[1]["id"]
        assert items[0]["metadata"] == {"templates": 2}
        assert body["total"] == 2  # noqa: PLR2004
        assert body["offset"] == 0

    async def test_respects_limit_query_param(self, api_client, session: AsyncSession):
        """Clamp the result count to the requested ``limit``."""
        for _ in range(3):
            await AlertBackupManager.create(session, AlertBackup(data={}, metadata_={}))
        response = api_client.get(f"{API_BASE}/backups", params={"limit": 2})
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert len(body["items"]) == 2  # noqa: PLR2004
        assert body["total"] == 3  # noqa: PLR2004
        assert body["limit"] == 2  # noqa: PLR2004

    async def test_respects_offset_query_param(self, api_client, session: AsyncSession):
        """Skip the first ``offset`` rows of the ordered listing."""
        for _ in range(3):
            await AlertBackupManager.create(session, AlertBackup(data={}, metadata_={}))
        full = api_client.get(f"{API_BASE}/backups").json()["items"]
        response = api_client.get(
            f"{API_BASE}/backups", params={"offset": 1, "limit": 2}
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["offset"] == 1
        assert body["total"] == 3  # noqa: PLR2004
        ids = [item["id"] for item in body["items"]]
        assert ids == [full[1]["id"], full[2]["id"]]

    async def test_rejects_offset_negative(self, api_client):
        """Reject offset < 0 with 422."""
        response = api_client.get(f"{API_BASE}/backups", params={"offset": -1})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_rejects_limit_out_of_range_low(self, api_client):
        """Reject limit < 1 with 422."""
        response = api_client.get(f"{API_BASE}/backups", params={"limit": 0})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_rejects_limit_out_of_range_high(self, api_client):
        """Reject limit > 100 with 422 to bound the response size."""
        response = api_client.get(f"{API_BASE}/backups", params={"limit": 101})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_handles_missing_metadata_gracefully(
        self, api_client, session: AsyncSession
    ):
        """Return an empty metadata dict when the backup has none."""
        await AlertBackupManager.create(session, AlertBackup(data={}, metadata_={}))
        response = api_client.get(f"{API_BASE}/backups")
        assert response.status_code == status.HTTP_200_OK
        items = response.json()["items"]
        assert items[0]["metadata"] == {}


@pytest.mark.asyncio
class TestBackupDetail:
    """Tests for the backup-detail endpoint."""

    async def test_returns_backup_detail(self, api_client, seeded_backup: AlertBackup):
        """Return the full categorised backup detail."""
        response = api_client.get(f"{API_BASE}/backups/{seeded_backup.id}")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["id"] == seeded_backup.id
        assert body["templates"][0]["name"] == "High CPU"
        assert body["rules"][0]["title"] == "High CPU"
        assert body["contact_points"][0]["name"] == "SEP PagerDuty"
        assert body["folders"][0]["title"] == "SEP Alerts"
        assert body["notification_policy_receiver"] == "default"

    async def test_returns_404_when_not_found(self, api_client):
        """Return 404 with a generic detail when the backup is missing."""
        response = api_client.get(f"{API_BASE}/backups/9999")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == "Backup not found"

    async def test_returns_422_on_non_integer_id(self, api_client):
        """Reject non-integer backup ids with 422."""
        response = api_client.get(f"{API_BASE}/backups/abc")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_handles_partial_data(self, api_client, session: AsyncSession):
        """Return empty defaults for any backup section missing in the payload."""
        partial = await AlertBackupManager.create(
            session, AlertBackup(data={"templates": [{}]}, metadata_={})
        )
        response = api_client.get(f"{API_BASE}/backups/{partial.id}")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["templates"][0] == {"name": "", "summary": ""}
        assert body["rules"] == []
        assert body["notification_policy_receiver"] is None


class TestPagerDutySaveApi:
    """Tests for the PagerDuty save endpoint."""

    def test_create_new_contact_point(self, api_client, mock_pmm_api):
        """Create the PagerDuty contact point when none exists."""
        mock_pmm_api.list_contact_points.return_value = []
        mock_pmm_api.create_contact_point.return_value = ContactPoint(
            uid="new-cp", name="SEP PagerDuty", type="pagerduty", settings={}
        )
        mock_pmm_api.get_notification_policy.return_value = NotificationPolicy(
            receiver="default", routes=[]
        )

        response = api_client.post(
            f"{API_BASE}/pagerduty", json={"integration_key": "key-abcd1234"}
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"status": "created"}
        mock_pmm_api.create_contact_point.assert_awaited_once()

    def test_update_existing_contact_point(self, api_client, mock_pmm_api):
        """Update the PagerDuty contact point when it already exists."""
        mock_pmm_api.list_contact_points.return_value = [
            ContactPoint(
                uid="existing-cp",
                name="SEP PagerDuty",
                type="pagerduty",
                settings={"integrationKey": "old"},
            ),
        ]
        mock_pmm_api.get_notification_policy.return_value = NotificationPolicy(
            receiver="default",
            routes=[{"receiver": "SEP PagerDuty"}],
        )

        response = api_client.post(
            f"{API_BASE}/pagerduty", json={"integration_key": "new-key"}
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"status": "updated"}
        mock_pmm_api.update_contact_point.assert_awaited_once()

    @pytest.mark.usefixtures("_mock_pmm_unavailable")
    def test_returns_503_when_pmm_unavailable(self, api_client):
        """Return 503 when PMM is not configured."""
        response = api_client.post(
            f"{API_BASE}/pagerduty", json={"integration_key": "k"}
        )
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_returns_502_on_api_error(self, api_client, mock_pmm_api):
        """Return 502 (without leaking the underlying error) on PMM failure."""
        mock_pmm_api.list_contact_points.side_effect = OSError("network down")
        response = api_client.post(
            f"{API_BASE}/pagerduty", json={"integration_key": "k"}
        )
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert "network down" not in response.text

    def test_returns_422_on_empty_integration_key(self, api_client, mock_pmm_api):
        """Reject empty integration_key at the body level (no PMM call)."""
        response = api_client.post(
            f"{API_BASE}/pagerduty", json={"integration_key": ""}
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        mock_pmm_api.list_contact_points.assert_not_called()

    def test_does_not_log_integration_key(self, api_client, mock_pmm_api, caplog):
        """Never log the PagerDuty integration key (it is a secret)."""
        mock_pmm_api.list_contact_points.return_value = []
        mock_pmm_api.create_contact_point.return_value = ContactPoint(
            uid="new-cp", name="SEP PagerDuty", type="pagerduty", settings={}
        )
        mock_pmm_api.get_notification_policy.return_value = NotificationPolicy(
            receiver="default", routes=[]
        )
        with caplog.at_level("DEBUG", logger=_APP_LOGGER):
            response = api_client.post(
                f"{API_BASE}/pagerduty",
                json={"integration_key": "supersecretkey-xyz"},
            )
        assert response.status_code == status.HTTP_200_OK
        for record in caplog.records:
            assert "supersecretkey-xyz" not in record.getMessage()


class TestPagerDutyDeleteApi:
    """Tests for the PagerDuty delete endpoint."""

    def test_deletes_contact_point_and_route(self, api_client, mock_pmm_api):
        """Filter the matching route and delete the contact point in order."""
        mock_pmm_api.list_contact_points.return_value = [
            ContactPoint(
                uid="cp-1",
                name="SEP PagerDuty",
                type="pagerduty",
                settings={"integrationKey": "key"},
            ),
        ]
        mock_pmm_api.get_notification_policy.return_value = NotificationPolicy(
            receiver="default",
            routes=[
                {"receiver": "SEP PagerDuty"},
                {"receiver": "other"},
            ],
        )

        response = api_client.post(f"{API_BASE}/pagerduty/delete")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"status": "deleted"}
        updated_policy = mock_pmm_api.update_notification_policy.call_args[0][0]
        assert len(updated_policy.routes) == 1
        assert updated_policy.routes[0]["receiver"] == "other"
        mock_pmm_api.delete_contact_point.assert_awaited_once_with("cp-1")
        call_names = [c[0] for c in mock_pmm_api.method_calls]
        assert call_names.index("update_notification_policy") < call_names.index(
            "delete_contact_point"
        )

    def test_returns_404_when_not_configured(self, api_client, mock_pmm_api):
        """Return 404 when no PagerDuty contact point exists."""
        mock_pmm_api.list_contact_points.return_value = []
        response = api_client.post(f"{API_BASE}/pagerduty/delete")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.usefixtures("_mock_pmm_unavailable")
    def test_returns_503_when_pmm_unavailable(self, api_client):
        """Return 503 when PMM is not configured."""
        response = api_client.post(f"{API_BASE}/pagerduty/delete")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_returns_502_on_api_error(self, api_client, mock_pmm_api):
        """Return 502 when the PMM upstream call raises."""
        mock_pmm_api.list_contact_points.side_effect = OSError("API failure")
        response = api_client.post(f"{API_BASE}/pagerduty/delete")
        assert response.status_code == status.HTTP_502_BAD_GATEWAY

    def test_returns_502_when_policy_fetch_fails(self, api_client, mock_pmm_api):
        """Return 502 when the policy fetch (inside the second try) raises."""
        mock_pmm_api.list_contact_points.return_value = [
            ContactPoint(
                uid="cp-1",
                name="SEP PagerDuty",
                type="pagerduty",
                settings={"integrationKey": "secretkey"},
            ),
        ]
        mock_pmm_api.get_notification_policy.side_effect = OSError("policy down")
        response = api_client.post(f"{API_BASE}/pagerduty/delete")
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert "policy down" not in response.text
        mock_pmm_api.delete_contact_point.assert_not_awaited()

    def test_returns_502_when_delete_contact_point_fails(
        self, api_client, mock_pmm_api
    ):
        """Return 502 when the trailing ``delete_contact_point`` call raises."""
        mock_pmm_api.list_contact_points.return_value = [
            ContactPoint(
                uid="cp-1",
                name="SEP PagerDuty",
                type="pagerduty",
                settings={"integrationKey": "k"},
            ),
        ]
        mock_pmm_api.get_notification_policy.return_value = NotificationPolicy(
            receiver="default", routes=[]
        )
        mock_pmm_api.delete_contact_point.side_effect = HTTPException(
            status_code=500, detail="upstream"
        )
        response = api_client.post(f"{API_BASE}/pagerduty/delete")
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert "upstream" not in response.text

    def test_delete_does_not_log_integration_key(
        self, api_client, mock_pmm_api, caplog
    ):
        """Never log the PagerDuty integration key on the delete path either."""
        mock_pmm_api.list_contact_points.return_value = [
            ContactPoint(
                uid="cp-1",
                name="SEP PagerDuty",
                type="pagerduty",
                settings={"integrationKey": "supersecretkey-xyz"},
            ),
        ]
        mock_pmm_api.get_notification_policy.return_value = NotificationPolicy(
            receiver="default", routes=[]
        )
        with caplog.at_level("DEBUG", logger=_APP_LOGGER):
            response = api_client.post(f"{API_BASE}/pagerduty/delete")
        assert response.status_code == status.HTTP_200_OK
        for record in caplog.records:
            assert "supersecretkey-xyz" not in record.getMessage()


class TestAlertsPushApi:
    """Tests for the alerts push endpoint."""

    _EXPECTED_PUSH_COUNT = 2

    def test_push_success(self, api_client, mock_pmm_api):
        """Return per-template success results when the push succeeds."""
        response = api_client.post(
            f"{API_BASE}/push",
            json={"selected_templates": ["High CPU", "Disk Full"]},
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["results"]) == self._EXPECTED_PUSH_COUNT
        assert all(r["status"] == "success" for r in data["results"])
        assert mock_pmm_api.create_template.await_count == self._EXPECTED_PUSH_COUNT
        assert mock_pmm_api.create_rule.await_count == self._EXPECTED_PUSH_COUNT

    def test_push_pmm_not_configured(self, api_client):
        """Return 503 when PMM is not configured."""
        sep_app.dependency_overrides[get_pmm_api] = lambda: None
        sep_app.dependency_overrides[get_alert_templates] = lambda: _ALERT_TEMPLATES
        sep_app.dependency_overrides[get_or_create_alert_folder] = lambda: None
        sep_app.dependency_overrides[get_pmm_present_names] = lambda: None
        response = api_client.post(
            f"{API_BASE}/push", json={"selected_templates": ["High CPU"]}
        )
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json()["detail"] == "PMM is not configured"

    def test_push_already_present(self, api_client, mock_pmm_api):
        """Skip templates that are already present in PMM."""
        sep_app.dependency_overrides[get_pmm_present_names] = lambda: {"High CPU"}
        response = api_client.post(
            f"{API_BASE}/push", json={"selected_templates": ["High CPU"]}
        )
        assert response.status_code == status.HTTP_200_OK
        result = response.json()["results"][0]
        assert result["status"] == "skipped"
        assert result["message"] == "Already present in PMM"
        mock_pmm_api.create_template.assert_not_awaited()

    def test_push_template_not_found(self, api_client, mock_pmm_api):
        """Emit a per-template error when the template name is unknown."""
        response = api_client.post(
            f"{API_BASE}/push",
            json={"selected_templates": ["Nonexistent Template"]},
        )
        assert response.status_code == status.HTTP_200_OK
        result = response.json()["results"][0]
        assert result["status"] == "error"
        assert result["message"] == "Template not found"

    def test_push_pmm_api_error(self, api_client, mock_pmm_api):
        """Emit a per-template error when ``create_template`` raises."""
        mock_pmm_api.create_template.side_effect = HTTPException(
            status_code=502, detail="Bad Gateway"
        )
        response = api_client.post(
            f"{API_BASE}/push", json={"selected_templates": ["High CPU"]}
        )
        assert response.status_code == status.HTTP_200_OK
        result = response.json()["results"][0]
        assert result["status"] == "error"
        assert "Bad Gateway" in result["message"]

    def test_push_returns_502_when_folder_unavailable(self, api_client, mock_pmm_api):
        """Return 502 when the alert folder cannot be resolved."""
        sep_app.dependency_overrides[get_or_create_alert_folder] = lambda: None
        response = api_client.post(
            f"{API_BASE}/push", json={"selected_templates": ["High CPU"]}
        )
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.json()["detail"] == "Failed to access PMM alert folder"

    def test_push_rule_failure_reports_orphaned_template(
        self, api_client, mock_pmm_api
    ):
        """Indicate the template was created when the rule call fails."""
        mock_pmm_api.create_rule.side_effect = HTTPException(
            status_code=502, detail="Rule creation failed"
        )
        response = api_client.post(
            f"{API_BASE}/push", json={"selected_templates": ["High CPU"]}
        )
        assert response.status_code == status.HTTP_200_OK
        result = response.json()["results"][0]
        assert result["status"] == "error"
        assert "Template created but rule failed" in result["message"]

    def test_push_conflict_retry_success(self, api_client, mock_pmm_api):
        """Retry ``create_rule`` once after deleting the conflicting rule."""
        mock_pmm_api.create_rule.side_effect = [
            HTTPException(status_code=502, detail="rule conflicts with existing rule"),
            None,
        ]
        mock_pmm_api.list_rules.return_value = []
        response = api_client.post(
            f"{API_BASE}/push", json={"selected_templates": ["High CPU"]}
        )
        assert response.status_code == status.HTTP_200_OK
        result = response.json()["results"][0]
        assert result["status"] == "success"
        assert "replaced conflicting rule" in result["message"]
        assert mock_pmm_api.create_rule.await_count == 2  # noqa: PLR2004

    def test_push_conflict_retry_fails(self, api_client, mock_pmm_api):
        """Surface an orphaned-template error when the retry also fails."""
        mock_pmm_api.create_rule.side_effect = [
            HTTPException(status_code=502, detail="rule conflicts with existing rule"),
            HTTPException(status_code=502, detail="still broken"),
        ]
        mock_pmm_api.list_rules.return_value = []
        response = api_client.post(
            f"{API_BASE}/push", json={"selected_templates": ["High CPU"]}
        )
        assert response.status_code == status.HTTP_200_OK
        result = response.json()["results"][0]
        assert result["status"] == "error"
        assert "Template created but rule failed" in result["message"]

    def test_push_rejects_empty_selected_templates(self, api_client, mock_pmm_api):
        """Reject an empty selected_templates list with 422."""
        response = api_client.post(f"{API_BASE}/push", json={"selected_templates": []})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_push_already_present_swallows_create_rule_failure(
        self, api_client, mock_pmm_api
    ):
        """Report ``skipped`` even when the inner ``create_rule`` call raises.

        When a template is already present in PMM the handler still attempts a
        no-op ``create_rule`` and silently absorbs any failure (the rule
        already exists upstream). Covers the ``except (HTTPException, OSError)``
        arm inside the already-present branch.
        """
        sep_app.dependency_overrides[get_pmm_present_names] = lambda: {"High CPU"}
        mock_pmm_api.create_rule.side_effect = HTTPException(
            status_code=502, detail="rule already exists"
        )
        response = api_client.post(
            f"{API_BASE}/push", json={"selected_templates": ["High CPU"]}
        )
        assert response.status_code == status.HTTP_200_OK
        result = response.json()["results"][0]
        assert result["status"] == "skipped"
        assert result["message"] == "Already present in PMM"
        mock_pmm_api.create_rule.assert_awaited_once()

    def test_push_conflict_retry_deletes_matching_rules_only(
        self, api_client, mock_pmm_api
    ):
        """Delete conflicting + ghost rules in the target folder only.

        Drive the conflict-retry path with a populated ``list_rules`` so the
        body of ``delete_conflicting_rules`` actually runs. Rules in another
        folder must be left untouched.
        """
        mock_pmm_api.create_rule.side_effect = [
            HTTPException(status_code=502, detail="rule conflicts with existing rule"),
            None,
        ]
        mock_pmm_api.list_rules.return_value = [
            AlertRule(uid="r1", title="High CPU", namespace_uid=_FOLDER.uid),
            AlertRule(uid="r2", title="", namespace_uid=_FOLDER.uid),
            AlertRule(uid="r3", title="High CPU", namespace_uid="other-folder"),
            AlertRule(uid="r4", title="unrelated", namespace_uid=_FOLDER.uid),
        ]
        response = api_client.post(
            f"{API_BASE}/push", json={"selected_templates": ["High CPU"]}
        )
        assert response.status_code == status.HTTP_200_OK
        result = response.json()["results"][0]
        assert result["status"] == "success"
        deleted_uids = sorted(
            call.args[0] for call in mock_pmm_api.delete_rule.await_args_list
        )
        assert deleted_uids == ["r1", "r2"]

    def test_push_mixed_results_preserve_input_order(self, api_client, mock_pmm_api):
        """Return per-template results in the same order as the request."""
        mock_pmm_api.create_template.side_effect = [
            None,
            HTTPException(status_code=502, detail="boom"),
        ]
        response = api_client.post(
            f"{API_BASE}/push",
            json={"selected_templates": ["High CPU", "Nonexistent", "Disk Full"]},
        )
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert [r["name"] for r in results] == [
            "High CPU",
            "Nonexistent",
            "Disk Full",
        ]
        assert [r["status"] for r in results] == ["success", "error", "error"]
        assert results[1]["message"] == "Template not found"
        assert "boom" in results[2]["message"]


@pytest.mark.asyncio
class TestRestoreApi:
    """Tests for the restore endpoint."""

    async def test_returns_404_when_backup_missing(self, api_client, mock_pmm_api):
        """Return 404 with a generic detail when the backup id is unknown."""
        response = api_client.post(f"{API_BASE}/restore", json={"backup_id": 9999})
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == "Backup not found"

    async def test_returns_503_when_pmm_unavailable(
        self, api_client, seeded_backup: AlertBackup
    ):
        """Return 503 when PMM is not configured."""
        sep_app.dependency_overrides[get_pmm_api] = lambda: None
        response = api_client.post(
            f"{API_BASE}/restore", json={"backup_id": seeded_backup.id}
        )
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    async def test_returns_422_on_non_positive_backup_id(
        self, api_client, mock_pmm_api
    ):
        """Reject backup_id <= 0 with 422."""
        response = api_client.post(f"{API_BASE}/restore", json={"backup_id": 0})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_restore_happy_path(
        self, api_client, mock_pmm_api, seeded_backup: AlertBackup
    ):
        """Return a structured success body with restore counts."""
        mock_pmm_api.list_rules.return_value = []
        mock_pmm_api.list_contact_points.return_value = []
        mock_pmm_api.list_folders.return_value = [_FOLDER]
        mock_pmm_api.template_exists.return_value = True
        response = api_client.post(
            f"{API_BASE}/restore", json={"backup_id": seeded_backup.id}
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status"] == "success"
        assert "templates" in body["details"]

    async def test_restore_contact_point_404_falls_back_to_delete_then_create(
        self, api_client, mock_pmm_api, seeded_backup: AlertBackup
    ):
        """Fall back to delete-then-create when update_contact_point returns 404."""
        mock_pmm_api.list_rules.return_value = []
        mock_pmm_api.list_folders.return_value = [_FOLDER]
        mock_pmm_api.template_exists.return_value = True
        mock_pmm_api.list_contact_points.return_value = [
            ContactPoint(
                uid="cp-existing",
                name="SEP PagerDuty",
                type="pagerduty",
                settings={"integrationKey": "old"},
            ),
        ]
        mock_pmm_api.update_contact_point.side_effect = HTTPNotFoundException(
            "not provisioned"
        )

        response = api_client.post(
            f"{API_BASE}/restore", json={"backup_id": seeded_backup.id}
        )
        assert response.status_code == status.HTTP_200_OK
        mock_pmm_api.update_contact_point.assert_awaited_once()
        mock_pmm_api.delete_contact_point.assert_awaited_once_with("cp-existing")
        mock_pmm_api.create_contact_point.assert_awaited_once()

    async def test_restore_contact_point_double_404_skips_silently(
        self, api_client, mock_pmm_api, seeded_backup: AlertBackup
    ):
        """Skip silently when both update and delete return 404."""
        mock_pmm_api.list_rules.return_value = []
        mock_pmm_api.list_folders.return_value = [_FOLDER]
        mock_pmm_api.template_exists.return_value = True
        mock_pmm_api.list_contact_points.return_value = [
            ContactPoint(
                uid="cp-existing",
                name="SEP PagerDuty",
                type="pagerduty",
                settings={"integrationKey": "old"},
            ),
        ]
        mock_pmm_api.update_contact_point.side_effect = HTTPNotFoundException(
            "not provisioned"
        )
        mock_pmm_api.delete_contact_point.side_effect = HTTPNotFoundException(
            "not provisioned"
        )

        response = api_client.post(
            f"{API_BASE}/restore", json={"backup_id": seeded_backup.id}
        )
        assert response.status_code == status.HTTP_200_OK
        mock_pmm_api.update_contact_point.assert_awaited_once()
        mock_pmm_api.delete_contact_point.assert_awaited_once()
        mock_pmm_api.create_contact_point.assert_not_awaited()

    async def test_restore_returns_502_on_oserror(
        self, api_client, mock_pmm_api, seeded_backup: AlertBackup
    ):
        """Return 502 (without leaking the underlying message) on OSError."""
        mock_pmm_api.list_rules.side_effect = OSError("upstream down")
        response = api_client.post(
            f"{API_BASE}/restore", json={"backup_id": seeded_backup.id}
        )
        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert "upstream down" not in response.text

    async def test_restore_re_raises_http_exception_unchanged(
        self, api_client, mock_pmm_api, seeded_backup: AlertBackup
    ):
        """Propagate an upstream HTTPException status verbatim (no 502 mask).

        The ``except HTTPException: raise`` branch is distinct from the
        ``OSError`` fallback that returns 502 — pin the contract that
        FastAPI-shaped errors bubble with their original status code.
        """
        mock_pmm_api.list_rules.side_effect = HTTPException(
            status_code=409, detail="precondition failed"
        )
        response = api_client.post(
            f"{API_BASE}/restore", json={"backup_id": seeded_backup.id}
        )
        assert response.status_code == status.HTTP_409_CONFLICT

    async def test_restore_with_empty_backup_data(
        self, api_client, mock_pmm_api, session: AsyncSession
    ):
        """Return zeroed counts when the backup payload is completely empty."""
        mock_pmm_api.list_rules.return_value = []
        mock_pmm_api.list_contact_points.return_value = []
        mock_pmm_api.list_folders.return_value = [_FOLDER]
        empty_backup = await AlertBackupManager.create(
            session, AlertBackup(data={}, metadata_={})
        )
        response = api_client.post(
            f"{API_BASE}/restore", json={"backup_id": empty_backup.id}
        )
        assert response.status_code == status.HTTP_200_OK
        details = response.json()["details"]
        assert details["templates"] == {"created": 0, "skipped": 0}
        assert details["rules_created"] == 0
        assert details["rules_deleted"] == 0
        assert details["notification_policies"] == "skipped"

    async def test_restore_404_detail_does_not_echo_backup_id(
        self, api_client, mock_pmm_api
    ):
        """Confirm 404 detail is generic and never echoes the requested id."""
        forged_id = 13371337
        response = api_client.post(f"{API_BASE}/restore", json={"backup_id": forged_id})
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert str(forged_id) not in response.text
        assert response.json()["detail"] == "Backup not found"


def test_api_routes_mount_under_plugins_prefix():
    """Confirm every alerts JSON endpoint is registered in the OpenAPI spec."""
    paths = sep_app.openapi()["paths"]
    expected = {
        "/api/apps/alerts/backups",
        "/api/apps/alerts/backups/{backup_id}",
        "/api/apps/alerts/restore",
        "/api/apps/alerts/pagerduty",
        "/api/apps/alerts/pagerduty/delete",
        "/api/apps/alerts/push",
    }
    assert expected.issubset(set(paths)), expected - set(paths)
