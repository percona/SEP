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

"""Define an admin-only endpoint that exports the effective SEP configuration.

The endpoint dumps every loaded Pydantic settings instance, redacts sensitive
fields, and serves the result as a downloadable YAML file so administrators
can audit, back up, or reuse the running configuration.
"""
import logging
import re
from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()

REDACTED_PLACEHOLDER = "***REDACTED***"

SENSITIVE_KEY_PATTERNS: tuple[str, ...] = (
    "secret",
    "password",
    "api_key",
    "token",
)

URL_CREDENTIALS_RE = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)[^/@\s]+@")

_CORE_SETTINGS_EXCLUDE: set[str] = {"LOGGING_CONFIG", "BASE_DIR"}


def _dump(obj: Any, exclude: set[str] | None = None) -> dict[str, Any]:
    """Return a YAML-safe dump of a Pydantic settings instance.

    Uses ``mode="python"`` so custom types survive serialization, then
    coerces the resulting structure through :func:`_coerce_yaml_safe` to
    produce primitives that ``yaml.safe_dump`` can handle.

    :param obj: The settings instance to dump.
    :type obj: Any
    :param exclude: Optional set of top-level field names to omit.
    :type exclude: set[str] | None
    :return: A dict representation of the settings suitable for YAML export.
    :rtype: dict[str, Any]
    """
    kwargs: dict[str, Any] = {"mode": "python"}
    if exclude:
        kwargs["exclude"] = exclude
    return _coerce_yaml_safe(obj.model_dump(**kwargs))


def _redact_string(value: str) -> str:
    """Strip credentials baked into URL-like strings.

    Matches ``scheme://user[:pass]@host`` prefixes (e.g. Celery brokers,
    Nomad endpoints, DB URLs) and replaces the userinfo portion with
    :data:`REDACTED_PLACEHOLDER`.

    :param value: The string to sanitize.
    :type value: str
    :return: The sanitized string, unchanged if no credentials were found.
    :rtype: str
    """
    return URL_CREDENTIALS_RE.sub(
        lambda m: f"{m.group('scheme')}{REDACTED_PLACEHOLDER}@", value
    )


def _key_is_sensitive(key: str) -> bool:
    """Return ``True`` when ``key`` matches a sensitive-field substring pattern.

    :param key: The dictionary key to classify.
    :type key: str
    :return: Whether the key looks like it holds a secret.
    :rtype: bool
    """
    lowered = key.lower()
    return any(pattern in lowered for pattern in SENSITIVE_KEY_PATTERNS)
