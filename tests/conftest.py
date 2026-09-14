import asyncio
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app


@pytest.fixture
def db_session_factory(tmp_path) -> Iterator[async_sessionmaker[AsyncSession]]:
    database_path = (tmp_path / "test.db").as_posix()
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)

    async def prepare_database() -> None:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(prepare_database())
    try:
        yield session_factory
    finally:
        asyncio.run(_dispose_engine(test_engine))


async def _dispose_engine(engine: AsyncEngine) -> None:
    await engine.dispose()


@pytest.fixture
async def api_client(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    async def override_db_session() -> AsyncIterator[AsyncSession]:
        async with db_session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_settings] = lambda: Settings(
        app_env="test",
        openrouter_api_key=None,
        openrouter_chat_api_key=None,
        openrouter_embedding_api_key=None,
    )
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        app.dependency_overrides.clear()
