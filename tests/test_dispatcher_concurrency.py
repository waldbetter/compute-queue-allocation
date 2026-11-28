"""MySQL 并发分配测试。

安全要求：
1. 仅使用 GPU_QUEUE_TEST_MYSQL_URL 环境变量指定的独立测试库。
2. 数据库名必须以 _test 结尾；fixture 会 drop_all/create_all。
3. 运行前停止后端服务，禁止连接开发/生产数据库。
"""
import asyncio
import os

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.models import Base
from app.models.allocation_log import AllocationAction, AllocationLog
from app.models.gpu import GPU, GpuStatus
from app.models.task import Task, TaskStatus
from app.models.user import Role, User


pytestmark = [
    pytest.mark.mysql,
    pytest.mark.skipif(
        not os.environ.get("GPU_QUEUE_TEST_MYSQL_URL"),
        reason="Set GPU_QUEUE_TEST_MYSQL_URL to a dedicated *_test MySQL database",
    ),
]


@pytest.fixture(scope="session")
def mysql_engine():
    url = os.environ.get("GPU_QUEUE_TEST_MYSQL_URL")
    if not url:
        pytest.skip("GPU_QUEUE_TEST_MYSQL_URL is not configured")
    database = make_url(url).database
    if not database or not database.endswith("_test"):
        pytest.fail(
            "Refusing to run destructive concurrency tests: "
            "database name must end with '_test'"
        )
    return create_async_engine(url, echo=False, poolclass=NullPool, future=True)


@pytest.fixture(scope="session")
def mysql_session_factory(mysql_engine):
    return async_sessionmaker(mysql_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def isolated_mysql_schema(mysql_engine):
    async with mysql_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with mysql_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _seed(mysql_session_factory, gpu_count: int, task_count: int):
    async with mysql_session_factory() as db:
        db.add(User(id=1, username="admin", role=Role.ADMIN))
        db.add_all([
            GPU(
                id=i + 1,
                name=f"gpu-{i}",
                model="RTX 3090",
                total_memory_mb=24576,
                status=GpuStatus.IDLE,
            )
            for i in range(gpu_count)
        ])
        db.add_all([
            Task(
                id=i + 1,
                user_id=1,
                name=f"task-{i}",
                command=f"echo {i}",
                status=TaskStatus.QUEUED,
            )
            for i in range(task_count)
        ])
        await db.commit()


async def _run_concurrent_attempts(mysql_session_factory, count: int):
    from app.core.dispatcher import Dispatcher

    dispatcher = Dispatcher(mysql_session_factory, interval=0.1, max_passes_per_tick=1)

    async def attempt():
        async with mysql_session_factory() as db:
            return await dispatcher.try_allocate_gpu(db)

    # 不吞掉数据库异常；异常本身就是需要调查的测试失败。
    return await asyncio.gather(*(attempt() for _ in range(count)))


@pytest.mark.asyncio
async def test_concurrent_allocation_single_gpu(mysql_session_factory):
    await _seed(mysql_session_factory, gpu_count=1, task_count=50)
    results = await _run_concurrent_attempts(mysql_session_factory, 50)

    assert sum(result is True for result in results) == 1
    async with mysql_session_factory() as db:
        allocations = (await db.execute(
            select(AllocationLog).where(AllocationLog.action == AllocationAction.ALLOCATE)
        )).scalars().all()
        gpus = (await db.execute(select(GPU))).scalars().all()
        pending = (await db.execute(
            select(Task).where(Task.status == TaskStatus.PENDING)
        )).scalars().all()
        queued = (await db.execute(
            select(Task).where(Task.status == TaskStatus.QUEUED)
        )).scalars().all()

        assert len(allocations) == 1
        assert len(gpus) == 1 and gpus[0].status == GpuStatus.ALLOCATED
        assert len(pending) == 1
        assert len(queued) == 49


@pytest.mark.asyncio
async def test_concurrent_allocation_two_gpus(mysql_session_factory):
    await _seed(mysql_session_factory, gpu_count=2, task_count=30)
    results = await _run_concurrent_attempts(mysql_session_factory, 30)

    assert sum(result is True for result in results) == 2
    async with mysql_session_factory() as db:
        allocations = (await db.execute(
            select(AllocationLog).where(AllocationLog.action == AllocationAction.ALLOCATE)
        )).scalars().all()
        pending = (await db.execute(
            select(Task).where(Task.status == TaskStatus.PENDING)
        )).scalars().all()
        queued = (await db.execute(
            select(Task).where(Task.status == TaskStatus.QUEUED)
        )).scalars().all()

        assert len(allocations) == 2
        assert len(pending) == 2
        assert len(queued) == 28


@pytest.mark.asyncio
async def test_concurrent_no_double_allocation(mysql_session_factory):
    await _seed(mysql_session_factory, gpu_count=1, task_count=100)
    await _run_concurrent_attempts(mysql_session_factory, 100)

    async with mysql_session_factory() as db:
        gpu = (await db.execute(select(GPU).where(GPU.id == 1))).scalar_one()
        allocated_tasks = (await db.execute(
            select(Task).where(Task.allocated_gpu_id == 1)
        )).scalars().all()
        allocations = (await db.execute(
            select(AllocationLog).where(AllocationLog.action == AllocationAction.ALLOCATE)
        )).scalars().all()

        assert gpu.status == GpuStatus.ALLOCATED
        assert gpu.current_task_id is not None
        assert len(allocated_tasks) == 1
        assert allocated_tasks[0].id == gpu.current_task_id
        assert len(allocations) == 1
        assert allocations[0].task_id == gpu.current_task_id
