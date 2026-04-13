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

"""Define the base alerting models."""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator, validate_call

from app.core.models import BaseCaseInsensitiveModel
from app.core.utils import utc_now
from app.core.utils.fields import NonEmptyStr

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
    :type summary: NonEmptyStr
    :param source: The source of the alert, such as the task that generated it.
    :type source: NonEmptyStr
    :param severity: The severity level of the alert, indicating its importance or
        urgency.
    :type severity: AlertSeverity
    :param timestamp: The time when the alert was generated or the related incident
        was detected. Defaults to the current UTC time.
    :type timestamp: datetime
    """

    model_config = ConfigDict(extra="allow")
    summary: NonEmptyStr
    source: NonEmptyStr
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

    async def resolve_alert(self, dedup_key: str) -> None:
        """Resolve a previously triggered alert by dedup key.

        Override in providers that support alert resolution (e.g. PagerDuty).
        The default implementation is a no-op for providers without resolve
        support.

        :param dedup_key: The deduplication key of the alert to resolve.
        :type dedup_key: str
        """


class AlertService(BaseCaseInsensitiveModel):
    """Define service for managing and triggering alerts through registered providers.

    This service allows for the registration of multiple alert providers and
    triggers alerts through all registered providers. It handles the sending of
    alerts and logs any exceptions that occur during the process.

    :param providers: A set of registered alert providers.
    :type providers: set[BaseAlertProvider]
    :param source_prefix: An optional prefix to be added to every alert source.
    :type source_prefix: str
    :param source_suffix: An optional suffix to be added to every alert source.
    :type source_suffix: str
    """

    providers: set[BaseAlertProvider] = set()
    source_prefix: str = ""
    source_suffix: str = ""

    @validate_call
    async def trigger(self, alert: Alert) -> None:
        """Trigger an alert through all registered providers.

        :param alert: The alert to be triggered.
        :type alert: Alert
        """
        if not self.providers:
            logger.warning("No alert providers registered.")
            return

        alert.source = f"{self.source_prefix}{alert.source}{self.source_suffix}"

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

    @validate_call
    async def resolve(self, dedup_key: str) -> None:
        """Resolve an alert through all registered providers.

        :param dedup_key: The deduplication key of the alert to resolve.
        :type dedup_key: str
        """
        if not self.providers:
            logger.warning("No alert providers registered.")
            return

        for provider in self.providers:
            try:
                await provider.resolve_alert(dedup_key)
                logger.info(
                    "Alert resolved via %s: dedup_key=%s",
                    provider.__class__.__name__,
                    dedup_key,
                )
            except Exception:
                logger.exception(
                    "Failed to resolve alert via %s: dedup_key=%s",
                    provider.__class__.__name__,
                    dedup_key,
                )
