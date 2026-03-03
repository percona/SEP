# Copyright 2025 Percona LLC
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

"""Define dependencies for periodic tasks in the Tasks API."""

import logging
from typing import Annotated

from fastapi import Depends
from sqlalchemy_celery_beat import PeriodicTask

from app.core.celery.deps import CeleryBeatSessionDep
from app.tasks.periodic.crud import PeriodicTaskManager

logger = logging.getLogger(__name__)


async def get_periodic_task(
    session: CeleryBeatSessionDep, periodic_task_id: int
) -> PeriodicTask:
    """Get PeriodicTask object by ID.

    :param session: The asynchronous database session.
    :type session: AsyncSession
    :param periodic_task_id: The ID of the periodic task to retrieve.
    :type periodic_task_id: int
    :return: The retrieved PeriodicTask object.
    :rtype: PeriodicTask
    """
    logger.debug("Retrieving period task %s", periodic_task_id)
    return await PeriodicTaskManager.get_or_404(session, id=periodic_task_id)


PeriodicTaskDep = Annotated[PeriodicTask, Depends(get_periodic_task)]
