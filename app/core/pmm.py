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

"""PMM annotation helpers for task lifecycle events."""

import asyncio
import logging

from app.core.config import settings
from app.core.requests.remote_api import RemoteAPI
from app.tasks.models import TaskHistory

logger = logging.getLogger(__name__)

_ANNOTATION_TIMEOUT = 5


async def create_pmm_annotation(
    text: str,
    node_name: str,
    tags: list[str] | None = None,
    service_names: list[str] | None = None,
) -> None:
    """Create a PMM annotation via POST ``/v1/management/annotations``.

    Fire-and-forget: errors are logged but never raised. This function
    must never block or fail task execution.

    :param text: Annotation text (e.g. ``"SEP backup_data - STARTED"``).
    :type text: str
    :param node_name: PMM node name from execution target.
    :type node_name: str
    :param tags: Optional tags for the annotation.
    :type tags: list[str] | None
    :param service_names: PMM service names from task metadata.
    :type service_names: list[str] | None
    """
    if not settings.PMM.annotations_enabled:
        return
    if not settings.PMM.endpoint or not settings.PMM.api_key:
        logger.debug("PMM annotation skipped: endpoint or api_key not configured")
        return

    try:
        api = await settings.get_remote_api(
            RemoteAPI,
            endpoint=settings.PMM.endpoint,
            verify_ssl=settings.PMM.verify_ssl,
        )
        with api.auth(settings.PMM.api_key.get_secret_value()):
            await asyncio.wait_for(
                api.post(
                    "/v1/management/annotations",
                    json={
                        "text": text,
                        "tags": tags or [],
                        "node_name": node_name,
                        "service_names": service_names or [],
                    },
                ),
                timeout=_ANNOTATION_TIMEOUT,
            )
        logger.info("PMM annotation created: %s (node=%s)", text, node_name)
    except Exception:
        logger.exception("Failed to create PMM annotation: %s", text)


async def annotate_task_event(
    queue_item: TaskHistory,
    event: str,
) -> None:
    """Create a PMM annotation for a task lifecycle event.

    Read ``_service_names`` (list) or ``_service_name`` (str) from
    the task's execution request metadata.

    :param queue_item: The task history record.
    :type queue_item: TaskHistory
    :param event: The event label (e.g. ``"STARTED"``, ``"COMPLETED"``, ``"FAILED"``).
    :type event: str
    """
    meta = queue_item.execution_request.meta or {}
    service_names = meta.get("_service_names")
    if service_names is None:
        single = meta.get("_service_name")
        service_names = [single] if single else []

    await create_pmm_annotation(
        text=f"SEP {queue_item.execution_request.task} - {event}",
        node_name=queue_item.execution_request.target,
        tags=["sep", queue_item.execution_request.task, event.lower()],
        service_names=service_names,
    )
