"""Define the base alerting models."""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils import utc_now
from app.core.utils.fields import RequiredStr

logger = logging.getLogger(__name__)


class AlertSeverity(StrEnum):
    """Define alert severity levels."""

    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class Alert(BaseModel):
    """Define an alert model.

    This model represents an alert with a summary, source, severity, and timestamp.
    Extra fields can be added as needed.

    :param summary: A brief summary of the alert.
    :type summary: RequiredStr
    :param source: The source of the alert, such as the task that generated it.
    :type source: RequiredStr
    :param severity: The severity level of the alert, indicating its importance or
        urgency.
    :type severity: AlertSeverity
    :param timestamp: The time when the alert was generated or the related incident
        was detected. Defaults to the current UTC time.
    :type timestamp: datetime
    """

    model_config = ConfigDict(extra="allow")
    summary: RequiredStr
    source: RequiredStr
    severity: AlertSeverity
    timestamp: datetime = Field(default_factory=utc_now)

    @model_validator(mode="before")
    @classmethod
    def _from_model(cls, data: Any) -> Any:
        if hasattr(data, "model_dump"):
            return data.model_dump()
        return data


class BaseAlertProvider(BaseCaseInsensitiveModel, ABC):
    """Define a blueprint for alert providers."""

    def __hash__(self) -> int:
        return hash(self.__class__.__name__)

    @abstractmethod
    async def send_alert(self, alert: Alert) -> None:
        """Send an alert to the provider.

        :param alert: The alert to be sent.
        :type alert: Alert
        """


class AlertService(BaseCaseInsensitiveModel):
    """Define service for managing and triggering alerts through registered providers.

    This service allows for the registration of multiple alert providers and
    triggers alerts through all registered providers. It handles the sending of
    alerts and logs any exceptions that occur during the process.

    :param providers: A set of registered alert providers.
    :type providers: set[BaseAlertProvider]
    """

    providers: set[BaseAlertProvider] = set()

    async def trigger(self, alert: Alert) -> None:
        """Trigger an alert through all registered providers.

        :param alert: The alert to be triggered.
        :type alert: Alert
        """
        if not self.providers:
            logger.warning("No alert providers registered.")
            return

        for provider in self.providers:
            try:
                await provider.send_alert(alert)
                logger.info("Alert sent via %s: %s", provider.__class__.__name__, alert)
            except Exception:
                logger.exception(
                    "Failed to send alert via %s: %s",
                    provider.__class__.__name__,
                    alert,
                )
