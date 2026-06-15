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

__all__ = ["router"]

from app.core.settings_override.api import build_settings_router
from app.core.settings_override.models import SettingClassEnum
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
router = build_settings_router(
    classes=[
        (SettingClassEnum.SEP_SETTINGS, SEPSettings, sep_settings),
        (SettingClassEnum.SNIPPETS_SETTINGS, SnippetsSettings, snippets_settings),
        (SettingClassEnum.MESSAGES_SETTINGS, MessagesSettings, messages_settings),
    ],
    session_dep=SessionDep,
    admin_dep=IsApiAdmin,
    mutation_deps=[RequireBearerForUnsafeMethods],
    remote_classes=[(SettingClassEnum.TASKS_SETTINGS, "/admin/settings")],
    remote_api_dep=TaskAPI,
)
