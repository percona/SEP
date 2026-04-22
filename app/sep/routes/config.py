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

import io
import logging
import re
from datetime import date, datetime, timedelta, UTC
from enum import Enum
from pathlib import PurePath
from string import Template
from typing import Any
from uuid import UUID

import yaml
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, SecretStr

from app.core.alerts.config import alert_settings
from app.core.config import settings
from app.core.utils import deep_dict_update
from app.inventory.config import inventory_settings
from app.sep.config import sep_settings
from app.sep.deps import IsAdminDep
from app.sep.middleware.messages.config import messages_settings
from app.sep.plugins.alerts.config import alerts_pmm_config
from app.sep.snippets.config import snippets_settings
from app.tasks.anonymizer.config import anonymizer_settings
from app.tasks.config import tasks_settings
from app.tasks.periodic.config import periodic_tasks_settings

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


def _coerce_yaml_safe(value: Any) -> Any:  # noqa: C901, PLR0911
    """Recursively convert ``value`` into YAML-serializable primitives.

    Walks dicts, lists, tuples, sets, and Pydantic models, coercing custom
    types (``SecretStr``, URL/Path objects, enums, datetimes, UUIDs,
    ``string.Template``, etc.) into strings, numbers, lists, or dicts that
    ``yaml.safe_dump`` accepts.

    :param value: The value to coerce.
    :type value: Any
    :return: A YAML-safe representation of ``value``.
    :rtype: Any
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, Enum):
        return _coerce_yaml_safe(value.value)
    if isinstance(value, int | float | str):
        return value
    if isinstance(value, SecretStr):
        return str(value)
    if isinstance(value, BaseModel):
        return _coerce_yaml_safe(value.model_dump(mode="python"))
    if isinstance(value, dict):
        return {str(k): _coerce_yaml_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_coerce_yaml_safe(item) for item in value]
    if isinstance(value, set | frozenset):
        return [_coerce_yaml_safe(item) for item in sorted(value, key=repr)]
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, PurePath | UUID):
        return str(value)
    if isinstance(value, Template):
        return value.template
    return str(value)


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


def _place(root: dict[str, Any], path: list[str], data: dict[str, Any]) -> None:
    """Merge ``data`` into ``root`` at the nested key path.

    An empty path merges ``data`` into ``root`` itself.

    :param root: The destination dictionary to mutate.
    :type root: dict[str, Any]
    :param path: The chain of keys under which ``data`` should live.
    :type path: list[str]
    :param data: The dictionary to merge in.
    :type data: dict[str, Any]
    """
    if not path:
        deep_dict_update(root, data)
        return
    cursor = root
    for key in path[:-1]:
        cursor = cursor.setdefault(key, {})
        if not isinstance(cursor, dict):
            return
    leaf = cursor.setdefault(path[-1], {})
    if isinstance(leaf, dict):
        deep_dict_update(leaf, data)
    else:
        cursor[path[-1]] = data


def collect_effective_config() -> dict[str, Any]:
    """Collect and merge every loaded settings instance into one dict.

    The resulting structure mirrors the ``default:`` section of
    ``settings.yaml``: core ``Settings`` fields sit at the root and app- or
    plugin-scoped settings nest under the keys from their
    ``SETTINGS_PREFIXES``.

    :return: The merged effective configuration as a nested dict.
    :rtype: dict[str, Any]
    """
    config: dict[str, Any] = _dump(settings, exclude=_CORE_SETTINGS_EXCLUDE)

    for obj in (
        sep_settings,
        inventory_settings,
        tasks_settings,
        periodic_tasks_settings,
        snippets_settings,
        messages_settings,
        anonymizer_settings,
        alert_settings,
    ):
        prefixes = list(getattr(obj, "SETTINGS_PREFIXES", []) or [])
        _place(config, prefixes, _dump(obj))

    _place(config, ["SEP", "ALERTS_PMM"], _dump(alerts_pmm_config))
    return config


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


def redact(data: Any) -> Any:
    """Return a copy of ``data`` with secrets stripped.

    Recursively walks dicts and lists. Keys matching
    :data:`SENSITIVE_KEY_PATTERNS` have their value replaced wholesale with
    :data:`REDACTED_PLACEHOLDER`. Every string leaf is additionally passed
    through :func:`_redact_string` to catch credentials embedded in URLs.

    :param data: The value to sanitize. May be a dict, list, scalar, or
        ``None``.
    :type data: Any
    :return: A new structure with sensitive data redacted.
    :rtype: Any
    """
    if isinstance(data, dict):
        return {
            key: (
                REDACTED_PLACEHOLDER
                if _key_is_sensitive(str(key)) and value is not None
                else redact(value)
            )
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [redact(item) for item in data]
    if isinstance(data, str):
        return _redact_string(data)
    return data


def _build_yaml_bytes() -> bytes:
    """Serialize the effective configuration to UTF-8 encoded YAML bytes.

    :return: The redacted configuration rendered as YAML.
    :rtype: bytes
    """
    config = redact(collect_effective_config())
    return yaml.safe_dump(
        config, default_flow_style=False, sort_keys=False, allow_unicode=True
    ).encode("utf-8")


@router.get("/export", name="export_config", dependencies=[IsAdminDep])
async def export_config() -> StreamingResponse:
    """Return the effective configuration as a downloadable YAML file.

    The endpoint is admin-only. Sensitive fields (secrets, passwords, API
    keys, tokens) are redacted from the output. The filename embeds a UTC
    date stamp so browsers save distinct snapshots.

    :return: A streaming response containing the YAML payload with headers
        that trigger a file download.
    :rtype: StreamingResponse
    """
    payload = _build_yaml_bytes()
    filename = f"sep-config-{datetime.now(UTC).strftime('%Y-%m-%d')}.yaml"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/yaml",
        headers=headers,
    )
