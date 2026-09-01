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

"""Declare the seam an app names its own inventory references through.

An app that persists an inventory id owes the collection job a way to read those
ids back, or the job would delete a tombstone the app can still resolve. The
declaration is a per-app export rather than an import the collector makes,
mirroring ``APP_OWNED_SETTINGS_CLASSES``: the collector never names a concrete
app package.

Providers are gathered from the ``SEP.APPS`` activation list, not from runtime
enablement, so disabling an app in the UI leaves its references in the retained
set — which is the safe direction. Deleting an app's entry from the activation
list while its rows survive is the unsafe one: the ids it holds stop being
retained, and the entities they name become collectible.
"""

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from sqlmodel.ext.asyncio.session import AsyncSession

from app.inventory.constants import RetirableEntityName


@runtime_checkable
class InventoryReferenceProvider(Protocol):
    """Read back the inventory ids one app still persists.

    Raising is the correct response to a read the provider cannot complete: an
    unreadable holder must never be reported as an empty one, which the job
    would take as "nothing referenced" and act on.
    """

    async def __call__(
        self, session: AsyncSession
    ) -> Mapping[RetirableEntityName, set[int]]:
        """Return the inventory ids this app still refers to, per entity type.

        :param session: The asynchronous SEP database session.
        :return: The referenced ids, keyed by inventory entity type.
        """
