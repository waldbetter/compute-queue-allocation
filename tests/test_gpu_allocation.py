"""GPU 单卡/多卡分配与资源不足场景。"""
import pytest
from sqlalchemy import select

from app.core.dispatcher import Dispatcher
from app.models.allocation_log import AllocationAction, AllocationLog
from app.models.gpu import GPU, GpuStatus
from app.models.task import Task, TaskStatus
from app.models.user import Role, User


@pytest.mark.asyncio
async def test_gpu_allocation_is_atomic_for_two_same_model_gpus(db_session_factory, db_session):
    db_session.add_all([
        User(id=1, username="admin", role=Role.ADMIN),
        GPU(id=1, name="gpu-1", model="RTX 3090", total_memory_mb=24576, status=GpuStatus.IDLE),
        GPU(id=2, name="gpu-2", model="RTX 3090", total_memory_mb=24576, status=GpuStatus.IDLE),
        GPU(id=3, name="gpu-3", model="A100", total_memory_mb=40960, status=GpuStatus.IDLE),
        Task(user_id=1, name="two-card", command="echo train",
             status=TaskStatus.QUEUED, gpu_count=2),
    ])
    await db_session.commit()

    dispatcher = Dispatcher(db_session_factory, interval=0.1, max_passes_per_tick=5)
    assert await dispatcher.run_once() == 1

    async with db_session_factory() as check:
        task = (await check.execute(select(Task).where(Task.name == "two-card"))).scalar_one()
        gpus = (await check.execute(select(GPU).order_by(GPU.id))).scalars().all()
        logs = (await check.execute(
            select(AllocationLog).where(
                AllocationLog.task_id == task.id,
                AllocationLog.action == AllocationAction.ALLOCATE,
            )
        )).scalars().all()

        assert task.status == TaskStatus.PENDING
        assert task.allocated_gpu_id == 1
        assert task.allocated_gpu_ids == "1,2"
        assert [gpu.status for gpu in gpus] == [
            GpuStatus.ALLOCATED, GpuStatus.ALLOCATED, GpuStatus.IDLE
        ]
        assert {gpu.current_task_id for gpu in gpus[:2]} == {task.id}
        assert len(logs) == 2
        assert {log.gpu_id for log in logs} == {1, 2}


@pytest.mark.asyncio
async def test_gpu_allocation_does_not_partially_allocate_when_insufficient(db_session_factory, db_session):
    db_session.add_all([
        User(id=1, username="admin", role=Role.ADMIN),
        GPU(id=1, name="gpu-1", model="RTX 3090", total_memory_mb=24576, status=GpuStatus.IDLE),
        GPU(id=2, name="gpu-2", model="A100", total_memory_mb=40960, status=GpuStatus.IDLE),
        Task(user_id=1, name="needs-two-3090", command="echo train",
             status=TaskStatus.QUEUED, gpu_count=2, gpu_model_preference="RTX 3090"),
    ])
    await db_session.commit()

    dispatcher = Dispatcher(db_session_factory, interval=0.1, max_passes_per_tick=5)
    assert await dispatcher.run_once() == 0

    async with db_session_factory() as check:
        task = (await check.execute(
            select(Task).where(Task.name == "needs-two-3090")
        )).scalar_one()
        gpus = (await check.execute(select(GPU).order_by(GPU.id))).scalars().all()
        logs = (await check.execute(
            select(AllocationLog).where(AllocationLog.action == AllocationAction.ALLOCATE)
        )).scalars().all()

        assert task.status == TaskStatus.QUEUED
        assert task.allocated_gpu_id is None
        assert task.allocated_gpu_ids is None
        assert all(gpu.status == GpuStatus.IDLE for gpu in gpus)
        assert logs == []
