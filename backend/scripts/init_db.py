import asyncio

from sqlalchemy.ext.asyncio import AsyncEngine

from app.models.base import Base
from app.infrastructure.mysql.database import engine


async def init_schema(engine: AsyncEngine, reset: bool = False) -> None:
    from app.models import user, gpu, task, allocation_log  # noqa: F401

    async with engine.begin() as conn:
        if reset:
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Drop existing tables before creating")
    args = parser.parse_args()

    async def run():
        await init_schema(engine, reset=args.reset)
        print("Schema initialized successfully.")
        # ✅ 新增：主动释放连接池，关闭所有底层mysql连接
        await engine.dispose()

    asyncio.run(run())
