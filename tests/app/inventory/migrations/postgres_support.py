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

"""Share the real-PostgreSQL plumbing of the Inventory-track migration tests.

Everything runs over ``asyncpg``: the inventory track's ``env.py`` builds its own
async engine, and the ``test_postgres`` CI job installs the ``postgresql`` group
only, so no sync driver is available to lean on.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy import text, URL
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

T = TypeVar("T")


def run_on_postgres(
    url: URL, coroutine_factory: Callable[[AsyncConnection], Awaitable[T]]
) -> T:
    """Run ``coroutine_factory`` in one transaction on a fresh async engine.

    :param url: The ``asyncpg`` URL of the database to connect to.
    :param coroutine_factory: The work to run against the open connection.
    :return: Whatever ``coroutine_factory`` returned.
    """

    async def _run() -> T:
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                return await coroutine_factory(conn)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


async def drop_public_schema(conn: AsyncConnection) -> None:
    """Drop and recreate the ``public`` schema.

    :param conn: The open connection to run the DDL on.
    """
    await conn.execute(text("DROP SCHEMA public CASCADE"))
    await conn.execute(text("CREATE SCHEMA public"))
