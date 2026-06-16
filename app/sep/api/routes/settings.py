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

"""Compose the SEP sub-app's settings REST API."""

__all__ = ["SEP_ADMIN_SETTINGS_CLASSES", "router"]

from typing import Any

import yaml
from fastapi import HTTPException
from fastapi.responses import Response

from app.core.exceptions import HTTPBadGatewayException
from app.core.settings_override.api import (
    build_settings_class_values,
    build_settings_router,
)
from app.core.settings_override.api.routes import ClassEntry
from app.core.settings_override.models import SettingClassEnum
from app.core.utils.date_time import utc_now
from app.sep.api.openapi import UPSTREAM_TASKS_502_RESPONSE
from app.sep.config import sep_settings, SEPSettings
from app.sep.deps import IsApiAdmin, RequireBearerForUnsafeMethods, SessionDep, TaskAPI
from app.sep.middleware.messages.config import messages_settings, MessagesSettings
from app.sep.snippets.config import snippets_settings, SnippetsSettings

# TasksSettings is owned by the Tasks sub-app (its own database and override
# layer), so SEP cannot register it as a local class. It is proxied server-side
# through ``tasks_api`` -- the same pattern as ``dashboard``/``hosts``/``task_stats``
# -- so the React Settings page reaches every group through ``/api/sep`` only and
# never calls ``/api/tasks/admin/settings/*`` directly (API-First Rule 1). The
# Tasks router mounts its settings at ``/admin/settings`` (see
# ``app/tasks/settings/routes.py``).
SEP_ADMIN_SETTINGS_CLASSES: list[ClassEntry] = [
    (SettingClassEnum.SEP_SETTINGS, SEPSettings, sep_settings),
    (SettingClassEnum.SNIPPETS_SETTINGS, SnippetsSettings, snippets_settings),
    (SettingClassEnum.MESSAGES_SETTINGS, MessagesSettings, messages_settings),
]

router = build_settings_router(
    classes=SEP_ADMIN_SETTINGS_CLASSES,
    session_dep=SessionDep,
    admin_dep=IsApiAdmin,
    mutation_deps=[RequireBearerForUnsafeMethods],
    remote_classes=[(SettingClassEnum.TASKS_SETTINGS, "/admin/settings")],
    remote_api_dep=TaskAPI,
)


def _tasks_settings_groups(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map a Tasks ``SettingsListResponse`` JSON body to export class blocks.

    :param payload: Parsed JSON from ``GET /admin/settings/`` on the Tasks API.
    :type payload: dict[str, Any]
    :return: One ``{key: value}`` mapping per ``setting_class`` group in the
        payload.
    :rtype: dict[str, dict[str, Any]]
    :raises HTTPBadGatewayException: If ``payload`` is missing a ``groups`` list
        or any setting entry lacks a ``key`` or ``value``.
    """
    groups = payload.get("groups")
    if not isinstance(groups, list):
        msg = "Tasks settings LIST response missing 'groups'."
        raise HTTPBadGatewayException(detail=msg)

    export: dict[str, dict[str, Any]] = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        setting_class = group.get("setting_class")
        settings = group.get("settings")
        if not isinstance(setting_class, str) or not isinstance(settings, list):
            continue
        class_block: dict[str, Any] = {}
        for entry in settings:
            if not isinstance(entry, dict):
                raise HTTPBadGatewayException(
                    detail="Tasks settings LIST entry is not an object.",
                )
            key = entry.get("key")
            if not isinstance(key, str):
                raise HTTPBadGatewayException(
                    detail="Tasks settings LIST entry missing 'key'.",
                )
            if "value" not in entry:
                raise HTTPBadGatewayException(
                    detail=f"Tasks settings LIST entry missing 'value' for key {key!r}.",
                )
            class_block[key] = entry["value"]
        export[setting_class] = class_block
    return export


@router.get(
    "/export",
    responses=UPSTREAM_TASKS_502_RESPONSE,
)
async def export_settings(
    session: SessionDep,
    tasks_api: TaskAPI,
) -> Response:
    """Return the merged effective configuration as a YAML attachment.

    Aggregates the three SEP-wired settings classes locally and fans out to
    ``GET /admin/settings/`` on the Tasks API for ``TasksSettings``. Values
    use the same dump path as the settings LIST endpoints. On upstream failure,
    re-raise as :class:`~app.core.exceptions.HTTPBadGatewayException` — no
    partial export.

    :param session: The active database session for SEP override queries.
    :type session: AsyncSession
    :param tasks_api: The Tasks API client used to fetch ``TasksSettings``.
    :type tasks_api: TaskAPI
    :return: YAML bytes with ``Content-Disposition`` set for download.
    :rtype: Response
    :raises HTTPBadGatewayException: If the Tasks settings LIST call fails
        with an ``HTTPException`` (e.g. an upstream non-2xx response), an
        ``OSError`` (e.g. a connection failure), an unexpected payload shape,
        or a missing ``TasksSettings`` group.
    """
    payload: dict[str, dict[str, Any]] = {}

    for setting_class, settings_cls, proxy in SEP_ADMIN_SETTINGS_CLASSES:
        payload[setting_class.value] = await build_settings_class_values(
            session=session,
            setting_class=setting_class,
            settings_cls=settings_cls,
            proxy=proxy,
        )

    try:
        tasks_payload = await tasks_api.get("/admin/settings/")
    except (HTTPException, OSError) as exc:
        detail = getattr(exc, "detail", str(exc))
        raise HTTPBadGatewayException(detail=str(detail)) from exc

    if not isinstance(tasks_payload, dict):
        raise HTTPBadGatewayException(
            detail="Tasks settings LIST returned an unexpected payload.",
        )

    tasks_groups = _tasks_settings_groups(tasks_payload)
    tasks_key = SettingClassEnum.TASKS_SETTINGS.value
    if tasks_key not in tasks_groups:
        raise HTTPBadGatewayException(
            detail=f"Tasks settings LIST response missing {tasks_key!r} group.",
        )
    payload[tasks_key] = tasks_groups[tasks_key]

    yaml_body = yaml.safe_dump(
        payload,
        default_flow_style=False,
        sort_keys=False,
    )
    filename = f"sep-config-{utc_now():%Y-%m-%d}.yaml"
    return Response(
        content=yaml_body,
        media_type="application/x-yaml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
