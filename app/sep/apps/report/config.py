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

"""Define the report plugin settings section.

The section is read straight off YAML/env rather than mounted as a field on
``SEPSettings``: importing this module runs the report package ``__init__``, which
pulls in the app definition and, transitively, ``sep_settings`` -- so a field
default typed with :class:`HealthReportSettings` would cycle while
``SEPSettings`` is still being constructed. Consumers import
:data:`health_report_settings` at call time (periodic task schedules, Celery
tasks, API routes), matching how alerts reads its section.
"""

__all__ = [
    "HealthReportSettings",
    "ReportScheduleEntry",
    "health_report_settings",
]

from typing import Any, ClassVar
from urllib.parse import urlparse

from pydantic import field_validator, model_validator, PositiveInt, SecretStr

from app.core.celery.models import CrontabSchedule, IntervalSchedule, Period
from app.core.config import BaseYamlSettings
from app.core.models import BaseLowercaseModel
from app.core.settings_override.models import SettingClassEnum
from app.core.settings_override.proxy import OverridableSettingsProxy
from app.core.utils import transform_dict_keys
from app.core.utils.fields import StrRelativePath
from app.core.utils.strings import lower_if_string


class ReportScheduleEntry(BaseLowercaseModel):
    """Define a single scheduled report generation with its own cadence and parameters.

    :param schedule: When to run (interval or crontab).
    :type schedule: IntervalSchedule | CrontabSchedule
    :param since: Prometheus-style start offset for the report window.
    :type since: str
    :param until: Prometheus-style end offset for the report window.
    :type until: str
    :param full: Whether to generate a full report.
    :type full: bool
    :param refresh: Re-run advisor checks before collecting results.
    :type refresh: bool
    :param sections: Optional list of report sections to include.
    :type sections: list[str] | None
    :param upload: Upload the generated report to ServiceNow after generation.
        Requires global upload credentials to be configured.
    :type upload: bool
    """

    schedule: IntervalSchedule | CrontabSchedule
    since: str = "now-7d"
    until: str = "now"
    full: bool = True
    refresh: bool = False
    sections: list[str] | None = None
    upload: bool = False


class HealthReportSettings(BaseYamlSettings):
    """Configuration for the Health & Security Report plugin.

    :cvar SETTINGS_PREFIXES: The prefixes for health-report settings in the
        configuration file. Set to ``["SEP", "HEALTH_REPORT"]`` so the section
        lives under ``SEP.HEALTH_REPORT``.
    :param schedules: List of report generation schedules, each with its own
        cadence and parameters.  Empty by default (no periodic generation).
    :type schedules: list[ReportScheduleEntry]
    :param upload: Master toggle for ServiceNow upload.  When ``False``
        (the default) uploading is disabled regardless of other fields.
    :type upload: bool
    :param endpoint: The ServiceNow upload API URL.
    :type endpoint: str | None
    :param api_key: API key for authenticating with the upload endpoint.
    :type api_key: SecretStr | None
    :param client_id: Customer identifier sent with each upload.
    :type client_id: str | None
    :param artifact_dir: Directory where rendered PDF artifacts are staged for
        download. Shared between the Celery worker (writer) and web (reader), so
        only lightweight job metadata transits the Celery result backend.
    :type artifact_dir: StrRelativePath
    :param artifact_ttl: Maximum age (seconds) of a staged PDF artifact before the
        cleanup task removes it. Should mirror ``CELERY.RESULT_EXPIRES`` so a
        job's metadata and its artifact expire together.
    :type artifact_ttl: PositiveInt
    :param cleanup_interval: Cadence of the ``purge_report_artifacts`` sweep that
        deletes staged PDFs older than ``artifact_ttl``.
    :type cleanup_interval: IntervalSchedule
    """

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["SEP", "HEALTH_REPORT"]
    schedules: list[ReportScheduleEntry] = []
    upload: bool = False
    endpoint: str | None = None
    api_key: SecretStr | None = None
    client_id: str | None = None
    artifact_dir: StrRelativePath = "data/health-reports"
    artifact_ttl: PositiveInt = 3600
    cleanup_interval: IntervalSchedule = IntervalSchedule(
        every=15, period=Period.MINUTES
    )

    @model_validator(mode="before")
    @classmethod
    def _lowercase_yaml_keys(cls, data: Any) -> Any:
        """Fold uppercase YAML keys to the lowercase field names this class declares."""
        if isinstance(data, dict):
            return transform_dict_keys(data, lower_if_string, deep=True)
        return data

    @field_validator("endpoint", "client_id", mode="before")
    @classmethod
    def _empty_str_to_none(cls, v: Any) -> Any:
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("endpoint", mode="after")
    @classmethod
    def _normalize_endpoint(cls, v: str | None) -> str | None:
        """Trim a bare origin's trailing slash while preserving a path's.

        An intake may route ``/v1/upload/`` and ``/v1/upload`` differently,
        answering the slashless spelling with a redirect that replays the
        request body -- credentials included -- to the redirect target. The
        configured path is therefore sent exactly as written.

        :param v: The configured endpoint, or ``None`` when unset.
        :return: The endpoint with only a bare origin's trailing slash removed.
        """
        if v is None:
            return None
        return v if urlparse(v).path.strip("/") else v.rstrip("/")

    @field_validator("api_key", mode="before")
    @classmethod
    def _empty_secret_to_none(cls, v: Any) -> Any:
        if v is None:
            return None
        raw = v.get_secret_value() if isinstance(v, SecretStr) else v
        if isinstance(raw, str) and not raw.strip():
            return None
        return v

    @property
    def upload_disabled_reasons(self) -> list[str]:
        """Return a list of reasons why uploading is not possible.

        An empty list means upload is fully configured and ready.
        """
        if not self.upload:
            return ["Upload is disabled"]

        reasons = []
        if self.endpoint is None:
            reasons.append("Endpoint is not configured")
        else:
            parsed = urlparse(self.endpoint)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                reasons.append("Endpoint is not a valid HTTP/HTTPS address")
        if self.api_key is None:
            reasons.append("API key is not configured")
        if self.client_id is None:
            reasons.append("Client ID is not configured")
        return reasons

    @property
    def is_upload_configured(self) -> bool:
        """Return ``True`` when upload is enabled and all credentials are set."""
        return not self.upload_disabled_reasons


health_report_settings: HealthReportSettings = OverridableSettingsProxy(
    HealthReportSettings, setting_class=SettingClassEnum.HEALTH_REPORT_SETTINGS
)
