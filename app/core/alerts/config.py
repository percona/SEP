"""Define configuration utilities for alerts."""

from enum import Enum
from typing import Any

from pydantic import field_validator, ValidationError

from app.core.alerts.models import AlertService, BaseAlertProvider
from app.core.alerts.providers.pagerduty import PagerDutyEventsAlertProvider
from app.core.config import BaseYamlSettings


class AlertProviderEnum(Enum):
    """Define an enumeration for alert providers."""

    PAGERDUTY = PagerDutyEventsAlertProvider


class AlertSettings(BaseYamlSettings):
    """Define configuration settings for alert providers.

    :param ALERT_PROVIDERS: The alert service configuration, which includes a list of
        alert providers.
    :type ALERT_PROVIDERS: AlertService
    """

    ALERT_PROVIDERS: set[BaseAlertProvider] = set()

    @field_validator("ALERT_PROVIDERS", mode="before")
    @classmethod
    def _set_alerts_providers(cls, data: Any) -> Any:
        providers = set()
        for provider_data in data:
            provider_name = provider_data.pop("PROVIDER", None) or provider_data.pop(
                "provider", None
            )
            if not provider_name:
                raise ValueError(
                    "Invalid alert provider configuration. Ensure 'PROVIDER' is set."
                )
            try:
                provider_class = AlertProviderEnum[provider_name.upper()].value
                providers.add(provider_class.model_validate(provider_data))
            except KeyError:
                raise ValueError(
                    f"Invalid alert provider: {provider_name}. Available providers: {[e.name for e in AlertProviderEnum]}"
                ) from None
            except ValidationError as exc:
                raise ValueError(
                    f"Invalid configuration for {provider_name!r} provider: {exc.errors()}"
                ) from None
        return providers


alert_settings = AlertSettings()
alert_service = AlertService(providers=alert_settings.ALERT_PROVIDERS)
