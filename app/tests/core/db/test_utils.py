"""Define tests for the app.core.db.utils module."""

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.core.db.utils import get_async_session_maker_from_engine


@pytest.mark.asyncio
async def test_get_async_session_maker_from_engine():
    """Verify that the sessionmaker is correctly configured with AsyncSession and expire_on_commit=False."""
    engine: AsyncEngine = create_async_engine("sqlite+aiosqlite:///:memory:")

    session_maker = get_async_session_maker_from_engine(engine)
    assert session_maker.kw.get("expire_on_commit") is False

    async with session_maker() as session:
        assert isinstance(session, AsyncSession)
