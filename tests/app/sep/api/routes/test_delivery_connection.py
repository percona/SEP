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

"""Define tests for the /api/sep/admin/delivery-connection endpoint."""

import asyncio
from typing import Any

import pytest
from aioresponses import aioresponses
from fastapi import status
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

from app.sep.api.routes import delivery_connection
from app.sep.api.routes.delivery_connection import DeliveryConnectionStatusEnum
from app.sep.bundle_upload.plan import DeliveryPlan
from app.sep.bundle_upload.resolver import DeliveryUnavailableCode
from app.sep.config import DeliveryPlanInputs, sep_settings

ENDPOINT = "/api/sep/admin/delivery-connection/"

_DELIVERY_ENDPOINT = "https://receiver.example.com/"
_DETAILS_URL = f"{_DELIVERY_ENDPOINT}api_key?sysparm_limit=1"
_DELIVERY_SECRET = "real-connection-details-key"

#: A receiver record carrying every fact the plan below declares, alongside the
#: credential fields the same row holds on Percona's instance.
_RECEIVER_BODY: dict[str, Any] = {
    "result": {
        "expires_on": "2027-01-31",
        "active": True,
        "token": "encrypted-token-blob",
        "account": {"name": "Contrativa", "number": "ACC-42"},
    }
}

#: What the plan's pointers resolve to over that body, in declaration order.
_EXPECTED_DETAILS = [
    {"label": "Access expires on", "value": "2027-01-31"},
    {"label": "Account name", "value": "Contrativa"},
    {"label": "Key active", "value": "true"},
    {"label": "Account number", "value": "ACC-42"},
]


def _delivery_plan(*, with_connection_details: bool = True) -> DeliveryPlan:
    """Build a resolvable delivery plan, optionally declaring the read.

    The declared labels are deliberately not in alphabetical order, so a test
    asserting declaration order cannot pass on a sorted answer.

    :param with_connection_details: Whether the plan declares the read.
    :return: The validated plan.
    """
    payload = {
        "endpoint": _DELIVERY_ENDPOINT,
        "secrets": {"api_key": _DELIVERY_SECRET},
        "upload": {
            "path": "attachment/upload",
            "headers": {"x-api-key": {"source": "secret", "name": "api_key"}},
        },
    }
    if with_connection_details:
        payload["connection_details"] = {
            "path": "api_key",
            "headers": {"x-api-key": {"source": "secret", "name": "api_key"}},
            "query": {"sysparm_limit": {"source": "literal", "value": "1"}},
            "details": {
                "Access expires on": "/result/expires_on",
                "Account name": "/result/account/name",
                "Key active": "/result/active",
                "Account number": "/result/account/number",
            },
        }
    return DeliveryPlan(**payload)


@pytest.fixture
def configured_delivery(mocker: MockerFixture) -> None:
    """Configure a resolvable delivery plan that declares the read."""
    mocker.patch.object(sep_settings, "DIAGNOSTICS_DELIVERY", _delivery_plan())
    mocker.patch.object(sep_settings, "DIAGNOSTICS_DELIVERY_INPUTS", None)


class TestDeliveryConnectionEndpoint:
    """Exercise the admin delivery-connection endpoint's five outcomes."""

    def test_reports_the_declared_pairs_in_declaration_order(
        self, admin_client: TestClient, configured_delivery: None
    ) -> None:
        """Answer every pair the plan declares, ordered as the plan declares them."""
        with aioresponses() as mock:
            mock.get(_DETAILS_URL, status=status.HTTP_200_OK, payload=_RECEIVER_BODY)

            response = admin_client.get(ENDPOINT)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "status": DeliveryConnectionStatusEnum.AVAILABLE.value,
            "details": _EXPECTED_DETAILS,
        }

    def test_no_credential_the_row_carries_reaches_the_response(
        self, admin_client: TestClient, configured_delivery: None
    ) -> None:
        """Answer the declared pairs alone, carrying no credential the row holds.

        Asserting only the token's absence would pass on a regression that
        blanks the projection whenever an undeclared field is present, so the
        full expected list is asserted alongside.
        """
        with aioresponses() as mock:
            mock.get(_DETAILS_URL, status=status.HTTP_200_OK, payload=_RECEIVER_BODY)

            response = admin_client.get(ENDPOINT)

        payload = response.json()
        assert payload["status"] == DeliveryConnectionStatusEnum.AVAILABLE.value
        assert payload["details"] == _EXPECTED_DETAILS
        assert "encrypted-token-blob" not in response.text

    def test_reports_undeclared_for_a_plan_without_the_step(
        self, admin_client: TestClient, mocker: MockerFixture
    ) -> None:
        """Say so rather than guessing a request for a plan that declares none."""
        mocker.patch.object(
            sep_settings,
            "DIAGNOSTICS_DELIVERY",
            _delivery_plan(with_connection_details=False),
        )
        mocker.patch.object(sep_settings, "DIAGNOSTICS_DELIVERY_INPUTS", None)

        with aioresponses() as mock:
            response = admin_client.get(ENDPOINT)
            requests = list(mock.requests)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "status": DeliveryConnectionStatusEnum.UNDECLARED.value,
            "details": [],
        }
        assert requests == []

    def test_reports_not_configured_without_a_baked_plan(
        self, admin_client: TestClient, mocker: MockerFixture
    ) -> None:
        """Report a deployment nobody configured, without issuing a request."""
        mocker.patch.object(sep_settings, "DIAGNOSTICS_DELIVERY", None)

        with aioresponses() as mock:
            response = admin_client.get(ENDPOINT)
            requests = list(mock.requests)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "status": DeliveryConnectionStatusEnum.NOT_CONFIGURED.value,
            "details": [],
        }
        assert requests == []

    def test_reports_drifted_inputs_separately_from_unconfigured(
        self, admin_client: TestClient, mocker: MockerFixture
    ) -> None:
        """Keep re-suppliable inputs distinct from delivery nobody configured."""
        mocker.patch.object(sep_settings, "DIAGNOSTICS_DELIVERY", _delivery_plan())
        mocker.patch.object(
            sep_settings,
            "DIAGNOSTICS_DELIVERY_INPUTS",
            DeliveryPlanInputs(secrets={"renamed_key": "value"}),
        )

        response = admin_client.get(ENDPOINT)

        assert response.status_code == status.HTTP_200_OK
        assert (
            response.json()["status"]
            == DeliveryConnectionStatusEnum.INPUTS_DRIFTED.value
        )

    def test_reports_fetch_failed_on_a_refused_credential(
        self, admin_client: TestClient, configured_delivery: None
    ) -> None:
        """Report a refused credential as a state, never as an error status."""
        with aioresponses() as mock:
            mock.get(_DETAILS_URL, status=status.HTTP_401_UNAUTHORIZED)

            response = admin_client.get(ENDPOINT)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "status": DeliveryConnectionStatusEnum.FETCH_FAILED.value,
            "details": [],
        }

    def test_a_refused_reads_error_body_reaches_no_log_record(
        self,
        admin_client: TestClient,
        configured_delivery: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Keep an error body out of the log line the degraded read writes.

        ``RemoteAPI`` maps an upstream error body's ``detail`` onto the
        exception it raises, so a body-carried credential reaches the log
        through the exception rather than through the response-body line the
        transport withholds.

        :param admin_client: The administrator client issuing the read.
        :param configured_delivery: The configured plan declaring the read.
        :param caplog: The log-capture fixture.
        """
        with aioresponses() as mock:
            mock.get(
                _DETAILS_URL,
                status=status.HTTP_401_UNAUTHORIZED,
                payload={"detail": "encrypted-token-blob"},
            )
            with caplog.at_level("DEBUG"):
                response = admin_client.get(ENDPOINT)

        assert (
            response.json()["status"] == DeliveryConnectionStatusEnum.FETCH_FAILED.value
        )
        assert "encrypted-token-blob" not in response.text
        # The degraded read's own line is the positive control: without it, the
        # sentinel assertion below would hold on a run that captured nothing.
        assert "Diagnostics delivery connection read failed" in caplog.text
        # ``caplog.text``, not ``record.getMessage()``: the latter renders the
        # format string alone, so it cannot see a value carried in a traceback.
        assert "encrypted-token-blob" not in caplog.text

    def test_reports_fetch_failed_when_the_receiver_cannot_be_reached(
        self, admin_client: TestClient, configured_delivery: None
    ) -> None:
        """Report a receiver that cannot be connected to at all."""
        with aioresponses() as mock:
            mock.get(_DETAILS_URL, exception=ConnectionRefusedError("refused"))

            response = admin_client.get(ENDPOINT)

        assert response.status_code == status.HTTP_200_OK
        assert (
            response.json()["status"] == DeliveryConnectionStatusEnum.FETCH_FAILED.value
        )

    def test_reports_fetch_failed_on_a_non_json_body(
        self, admin_client: TestClient, configured_delivery: None
    ) -> None:
        """Report a body the declared pointers cannot be applied to."""
        with aioresponses() as mock:
            mock.get(
                _DETAILS_URL,
                status=status.HTTP_200_OK,
                body="OK",
                content_type="text/plain",
            )

            response = admin_client.get(ENDPOINT)

        assert response.status_code == status.HTTP_200_OK
        assert (
            response.json()["status"] == DeliveryConnectionStatusEnum.FETCH_FAILED.value
        )

    def test_reports_fetch_failed_on_a_body_the_pointers_cannot_be_applied_to(
        self, admin_client: TestClient, configured_delivery: None
    ) -> None:
        """Report a body-less answer, which no declared pointer can address."""
        with aioresponses() as mock:
            mock.get(_DETAILS_URL, status=status.HTTP_204_NO_CONTENT)

            response = admin_client.get(ENDPOINT)

        assert response.status_code == status.HTTP_200_OK
        assert (
            response.json()["status"] == DeliveryConnectionStatusEnum.FETCH_FAILED.value
        )

    def test_reports_fetch_failed_when_the_read_outlives_its_bound(
        self,
        admin_client: TestClient,
        configured_delivery: None,
        mocker: MockerFixture,
    ) -> None:
        """Report a read that outran the bound the delivery probe already runs under."""
        mocker.patch.object(delivery_connection, "EXTERNAL_PROBE_TIMEOUT_SECONDS", 0.01)

        async def _slow_receiver(_url: str, **_kwargs: Any) -> None:
            """Answer more slowly than the read's own bound allows."""
            await asyncio.sleep(0.5)

        with aioresponses() as mock:
            mock.get(_DETAILS_URL, callback=_slow_receiver)

            response = admin_client.get(ENDPOINT)

        assert response.status_code == status.HTTP_200_OK
        assert (
            response.json()["status"] == DeliveryConnectionStatusEnum.FETCH_FAILED.value
        )

    def test_reports_available_with_no_pairs_when_every_pointer_missed(
        self, admin_client: TestClient, configured_delivery: None
    ) -> None:
        """Answer the read outcome with an empty list, not a failure.

        A pointer set that no longer matches the receiver's contract is a
        successful read of a response with nothing the plan recognises.
        """
        with aioresponses() as mock:
            mock.get(
                _DETAILS_URL,
                status=status.HTTP_200_OK,
                payload={"result": {"unrelated": "value"}},
            )

            response = admin_client.get(ENDPOINT)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "status": DeliveryConnectionStatusEnum.AVAILABLE.value,
            "details": [],
        }

    def test_requires_admin(self, test_client: TestClient) -> None:
        """Reject a non-admin caller, as the case-search endpoint does."""
        response = test_client.get(ENDPOINT)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.parametrize("code", list(DeliveryUnavailableCode))
    def test_every_unavailable_code_maps_to_a_status(
        self, code: DeliveryUnavailableCode
    ) -> None:
        """Give every unavailability code a status, since the lookup is unguarded.

        That lookup sits outside the read's own exception handling, so a code
        added without a status would answer 500 rather than one of the five
        outcomes this endpoint promises. Iterating the enum is what makes a
        future member fail here instead.

        :param code: One unavailability code the resolver can report.
        """
        assert code in delivery_connection._UNAVAILABLE_STATUS
