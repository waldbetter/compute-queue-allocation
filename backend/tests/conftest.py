from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def db_url(tmp_path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"


@pytest_asyncio.fixture
async def db_engine(db_url) -> AsyncGenerator[AsyncEngine, None]:
    from app.models import Base

    engine = create_async_engine(
        db_url,
        echo=False,
        future=True,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session_factory(db_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def db_session(db_session_factory) -> AsyncGenerator[AsyncSession, None]:
    async with db_session_factory() as session:
        try:
            yield session
            await session.rollback()
        finally:
            await session.close()


@pytest_asyncio.fixture
async def seed_basic(db_session) -> AsyncSession:
    from app.models.gpu import GPU, GpuStatus
    from app.models.user import Role, User

    db_session.add_all([
        User(id=1, username="admin", role=Role.ADMIN),
        User(id=2, username="alice", role=Role.MEMBER),
        User(id=3, username="bob", role=Role.MEMBER),
        GPU(id=1, name="gpu-0", model="RTX 3090", total_memory_mb=24576, status=GpuStatus.IDLE),
        GPU(id=2, name="gpu-1", model="RTX 3090", total_memory_mb=24576, status=GpuStatus.IDLE),
        GPU(id=3, name="gpu-2", model="A100", total_memory_mb=40960, status=GpuStatus.IDLE),
    ])
    await db_session.commit()
    await db_session.close()
    return db_session