from typing import Annotated
from typing import AsyncGenerator

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.tasks.db import get_async_session


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async_session = get_async_session()
    async with async_session() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
