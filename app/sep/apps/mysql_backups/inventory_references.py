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

"""Declare the inventory services the MySQL backup catalog still resolves."""

from collections.abc import Mapping

from sqlmodel.ext.asyncio.session import AsyncSession

from app.inventory.constants import RetirableEntityName
from app.sep.apps.framework.inventory_references import InventoryReferenceProvider
from app.sep.apps.mysql_backups.crud import MysqlBackupRunManager


async def referenced_inventory_entities(
    session: AsyncSession,
) -> Mapping[RetirableEntityName, set[int]]:
    """Return the inventory services the recorded backup runs point at.

    :param session: The asynchronous SEP database session.
    :return: The referenced service ids, keyed by inventory entity type.
    """
    return {
        RetirableEntityName.SERVICE: await MysqlBackupRunManager.referenced_service_ids(
            session
        )
    }


INVENTORY_REFERENCE_PROVIDERS: list[InventoryReferenceProvider] = [
    referenced_inventory_entities,
]
