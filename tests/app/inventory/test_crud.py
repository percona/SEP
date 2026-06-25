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

"""Test inventory CRUD manager database-layer behavior."""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import HTTPBadRequestException
from app.inventory.crud import ServiceManager
from tests.app.factories import ServiceWriteFactory


@pytest.mark.asyncio
async def test_dangling_fk_rejected_by_database(session: AsyncSession) -> None:
    """Reject a dangling parent FK at the database layer.

    ``create`` injects the FK from a path-validated parent and runs no parent
    pre-check, so this exercises the SQLite foreign-key constraint directly
    (``PRAGMA foreign_keys = ON`` is enabled on the inventory test engine). The
    DB ``IntegrityError`` surfaces as ``HTTPBadRequestException`` because
    ``BaseSQLModelManager.save`` translates database errors on commit.
    """
    with pytest.raises(HTTPBadRequestException):
        await ServiceManager.create(session, ServiceWriteFactory.build(), node_id=9999)
