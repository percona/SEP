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

"""Define dependencies for the om_bootstrap plugin."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends

from app.sep.apps.om_bootstrap.crud import BootstrapRunManager
from app.sep.apps.om_bootstrap.models import BootstrapRun
from app.sep.deps import SessionDep


async def get_run_for_update(run_id: UUID, session: SessionDep) -> BootstrapRun:
    """Read the path's run under its row lock, for a route that writes it back.

    ``session`` is the same request-scoped session the route itself receives
    through :data:`~app.sep.deps.SessionDep`, so the lock taken here and the
    route's save share one transaction.

    :param run_id: The run's id, from the route's path.
    :param session: The request's database session; its transaction holds the lock.
    :raises HTTPNotFoundException: When there is no such run.
    :return: The run.
    """
    return await BootstrapRunManager.get_run(session, run_id, for_update=True)


LockedRun = Annotated[BootstrapRun, Depends(get_run_for_update)]
