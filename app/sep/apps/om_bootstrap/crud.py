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

"""Define reads and writes for :class:`BootstrapRun`.

A plain :class:`~app.core.db.crud.BaseSQLModelManager`, unlike ``om_inventory``'s
own :class:`~app.sep.apps.om_inventory.crud.ProbeRunManager` sibling
(``OmHost``/``OmService``), which hand-writes attribute-by-attribute upserts for
a documented reason -- freshness columns a blanket update would silently wipe.
``BootstrapRun`` has no such column: every write here replaces the whole row
(the ``hosts`` document included, per ``models.py``'s "read and written whole"
design), so the manager's generic ``save``/``update`` need no override.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.crud import BaseSQLModelManager
from app.sep.apps.om_bootstrap.models import BootstrapRun

__all__ = ["BootstrapRunManager", "get_run"]


class BootstrapRunManager(BaseSQLModelManager):
    """Manage :class:`BootstrapRun` CRUD operations.

    :cvar Model: The SQLModel class this manager is responsible for.
    """

    Model = BootstrapRun


async def get_run(session: AsyncSession, run_id: UUID) -> BootstrapRun | None:
    """Return one run.

    :param session: The database session.
    :param run_id: The run's id.
    :return: The run, or ``None``.
    """
    return await session.get(BootstrapRun, run_id)
