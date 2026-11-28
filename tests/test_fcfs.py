"""FCFS 排队顺序测试。依赖项目 backend/tests/conftest.py 提供的 SQLite fixtures。"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.dispatcher import Dispatcher
from app.models.gpu import GPU, GpuStatus
from app.models.task import Task, TaskStatus
from app.models.user import Role, User


@pytest.mark.asyncio
async def test_fcfs_allocates_tasks_by_submitted_time_then_id(db_session_factory, db_session):
    db_session.add_all([
        User(id=1, username="admin", role=Role.ADMIN),
        GPU(id=1, name="gpu-1", model="RTX 3090", total_memory_mb=24576, status=GpuStatus.IDLE),
        GPU(id=2, name="gpu-2", model="RTX 3090", total_memory_mb=24576, status=GpuStatus.IDLE),
    ])
    base = datetime(2026, 1, 1, 10, 0, 0)
    # 插入顺序刻意与提交时间顺序不同，验证调度器按时间排序。
    db_session.add_all([
        Task(user_id=1, name="later", command="echo later",
             status=TaskStatus.QUEUED, submitted_at=base + timedelta(seconds=20)),
        Task(user_id=1, name="first", command="echo first",
             status=TaskStatus.QUEUED, submitted_at=base),
        Task(user_id=1, name="middle", command="echo middle",
             status=TaskStatus.QUEUED, submitted_at=base + timedelta(seconds=10)),
    ])
    await db_session.commit()

    dispatcher = Dispatcher(db_session_factory, interval=0.1, max_passes_per_tick=5)
    assert await dispatcher.run_once() == 2

    async with db_session_factory() as check:
        first = (await check.execute(select(Task).where(Task.name == "first"))).scalar_one()
        middle = (await check.execute(select(Task).where(Task.name == "middle"))).scalar_one()
        later = (await check.execute(select(Task).where(Task.name == "later"))).scalar_one()

        assert first.status == TaskStatus.PENDING
        assert middle.status == TaskStatus.PENDING
        assert later.status == TaskStatus.QUEUED
        assert first.allocated_gpu_id == 1
        assert middle.allocated_gpu_id == 2
        assert later.allocated_gpu_id is None


@pytest.mark.asyncio
async def test_fcfs_same_timestamp_uses_task_id_as_tiebreaker(db_session_factory, db_session):
    db_session.add_all([
        User(id=1, username="admin", role=Role.ADMIN),
        GPU(id=1, name="gpu-1", model="RTX 3090", total_memory_mb=24576, status=GpuStatus.IDLE),
    ])
    same_time = datetime(2026, 1, 1, 10, 0, 0)
    # 显式指定 ID，保证时间相同时 id 较小的任务排在前面。
    db_session.add_all([
        Task(id=20, user_id=1, name="id-20", command="echo 20",
             status=TaskStatus.QUEUED, submitted_at=same_time),
        Task(id=10, user_id=1, name="id-10", command="echo 10",
             status=TaskStatus.QUEUED, submitted_at=same_time),
    ])
    await db_session.commit()

    dispatcher = Dispatcher(db_session_factory, interval=0.1, max_passes_per_tick=1)
    assert await dispatcher.run_once() == 1

    async with db_session_factory() as check:
        earlier_id = (await check.execute(select(Task).where(Task.id == 10))).scalar_one()
        later_id = (await check.execute(select(Task).where(Task.id == 20))).scalar_one()
        assert earlier_id.status == TaskStatus.PENDING
        assert later_id.status == TaskStatus.QUEUED
