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

"""Define tests for the /api/sep/admin/connectivity-check endpoint."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from app.api.deps import require_admin_for_unsafe_methods
from app.core.auth.providers.casdoor.models import CasdoorUser
from app.core.exceptions import (
    HTTPBadGatewayException,
    HTTPInternalServerErrorException,
)
from app.core.requests.connectivity import (
    build_connectivity_result,
    ConnectivityResult,
    ConnectivityStatusEnum,
)
from app.core.requests.remote_api import UPSTREAM_NON_JSON_HEADER
from app.sep.apps.alerts.deps import get_pmm_api
from app.sep.clients.pmm import PMMRemoteAPI
from app.sep.deps import (
    get_api_authenticated_admin,
    get_current_user,
    require_bearer_for_unsafe_methods,
)
from app.sep.main import sep_app

ENDPOINT = "/api/sep/admin/connectivity-check/"

#: Full-sweep body naming every service (the frontend's "check all" shape).
ALL_TARGETS = {"targets": ["pmm", "inventory", "tasks", "nomad"]}


def _reachable(service: str, version: str | None = None) -> ConnectivityResult:
    """Build a reachable result for the given service."""
    return build_connectivity_result(
        service, ConnectivityStatusEnum.REACHABLE, version=version
    )


@pytest.fixture
def admin_client(admin_user: CasdoorUser) -> TestClient:
    """Yield an admin TestClient with the Bearer gate satisfied."""
    sep_app.dependency_overrides[get_current_user] = lambda: admin_user
    sep_app.dependency_overrides[get_api_authenticated_admin] = lambda: admin_user
    sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
    sep_app.dependency_overrides[require_admin_for_unsafe_methods] = lambda: None
    yield TestClient(sep_app, raise_server_exceptions=False)
    sep_app.dependency_overrides = {}


@pytest.fixture
def mock_pmm_api() -> AsyncMock:
    """Override get_pmm_api with a configured PMM client mock."""
    mock = AsyncMock(spec=PMMRemoteAPI)
    sep_app.dependency_overrides[get_pmm_api] = lambda: mock
    yield mock
    sep_app.dependency_overrides.pop(get_pmm_api, None)


@pytest.fixture
def pmm_not_configured() -> None:
    """Override get_pmm_api to report PMM as unconfigured."""
    sep_app.dependency_overrides[get_pmm_api] = lambda: None
    yield
    sep_app.dependency_overrides.pop(get_pmm_api, None)


def _results_by_service(payload: list[dict]) -> dict[str, dict]:
    """Index a response payload by its ``service`` field."""
    return {entry["service"]: entry for entry in payload}


class TestConnectivityCheckEndpoint:
    """Exercise the admin connectivity-check endpoint."""

    def test_all_reachable(
        self,
        admin_client: TestClient,
        mock_pmm_api: AsyncMock,
        mock_inventory_api_dep: AsyncMock,
        mock_task_api_dep: AsyncMock,
    ) -> None:
        """Report all four services reachable when every probe succeeds."""
        mock_pmm_api.check_connectivity.return_value = _reachable("pmm", "3.1.0")
        mock_inventory_api_dep.check_connectivity.return_value = _reachable("inventory")
        mock_task_api_dep.get.return_value = {"nomad-1": "10.0.0.1"}

        response = admin_client.post(ENDPOINT, json=ALL_TARGETS)

        assert response.status_code == status.HTTP_200_OK
        results = _results_by_service(response.json())
        assert set(results) == {"pmm", "inventory", "tasks", "nomad"}
        assert all(r["reachable"] for r in results.values())
        assert results["pmm"]["version"] == "3.1.0"

    def test_one_failure_does_not_fail_response(
        self,
        admin_client: TestClient,
        mock_pmm_api: AsyncMock,
        mock_inventory_api_dep: AsyncMock,
        mock_task_api_dep: AsyncMock,
    ) -> None:
        """Keep the response 200 with others reachable when Inventory fails."""
        mock_pmm_api.check_connectivity.return_value = _reachable("pmm")
        mock_inventory_api_dep.check_connectivity.return_value = (
            build_connectivity_result("inventory", ConnectivityStatusEnum.UNREACHABLE)
        )
        mock_task_api_dep.get.return_value = {}

        response = admin_client.post(ENDPOINT, json=ALL_TARGETS)

        assert response.status_code == status.HTTP_200_OK
        results = _results_by_service(response.json())
        assert results["inventory"]["reachable"] is False
        assert results["inventory"]["status"] == "unreachable"
        assert results["pmm"]["reachable"] is True
        assert results["tasks"]["reachable"] is True
        assert results["nomad"]["reachable"] is True

    def test_empty_hosts_marks_both_reachable(
        self,
        admin_client: TestClient,
        mock_pmm_api: AsyncMock,
        mock_inventory_api_dep: AsyncMock,
        mock_task_api_dep: AsyncMock,
    ) -> None:
        """Treat an empty /hosts/ mapping as Tasks and Nomad both reachable."""
        mock_pmm_api.check_connectivity.return_value = _reachable("pmm")
        mock_inventory_api_dep.check_connectivity.return_value = _reachable("inventory")
        mock_task_api_dep.get.return_value = {}

        results = _results_by_service(
            admin_client.post(ENDPOINT, json=ALL_TARGETS).json()
        )

        assert results["tasks"]["reachable"] is True
        assert results["nomad"]["reachable"] is True

    def test_hosts_502_means_tasks_up_nomad_down(
        self,
        admin_client: TestClient,
        mock_pmm_api: AsyncMock,
        mock_inventory_api_dep: AsyncMock,
        mock_task_api_dep: AsyncMock,
    ) -> None:
        """Map a Tasks 502 to Tasks reachable but Nomad unreachable."""
        mock_pmm_api.check_connectivity.return_value = _reachable("pmm")
        mock_inventory_api_dep.check_connectivity.return_value = _reachable("inventory")
        mock_task_api_dep.get.side_effect = HTTPBadGatewayException(
            "Executor backend unreachable"
        )

        results = _results_by_service(
            admin_client.post(ENDPOINT, json=ALL_TARGETS).json()
        )

        assert results["tasks"]["reachable"] is True
        assert results["nomad"]["reachable"] is False
        assert results["nomad"]["status"] == "unreachable"

    def test_nginx_502_marks_tasks_unreachable(
        self,
        admin_client: TestClient,
        mock_pmm_api: AsyncMock,
        mock_inventory_api_dep: AsyncMock,
        mock_task_api_dep: AsyncMock,
    ) -> None:
        """Treat a non-JSON (nginx) 502 as the whole Tasks app being down.

        nginx answers with an HTML 502 when the Tasks process is unreachable;
        ``RemoteAPI.request`` stamps ``UPSTREAM_NON_JSON_HEADER`` on that
        ``HTTPException``. Unlike an app-level JSON 502 (Nomad down), Tasks must
        not be reported reachable: the marked 502 is classified like any other
        error response the server returned.
        """
        mock_pmm_api.check_connectivity.return_value = _reachable("pmm")
        mock_inventory_api_dep.check_connectivity.return_value = _reachable("inventory")
        mock_task_api_dep.get.side_effect = HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="An unexpected error occurred on the server.",
            headers={UPSTREAM_NON_JSON_HEADER: "1"},
        )

        results = _results_by_service(
            admin_client.post(ENDPOINT, json=ALL_TARGETS).json()
        )

        assert results["tasks"]["reachable"] is False
        assert results["tasks"]["status"] == "error"
        assert results["nomad"]["reachable"] is False
        assert results["nomad"]["status"] == "error"

    def test_hosts_non_502_error_marks_both_error(
        self,
        admin_client: TestClient,
        mock_pmm_api: AsyncMock,
        mock_inventory_api_dep: AsyncMock,
        mock_task_api_dep: AsyncMock,
    ) -> None:
        """Mark both Tasks and Nomad error on a non-502 HTTP failure (e.g. 500).

        A 500 indicates the Tasks API itself is unhealthy, not a Nomad backend
        outage, so Tasks must not be reported reachable.
        """
        mock_pmm_api.check_connectivity.return_value = _reachable("pmm")
        mock_inventory_api_dep.check_connectivity.return_value = _reachable("inventory")
        mock_task_api_dep.get.side_effect = HTTPInternalServerErrorException()

        results = _results_by_service(
            admin_client.post(ENDPOINT, json=ALL_TARGETS).json()
        )

        assert results["tasks"]["reachable"] is False
        assert results["tasks"]["status"] == "error"
        assert results["nomad"]["reachable"] is False
        assert results["nomad"]["status"] == "error"

    def test_hosts_connection_error_marks_both_unreachable(
        self,
        admin_client: TestClient,
        mock_pmm_api: AsyncMock,
        mock_inventory_api_dep: AsyncMock,
        mock_task_api_dep: AsyncMock,
    ) -> None:
        """Mark both Tasks and Nomad unreachable on a connection error."""
        mock_pmm_api.check_connectivity.return_value = _reachable("pmm")
        mock_inventory_api_dep.check_connectivity.return_value = _reachable("inventory")
        mock_task_api_dep.get.side_effect = ConnectionRefusedError("refused")

        results = _results_by_service(
            admin_client.post(ENDPOINT, json=ALL_TARGETS).json()
        )

        assert results["tasks"]["reachable"] is False
        assert results["tasks"]["status"] == "unreachable"
        assert results["nomad"]["reachable"] is False
        assert results["nomad"]["status"] == "unreachable"

    def test_hosts_auth_failure_marks_both_auth_failed(
        self,
        admin_client: TestClient,
        mock_pmm_api: AsyncMock,
        mock_inventory_api_dep: AsyncMock,
        mock_task_api_dep: AsyncMock,
    ) -> None:
        """Map a Tasks 401 to both Tasks and Nomad auth_failed."""
        mock_pmm_api.check_connectivity.return_value = _reachable("pmm")
        mock_inventory_api_dep.check_connectivity.return_value = _reachable("inventory")
        mock_task_api_dep.get.side_effect = HTTPException(status.HTTP_401_UNAUTHORIZED)

        results = _results_by_service(
            admin_client.post(ENDPOINT, json=ALL_TARGETS).json()
        )

        assert results["tasks"]["status"] == "auth_failed"
        assert results["nomad"]["status"] == "auth_failed"

    def test_pmm_not_configured(
        self,
        admin_client: TestClient,
        pmm_not_configured: None,
        mock_inventory_api_dep: AsyncMock,
        mock_task_api_dep: AsyncMock,
    ) -> None:
        """Report PMM not-configured without raising when no PMM is set."""
        mock_inventory_api_dep.check_connectivity.return_value = _reachable("inventory")
        mock_task_api_dep.get.return_value = {}

        results = _results_by_service(
            admin_client.post(ENDPOINT, json=ALL_TARGETS).json()
        )

        assert results["pmm"]["reachable"] is False
        assert "not configured" in results["pmm"]["detail"].lower()

    def test_requires_admin(self, test_client: TestClient) -> None:
        """Reject a non-admin caller (cookie/regular user) with 403."""
        # ``test_client`` authenticates a regular (non-admin) user. Auth is
        # enforced before body validation, so a valid body still gets a 403.
        response = test_client.post(ENDPOINT, json=ALL_TARGETS)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_requires_bearer_on_post(
        self, api_admin_client_no_bearer: TestClient
    ) -> None:
        """Reject an admin cookie-only POST when the Bearer gate is intact."""
        response = api_admin_client_no_bearer.post(ENDPOINT, json=ALL_TARGETS)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_targets_subset_probes_only_requested(
        self,
        admin_client: TestClient,
        mock_pmm_api: AsyncMock,
        mock_inventory_api_dep: AsyncMock,
        mock_task_api_dep: AsyncMock,
    ) -> None:
        """Probe only PMM when ``targets`` names PMM alone."""
        mock_pmm_api.check_connectivity.return_value = _reachable("pmm")

        response = admin_client.post(ENDPOINT, json={"targets": ["pmm"]})

        assert response.status_code == status.HTTP_200_OK
        results = _results_by_service(response.json())
        assert set(results) == {"pmm"}
        mock_inventory_api_dep.check_connectivity.assert_not_called()
        mock_task_api_dep.get.assert_not_called()

    @pytest.mark.usefixtures("mock_task_api_dep")
    def test_targets_preserve_request_order(
        self,
        admin_client: TestClient,
        mock_pmm_api: AsyncMock,
        mock_inventory_api_dep: AsyncMock,
    ) -> None:
        """Return results in the order the services were requested."""
        mock_pmm_api.check_connectivity.return_value = _reachable("pmm")
        mock_inventory_api_dep.check_connectivity.return_value = _reachable("inventory")

        payload = admin_client.post(
            ENDPOINT, json={"targets": ["inventory", "pmm"]}
        ).json()

        assert [entry["service"] for entry in payload] == ["inventory", "pmm"]

    @pytest.mark.usefixtures("mock_pmm_api", "mock_inventory_api_dep")
    def test_nomad_only_runs_hosts_probe(
        self,
        admin_client: TestClient,
        mock_task_api_dep: AsyncMock,
    ) -> None:
        """Return only Nomad, driven by the shared /hosts/ probe, when asked alone."""
        mock_task_api_dep.get.return_value = {}

        response = admin_client.post(ENDPOINT, json={"targets": ["nomad"]})

        results = _results_by_service(response.json())
        assert set(results) == {"nomad"}
        assert results["nomad"]["reachable"] is True
        mock_task_api_dep.get.assert_awaited_once()

    @pytest.mark.usefixtures("mock_pmm_api", "mock_inventory_api_dep")
    def test_tasks_and_nomad_share_single_probe(
        self,
        admin_client: TestClient,
        mock_task_api_dep: AsyncMock,
    ) -> None:
        """Run /hosts/ exactly once when both Tasks and Nomad are requested."""
        mock_task_api_dep.get.return_value = {}

        response = admin_client.post(ENDPOINT, json={"targets": ["tasks", "nomad"]})

        results = _results_by_service(response.json())
        assert set(results) == {"tasks", "nomad"}
        mock_task_api_dep.get.assert_awaited_once()

    @pytest.mark.usefixtures(
        "mock_pmm_api", "mock_inventory_api_dep", "mock_task_api_dep"
    )
    def test_empty_targets_rejected(self, admin_client: TestClient) -> None:
        """Reject an empty ``targets`` list with 422."""
        response = admin_client.post(ENDPOINT, json={"targets": []})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.usefixtures(
        "mock_pmm_api", "mock_inventory_api_dep", "mock_task_api_dep"
    )
    def test_invalid_target_rejected(self, admin_client: TestClient) -> None:
        """Reject an unknown service name with 422."""
        response = admin_client.post(ENDPOINT, json={"targets": ["bogus"]})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.usefixtures(
        "mock_pmm_api", "mock_inventory_api_dep", "mock_task_api_dep"
    )
    def test_missing_targets_rejected(self, admin_client: TestClient) -> None:
        """Reject a request with no ``targets`` field with 422."""
        response = admin_client.post(ENDPOINT, json={})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.usefixtures("mock_pmm_api", "mock_inventory_api_dep")
    def test_duplicate_targets_collapsed(
        self,
        admin_client: TestClient,
        mock_task_api_dep: AsyncMock,
    ) -> None:
        """Collapse duplicate targets so a repeated service probes and returns once."""
        mock_task_api_dep.get.return_value = {}

        payload = admin_client.post(
            ENDPOINT, json={"targets": ["tasks", "tasks"]}
        ).json()

        assert [entry["service"] for entry in payload] == ["tasks"]
        mock_task_api_dep.get.assert_awaited_once()

    @pytest.mark.usefixtures("mock_pmm_api", "mock_inventory_api_dep")
    def test_tasks_only_runs_hosts_probe(
        self,
        admin_client: TestClient,
        mock_task_api_dep: AsyncMock,
    ) -> None:
        """Return only Tasks, driven by the shared /hosts/ probe, when asked alone."""
        mock_task_api_dep.get.return_value = {}

        response = admin_client.post(ENDPOINT, json={"targets": ["tasks"]})

        results = _results_by_service(response.json())
        assert set(results) == {"tasks"}
        assert results["tasks"]["reachable"] is True
        mock_task_api_dep.get.assert_awaited_once()

    def test_hosts_timeout_marks_both_timeout(
        self,
        admin_client: TestClient,
        mock_pmm_api: AsyncMock,
        mock_inventory_api_dep: AsyncMock,
        mock_task_api_dep: AsyncMock,
    ) -> None:
        """Map a /hosts/ probe timeout to both Tasks and Nomad timeout."""
        mock_pmm_api.check_connectivity.return_value = _reachable("pmm")
        mock_inventory_api_dep.check_connectivity.return_value = _reachable("inventory")
        mock_task_api_dep.get.side_effect = TimeoutError("timed out")

        results = _results_by_service(
            admin_client.post(ENDPOINT, json=ALL_TARGETS).json()
        )

        assert results["tasks"]["reachable"] is False
        assert results["tasks"]["status"] == "timeout"
        assert results["nomad"]["reachable"] is False
        assert results["nomad"]["status"] == "timeout"

    @pytest.mark.usefixtures("mock_inventory_api_dep", "mock_task_api_dep")
    def test_pmm_configured_unreachable(
        self,
        admin_client: TestClient,
        mock_pmm_api: AsyncMock,
    ) -> None:
        """Pass through a configured PMM client's unreachable result verbatim."""
        mock_pmm_api.check_connectivity.return_value = build_connectivity_result(
            "pmm", ConnectivityStatusEnum.UNREACHABLE
        )

        results = _results_by_service(
            admin_client.post(ENDPOINT, json={"targets": ["pmm"]}).json()
        )

        assert results["pmm"]["reachable"] is False
        assert results["pmm"]["status"] == "unreachable"
