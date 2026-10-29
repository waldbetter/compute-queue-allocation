"""
Story 3-4: 并发分配安全测试 (MySQL)

前置条件：
  - 本机 MySQL 8.0+ 运行中 (root / 123456)
  - 数据库 gpu_queue 存在 (本测试会自动 create_all / drop_all)

验证目标：
  - N 个并发协程同时 try_allocate_gpu() 时：
    * 只有 1 个成功（1 GPU + 50 QUEUED 任务）
    * 只有 1 条 ALLOCATE 日志
    * GPU 状态正确变为 ALLOCATED，其他保持 IDLE
    * 被分配任务变为 PENDING，其他保持 QUEUED
"""
import asyncio
import os
import sys
from datetime import datetime

import pytest
import pytest_asyncio

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_MYSQL_TESTS") == "1",
    reason="MySQL tests skipped",
)

MYSQL_URL = "mysql+aiomysql://root:123456@localhost:3306/gpu_queue"

try:
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    HAS_SA = True
except ImportError:
    HAS_SA = False


@pytest.fixture(scope="session")
def mysql_engine() -> AsyncEngine:
    if not HAS_SA:
        pytest.skip("SQLAlchemy not available")
    engine = create_async_engine(
        MYSQL_URL,
        echo=False,
        poolclass=NullPool,
        future=True,
    )
    return engine


@pytest.fixture(scope="session")
def mysql_session_factory(mysql_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(mysql_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def _mysql_schema(mysql_engine):
    from app.models import Base
    async with mysql_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with mysql_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _seed_base(mysql_session_factory):
    from app.models.gpu import GPU, GpuStatus
    from app.models.user import Role, User
    async with mysql_session_factory() as db:
        db.add_all([
            User(id=1, username="admin", role=Role.ADMIN),
        ])
        await db.commit()


async def _insert_one_idle_gpu(mysql_session_factory, gpu_id=1):
    from app.models.gpu import GPU, GpuStatus
    async with mysql_session_factory() as db:
        db.add(GPU(
            id=gpu_id, name=f"gpu-{gpu_id-1}", model="RTX 3090",
            total_memory_mb=24576, status=GpuStatus.IDLE,
        ))
        await db.commit()


async def _insert_n_queued_tasks(mysql_session_factory, n, start_id=1):
    from app.models.task import Task, TaskStatus
    async with mysql_session_factory() as db:
        tasks = [
            Task(
                id=start_id + i,
                user_id=1,
                name=f"task-{i}",
                command=f"echo {i}",
                status=TaskStatus.QUEUED,
            )
            for i in range(n)
        ]
        db.add_all(tasks)
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.mysql
async def test_concurrent_allocation_single_gpu(mysql_session_factory):
    """
    1 IDLE GPU + 50 QUEUED tasks + 50 并发 try_allocate_gpu()
    => 只有 1 次成功分配，只有 1 条 ALLOCATE 日志
    """
    from app.core.dispatcher import Dispatcher
    from app.models.allocation_log import AllocationAction, AllocationLog
    from app.models.gpu import GPU, GpuStatus
    from app.models.task import Task, TaskStatus

    await _seed_base(mysql_session_factory)
    await _insert_one_idle_gpu(mysql_session_factory)
    N = 50
    await _insert_n_queued_tasks(mysql_session_factory, N, start_id=1)

    dispatcher = Dispatcher(mysql_session_factory, interval=0.1, max_passes_per_tick=1)

    async def one_try():
        try:
            async with mysql_session_factory() as db:
                return await dispatcher.try_allocate_gpu(db)
        except Exception:
            return False

    coros = [one_try() for _ in range(N)]
    results = await asyncio.gather(*coros, return_exceptions=False)

    success_count = sum(1 for r in results if r is True)
    print(f"[concurrent] success_count={success_count} (expect 1)")

    assert success_count == 1, f"Expected 1 success, got {success_count}"

    async with mysql_session_factory() as check:
        allocs = (await check.execute(
            select(AllocationLog).where(AllocationLog.action == AllocationAction.ALLOCATE)
        )).scalars().all()
        print(f"[concurrent] ALLOCATE logs={len(allocs)} (expect 1)")
        assert len(allocs) == 1, f"Expected 1 ALLOCATE log, got {len(allocs)}"

        gpus = (await check.execute(select(GPU).order_by(GPU.id))).scalars().all()
        idle_gpus = [g for g in gpus if g.status == GpuStatus.IDLE]
        alloc_gpus = [g for g in gpus if g.status == GpuStatus.ALLOCATED]
        print(f"[concurrent] gpus: idle={len(idle_gpus)} allocated={len(alloc_gpus)}")
        assert len(idle_gpus) == 0
        assert len(alloc_gpus) == 1

        tasks = (await check.execute(select(Task).order_by(Task.id))).scalars().all()
        pending_tasks = [t for t in tasks if t.status == TaskStatus.PENDING]
        queued_tasks = [t for t in tasks if t.status == TaskStatus.QUEUED]
        print(f"[concurrent] tasks: pending={len(pending_tasks)} queued={len(queued_tasks)}")
        assert len(pending_tasks) == 1
        assert len(queued_tasks) == N - 1


@pytest.mark.asyncio
@pytest.mark.mysql
async def test_concurrent_allocation_two_gpus(mysql_session_factory):
    """
    2 IDLE GPU + 30 QUEUED tasks + 30 并发
    => 只有 2 次成功，只有 2 条 ALLOCATE 日志
    """
    from app.core.dispatcher import Dispatcher
    from app.models.allocation_log import AllocationAction, AllocationLog
    from app.models.gpu import GPU, GpuStatus
    from app.models.task import Task, TaskStatus

    await _seed_base(mysql_session_factory)
    await _insert_one_idle_gpu(mysql_session_factory, gpu_id=1)
    await _insert_one_idle_gpu(mysql_session_factory, gpu_id=2)
    N = 30
    await _insert_n_queued_tasks(mysql_session_factory, N, start_id=1)

    dispatcher = Dispatcher(mysql_session_factory, interval=0.1, max_passes_per_tick=1)

    async def one_try():
        try:
            async with mysql_session_factory() as db:
                return await dispatcher.try_allocate_gpu(db)
        except Exception:
            return False

    coros = [one_try() for _ in range(N)]
    results = await asyncio.gather(*coros, return_exceptions=False)

    success_count = sum(1 for r in results if r is True)
    print(f"[2gpu] success_count={success_count} (expect 2)")
    assert success_count == 2

    async with mysql_session_factory() as check:
        allocs = (await check.execute(
            select(AllocationLog).where(AllocationLog.action == AllocationAction.ALLOCATE)
        )).scalars().all()
        assert len(allocs) == 2

        gpus = (await check.execute(select(GPU).order_by(GPU.id))).scalars().all()
        idle = [g for g in gpus if g.status == GpuStatus.IDLE]
        alloc = [g for g in gpus if g.status == GpuStatus.ALLOCATED]
        assert len(idle) == 0
        assert len(alloc) == 2

        tasks = (await check.execute(select(Task).order_by(Task.id))).scalars().all()
        pending = [t for t in tasks if t.status == TaskStatus.PENDING]
        queued = [t for t in tasks if t.status == TaskStatus.QUEUED]
        assert len(pending) == 2
        assert len(queued) == N - 2


@pytest.mark.asyncio
@pytest.mark.mysql
async def test_concurrent_no_double_allocation(mysql_session_factory):
    """
    1 IDLE GPU + 100 QUEUED tasks + 100 并发
    => GPU 的 current_task_id 不应该有冲突，任务 allocated_gpu_id 只应有一个
    """
    from app.core.dispatcher import Dispatcher
    from app.models.allocation_log import AllocationAction, AllocationLog
    from app.models.gpu import GPU, GpuStatus
    from app.models.task import Task, TaskStatus

    await _seed_base(mysql_session_factory)
    await _insert_one_idle_gpu(mysql_session_factory)
    N = 100
    await _insert_n_queued_tasks(mysql_session_factory, N, start_id=1)

    dispatcher = Dispatcher(mysql_session_factory, interval=0.1, max_passes_per_tick=1)

    async def one_try():
        try:
            async with mysql_session_factory() as db:
                return await dispatcher.try_allocate_gpu(db)
        except Exception:
            return False

    coros = [one_try() for _ in range(N)]
    await asyncio.gather(*coros, return_exceptions=False)

    async with mysql_session_factory() as check:
        gpu = (await check.execute(select(GPU).where(GPU.id == 1))).scalar_one()
        assert gpu.status == GpuStatus.ALLOCATED
        assert gpu.current_task_id is not None

        allocated_tasks = (await check.execute(
            select(Task).where(Task.allocated_gpu_id == 1)
        )).scalars().all()
        assert len(allocated_tasks) == 1
        assert allocated_tasks[0].id == gpu.current_task_id

        allocs = (await check.execute(
            select(AllocationLog).where(AllocationLog.action == AllocationAction.ALLOCATE)
        )).scalars().all()
        assert len(allocs) == 1
        assert allocs[0].task_id == gpu.current_task_id