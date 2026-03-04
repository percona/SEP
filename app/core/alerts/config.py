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

"""Define configuration utilities for alerts."""

from enum import Enum
from typing import Any, ClassVar

from pydantic import field_validator, ValidationError

from app.core.alerts.models import AlertService, BaseAlertProvider
from app.core.alerts.providers.pagerduty import PagerDutyEventsAlertProvider
from app.core.config import BaseYamlSettings


class AlertProviderEnum(Enum):
    """Define an enumeration for alert providers."""

    PAGERDUTY = PagerDutyEventsAlertProvider


class AlertSettings(BaseYamlSettings):
    """Define configuration settings for alerting.

    :cvar SETTINGS_PREFIXES: The prefixes for alert-related settings in the
        configuration file.
    :vartype SETTINGS_PREFIXES: ClassVar[list[str]]
    :param PROVIDERS: The list of alert providers for the AlertService.
    :type PROVIDERS: set[BaseAlertProvider]
    :param SOURCE_PREFIX: An optional prefix to be added to every alert source.
    :type SOURCE_PREFIX: str
    :param SOURCE_SUFFIX: An optional suffix to be added to every alert source.
    :type SOURCE_SUFFIX: str
    """

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["ALERTING"]
    PROVIDERS: set[BaseAlertProvider] = set()
    SOURCE_PREFIX: str = ""
    SOURCE_SUFFIX: str = ""

    @field_validator("PROVIDERS", mode="before")
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
alert_service = AlertService(
    providers=alert_settings.PROVIDERS,
    source_prefix=alert_settings.SOURCE_PREFIX,
    source_suffix=alert_settings.SOURCE_SUFFIX,
)
