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

"""Define tests for the app.core.alerts.providers.pagerduty module."""

from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientError
from pydantic import ValidationError

from app.core.alerts.models import Alert, AlertSeverity
from app.core.alerts.providers.pagerduty import (
    PagerDutyAlert,
    PagerDutyAlertSeverity,
    PagerDutyEventsAlertProvider,
)
from app.core.utils import utc_now


@pytest.fixture
def sample_alert():
    """Provide a full PagerDutyAlert with all optional fields set."""
    return Alert(
        summary="Svc down",
        source="svc-1",
        severity=AlertSeverity.CRITICAL,
        dedup_key="dup1",
        component="comp",
        group="grp",
        class_="cls",
        custom_details={"key": "val"},
        images=[{"src": "u", "href": "v", "alt": "a"}],
        links=[{"href": "l", "text": "t"}],
        timestamp=utc_now(),
    )


@pytest.mark.asyncio
async def test_send_alert_builds_correct_payload(mocker, mock_remote_api, sample_alert):
    """Verify that the JSON payload sent to PagerDuty matches expectations."""
    mock_remote_api.post.return_value = {"success": True}
    mocker.patch.object(
        PagerDutyEventsAlertProvider,
        "get_api",
        new=AsyncMock(return_value=mock_remote_api),
    )
    prov = PagerDutyEventsAlertProvider(routing_key="rk1")

    await prov.send_alert(sample_alert)
    mock_remote_api.post.assert_awaited_once_with(
        "enqueue",
        json={
            "routing_key": "rk1",
            "event_action": "trigger",
            "dedup_key": sample_alert.dedup_key,
            "images": sample_alert.images,
            "links": sample_alert.links,
            "payload": {
                "summary": sample_alert.summary,
                "source": sample_alert.source,
                "class": sample_alert.class_,
                "severity": PagerDutyAlertSeverity.CRITICAL,
                "component": sample_alert.component,
                "group": sample_alert.group,
                "custom_details": sample_alert.custom_details,
                "timestamp": sample_alert.timestamp,
            },
        },
    )


@pytest.mark.asyncio
async def test_send_alert_propagates_transport_error(
    mocker, mock_remote_api, sample_alert
):
    """Verify send_alert lets a transport error from ``post`` propagate."""
    mock_remote_api.post.side_effect = ClientError("connection reset")
    mocker.patch.object(
        PagerDutyEventsAlertProvider,
        "get_api",
        new=AsyncMock(return_value=mock_remote_api),
    )
    prov = PagerDutyEventsAlertProvider(routing_key="rk1")

    with pytest.raises(ClientError):
        await prov.send_alert(sample_alert)


@pytest.mark.asyncio
async def test_resolve_alert_builds_correct_payload(mocker, mock_remote_api):
    """Verify that the resolve JSON payload sent to PagerDuty is correct."""
    mock_remote_api.post.return_value = {"success": True}
    mocker.patch.object(
        PagerDutyEventsAlertProvider,
        "get_api",
        new=AsyncMock(return_value=mock_remote_api),
    )
    prov = PagerDutyEventsAlertProvider(routing_key="rk1")

    await prov.resolve_alert("task:backup:node-1")
    mock_remote_api.post.assert_awaited_once_with(
        "enqueue",
        json={
            "routing_key": "rk1",
            "event_action": "resolve",
            "dedup_key": "task:backup:node-1",
        },
    )


@pytest.mark.asyncio
async def test_resolve_alert_rejects_empty_dedup_key(mocker, mock_remote_api):
    """Verify resolve_alert rejects an empty dedup_key before any API call."""
    mocker.patch.object(
        PagerDutyEventsAlertProvider,
        "get_api",
        new=AsyncMock(return_value=mock_remote_api),
    )
    prov = PagerDutyEventsAlertProvider(routing_key="rk1")

    with pytest.raises(ValidationError):
        await prov.resolve_alert("")

    mock_remote_api.post.assert_not_awaited()


@pytest.mark.parametrize("severity", list(AlertSeverity))
def test_alert_maps_to_matching_pagerduty_severity(severity):
    """Verify each AlertSeverity maps to the matching PagerDutyAlertSeverity."""
    base = Alert(summary="s", source="o", severity=severity)

    pd_alert = PagerDutyAlert.model_validate(base)

    assert pd_alert.severity == PagerDutyAlertSeverity[severity.name]


def test_pagerduty_routing_key_masked_in_repr():
    """Test that routing_key is masked in repr output."""
    prov = PagerDutyEventsAlertProvider(routing_key="secret-routing-key")
    assert "secret-routing-key" not in repr(prov)


def test_pagerduty_alert_extra_ignored_and_validation():
    """Ensure PagerDutyAlert ignores extras and validates severity enum."""
    a = PagerDutyAlert(summary="s", source="o", severity="warning", foo="bar")
    dumped = a.model_dump()
    assert "foo" not in dumped
    with pytest.raises(
        ValidationError, match="Value and name not found for PagerDutyAlertSeverity"
    ):
        PagerDutyAlert(summary="s", source="o", severity="not-a-sev")


def test_pagerduty_alert_promotes_custom_details_extra_from_base_alert():
    """Promote a base Alert's ``custom_details`` extra into the typed field.

    This is the provider-agnostic seam: ``alert_for_status`` attaches
    ``custom_details`` as an extra field on the base ``Alert`` (``extra="allow"``)
    and it surfaces through ``PagerDutyAlert.custom_details`` when the provider
    re-validates the alert.
    """
    base = Alert(
        summary="s",
        source="o",
        severity=AlertSeverity.ERROR,
        custom_details={"description": "=== ERROR DETAILS ==="},
    )
    promoted = PagerDutyAlert.model_validate(base.model_dump())
    assert promoted.custom_details == {"description": "=== ERROR DETAILS ==="}
