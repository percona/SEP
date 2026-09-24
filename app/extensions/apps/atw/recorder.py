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

"""Denormalize a diagnostics run's terminal status onto its ATW execution row.

Run status lives behind the tasks service's own database, and the incident listing
may not pay a per-row HTTP call to read it, so ATW keeps its own copy. This module
is the write side of that copy: the tasks service resolves it lazily off the
``run_result_recorder`` the ATW proxy task carries, which is why nothing here is
imported by ``app/tasks/``.

The hook covers only the transitions ``maybe_record_run`` observes; the three it
documents as unobserved, and every row predating the proxy, are filled by
:mod:`app.extensions.apps.atw.reconcile` instead.
"""

import logging
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.extensions.apps.atw.crud import AtwIncidentExecutionManager
from app.extensions.db import get_async_session_maker
from app.tasks.models import TaskHistory

logger = logging.getLogger(__name__)

#: Importable ``"module:function"`` path of this module's run-result recorder. The
#: ATW proxy task carries it so the tasks service resolves the recorder without
#: statically importing this plugin; ``HOOK_MODULE_ALLOWLIST`` already admits
#: ``app.extensions.apps``, so the path needs no tasks-service change.
RUN_RESULT_RECORDER = f"{__name__}:record_atw_run"


async def record_atw_run(
    session: AsyncSession,  # noqa: ARG001 — seam contract; see below
    history: TaskHistory,
    result: dict[str, Any] | None,  # noqa: ARG001 — ATW records status, not payload
) -> None:
    """Write one terminal run's outcome onto the matching incident execution row.

    No-ops for a non-terminal status, and for a history no ATW execution
    references — a run dispatched by another feature never reaches here at all,
    because only ATW's own proxy task carries this recorder, but a filtered UPDATE
    is what makes that harmless rather than merely unlikely.

    ``atw_incident_execution`` is owned by the **extensions** database, while the recorder
    seam opens and passes a *tasks*-database session — two distinct engines under
    SQLite. So the write goes on a fresh extensions session opened here; the passed
    ``session`` is intentionally unused, kept only for the seam's
    ``(session, history, result)`` contract. ``result`` is unused because a
    diagnostics run's outcome is its status, not anything its payload reports.

    :param session: The tasks-database session opened by the recorder seam;
        unused — kept for the seam contract (see above).
    :param history: The terminal ``TaskHistory``, with ``task`` loaded.
    :param result: The payload-reported result; unused (see above).
    """
    if not history.status.is_terminal():
        return
    async with get_async_session_maker()() as extensions_session:
        await AtwIncidentExecutionManager.update_where(
            extensions_session,
            {
                "terminal_status": history.status,
                "finished_at": history.finished_at,
            },
            task_history_id=history.id,
        )
    logger.debug(
        "Recorded ATW run outcome %s for task history %s", history.status, history.id
    )
