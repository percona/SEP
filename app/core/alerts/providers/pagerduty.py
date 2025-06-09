"""Provide a PagerDuty alert provider."""

from enum import StrEnum
from functools import cached_property
from typing import Any, ClassVar

from pydantic import (
    ConfigDict,
    Field,
    validate_call,
)

from app.core.alerts.models import Alert, BaseAlertProvider
from app.core.config import settings
from app.core.requests import RemoteAPI
from app.core.utils.fields import EnumFieldMixin, RequiredStr, StrHttpUrl


class PagerDutyAlertSeverity(EnumFieldMixin, StrEnum):
    """Define alert severity levels."""

    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class PagerDutyAlert(Alert):
    """Define a PagerDuty alert model.

    This model extends the base Alert model to include PagerDuty-specific fields.

    :param severity: The severity level of the alert, indicating its importance or
        urgency. Must be one of the PagerDutyAlertSeverity values.
    :type severity: PagerDutyAlertSeverity
    :param dedup_key: A unique key to deduplicate alerts. If provided, PagerDuty will
        not trigger a new incident if an alert with the same dedup_key is already
        active. Defaults to None.
    :type dedup_key: RequiredStr | None
    :param component: The component affected by the alert, such as a service or
        application. Defaults to None.
    :type component: RequiredStr | None
    :param group: The group associated with the alert, such as a team or department.
        Defaults to None.
    :type group: RequiredStr | None
    :param class_: The class of the alert, which can be used to categorize it.
        Defaults to None.
    :type class_: RequiredStr | None
    :param custom_details: Additional custom details to include in the alert.
        Defaults to None.
    :type custom_details: dict[str, Any] | None
    :param images: A list of images to include in the alert, each represented as a
        dictionary with 'src', 'href', and 'alt' keys. Defaults to None.
    :type images: list[dict[str, str]] | None
    :param links: A list of links to include in the alert, each represented as a
        dictionary with 'href' and 'text' keys. Defaults to None.
    :type links: list[dict[str, str]] | None
    """

    model_config = ConfigDict(extra="ignore")
    severity: PagerDutyAlertSeverity
    dedup_key: RequiredStr | None = None
    component: RequiredStr | None = None
    group: RequiredStr | None = None
    class_: RequiredStr | None = Field(None, alias="class")
    custom_details: dict[str, Any] | None = None
    images: list[dict[str, str]] | None = None
    links: list[dict[str, str]] | None = None


class PagerDutyEventsAlertProvider(BaseAlertProvider):
    """Define a PagerDuty alert provider.

    This provider sends alerts to PagerDuty using the Events API v2.
    """

    API_ENDPOINT: ClassVar[StrHttpUrl] = "https://events.pagerduty.com/v2/"
    routing_key: str

    def __hash__(self) -> int:
        return hash((self.__class__.__name__, self.routing_key))

    @cached_property
    def api(self) -> RemoteAPI:
        """Get the PagerDuty API client.

        :return: The RemoteAPI client for PagerDuty.
        :rtype: RemoteAPI
        """
        remote_api = RemoteAPI(endpoint=self.API_ENDPOINT)
        remote_api.session = settings.get_extra_client_session(remote_api.endpoint)
        return remote_api

    @validate_call
    async def send_alert(self, alert: PagerDutyAlert) -> None:
        """Send an alert to PagerDuty.

        This method sends an alert to PagerDuty using the Events API v2.

        :param alert: The alert to be sent.
        :type alert: Alert
        """
        await self.api.post(
            "enqueue",
            json={
                "routing_key": self.routing_key,
                "event_action": "trigger",
                **alert.model_dump(
                    include={"dedup_key", "images", "links"}, exclude_none=True
                ),
                "payload": alert.model_dump(
                    by_alias=True,
                    exclude={"dedup_key", "images", "links"},
                    exclude_none=True,
                ),
            },
        )
