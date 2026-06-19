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

"""Resolve owner-specific failure-alert enrichment via a plugin hook.

The tasks service owns the generic failure-alert path but must stay free of any
static ``app.sep`` import: plugin domain knowledge (e.g. the archiver
``PURGE_LIST`` schema) lives in the plugin package, not here. A task owner names
its alert-detail builder by a ``"module:function"`` string in
:data:`ALERT_DETAIL_BUILDERS`; the builder is resolved lazily with
:func:`importlib.import_module` the first time an alert for that owner fires.
This mirrors how the Celery executor resolves a task ``callable`` and how the
task seed references plugin callables by path.

Resolving lazily — rather than registering at import time — is deliberate:
``alert_for_status`` fires in three processes that share no plugin-bootstrap
step (the Celery worker, the SEP app, and the tasks API). A lazy ``module:func``
lookup works in all three; an import-time registry would only cover whichever
process happened to import the plugin.
"""

import importlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.tasks.models import TaskHistory

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OwnerAlertDetails:
    """Hold the owner-specific additions to a task failure alert.

    :param source_node: The source database node name used in the alert
        summary (Short Description).
    :param custom_details: The provider-agnostic detail payload attached to the
        alert; surfaces through ``PagerDutyAlert.custom_details``.
    """

    source_node: str
    custom_details: dict[str, Any]


#: An ``async`` callable taking the failed ``TaskHistory`` and returning the
#: owner-specific alert additions (or ``None`` when nothing should be attached).
AlertDetailBuilder = Callable[["TaskHistory"], Awaitable[OwnerAlertDetails | None]]

#: Map a ``TaskOwner`` value to the ``"module:function"`` path of its
#: alert-detail builder. Archiver enrichment lives in the archives plugin so
#: archiver domain knowledge stays out of the tasks service.
ALERT_DETAIL_BUILDERS: dict[str, str] = {
    "ARCHIVER": "app.sep.plugins.archives.alerts:build_owner_alert_details",
}

#: Cache of resolved builders, keyed by ``"module:function"`` path.
_RESOLVED: dict[str, AlertDetailBuilder] = {}


def _resolve(path: str) -> AlertDetailBuilder:
    """Import and return the builder named by a ``"module:function"`` path.

    :param path: The builder path in ``"module:function"`` form.
    :return: The resolved builder callable.
    """
    module_path, func_name = path.split(":", 1)
    module = importlib.import_module(module_path)
    return getattr(module, func_name)


async def build_owner_alert_details(
    history: "TaskHistory",
) -> OwnerAlertDetails | None:
    """Build owner-specific failure-alert details for the given history.

    Look up the builder registered for the task's owner and delegate to it.
    Return ``None`` for any owner without a builder, leaving the generic alert
    path unchanged. A builder that cannot be imported is swallowed (logged) so a
    missing or misconfigured plugin can never prevent the failure alert itself
    from firing.

    :param history: The failed task execution history.
    :return: The owner-specific alert additions, or ``None``.
    """
    path = ALERT_DETAIL_BUILDERS.get(str(history.task.owner))
    if path is None:
        return None
    builder = _RESOLVED.get(path)
    if builder is None:
        try:
            builder = _resolve(path)
        except (ImportError, AttributeError, ValueError):
            logger.exception("Failed to resolve alert detail builder %r.", path)
            return None
        _RESOLVED[path] = builder
    return await builder(history)
