"""Define tests for the app.core.alerts.providers.pagerduty module."""

from unittest.mock import AsyncMock

import pytest
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


def test_pagerduty_alert_extra_ignored_and_validation():
    """Ensure PagerDutyAlert ignores extras and validates severity enum."""
    a = PagerDutyAlert(summary="s", source="o", severity="warning", foo="bar")
    dumped = a.model_dump()
    assert "foo" not in dumped
    with pytest.raises(
        ValidationError, match="Value and name not found for PagerDutyAlertSeverity"
    ):
        PagerDutyAlert(summary="s", source="o", severity="not-a-sev")
