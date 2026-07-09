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

"""Generalize unauthenticated health check endpoint shared by the SEP service apps."""

from collections.abc import Callable
from typing import TYPE_CHECKING

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


def build_health_router(
    session_maker_factory: Callable[[], async_sessionmaker],
) -> APIRouter:
    """Build a router exposing an unauthenticated ``GET /health`` liveness probe.

    The probe confirms the server is accepting requests and its database is
    reachable via a ``SELECT 1`` round-trip. Schema currency is not re-checked
    here: the container entrypoint runs ``alembic upgrade heads`` before the
    server starts, so a reachable database behind a responding server already
    implies migrations are applied.

    :param session_maker_factory: The service's ``get_async_session_maker``;
        called per request to obtain a session bound to that service's engine.
    :return: A router carrying the ``GET /health`` route.
    """
    router = APIRouter()

    @router.get("/health", include_in_schema=False)
    async def health() -> JSONResponse:
        """Return ``200`` when the database is reachable, ``503`` otherwise."""
        try:
            async with session_maker_factory()() as session:
                session: AsyncSession
                (await session.exec(select(1))).one()
        except SQLAlchemyError:
            return JSONResponse(
                {"status": "unavailable"},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return JSONResponse({"status": "ok"})

    return router
