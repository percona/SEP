"""Define the base alerting models."""

from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils import utc_now
from app.core.utils.fields import RequiredStr


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
