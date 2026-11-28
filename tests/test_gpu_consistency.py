"""校验 Task、GPU 和 AllocationLog 三类数据的一致性。"""
import pytest
from sqlalchemy import select

from app.core.dispatcher import Dispatcher
from app.core.process_manager import ProcessManager
from app.models.allocation_log import AllocationAction, AllocationLog
from app.models.gpu import GPU, GpuStatus
from app.models.task import Task, TaskStatus
from app.models.user import Role, User


@pytest.mark.asyncio
async def test_task_gpu_and_allocation_log_consistency_across_allocate_and_release(
    db_session_factory, db_session
):
    db_session.add_all([
        User(id=1, username="admin", role=Role.ADMIN),
        GPU(id=1, name="gpu-1", model="RTX 3090", total_memory_mb=24576, status=GpuStatus.IDLE),
        GPU(id=2, name="gpu-2", model="RTX 3090", total_memory_mb=24576, status=GpuStatus.IDLE),
        Task(user_id=1, name="consistency-task", command="echo done",
             status=TaskStatus.QUEUED, gpu_count=2),
    ])
    await db_session.commit()

    dispatcher = Dispatcher(db_session_factory, interval=0.1, max_passes_per_tick=5)
    assert await dispatcher.run_once() == 1

    async with db_session_factory() as allocated:
        task = (await allocated.execute(
            select(Task).where(Task.name == "consistency-task")
        )).scalar_one()
        allocated_gpus = (await allocated.execute(
            select(GPU).where(GPU.current_task_id == task.id).order_by(GPU.id)
        )).scalars().all()
        allocate_logs = (await allocated.execute(
            select(AllocationLog).where(
                AllocationLog.task_id == task.id,
                AllocationLog.action == AllocationAction.ALLOCATE,
            )
        )).scalars().all()

        assert task.status == TaskStatus.PENDING
        assert task.allocated_gpu_ids == ",".join(str(gpu.id) for gpu in allocated_gpus)
        assert len(allocated_gpus) == task.gpu_count
        assert len(allocate_logs) == task.gpu_count
        assert {log.gpu_id for log in allocate_logs} == {gpu.id for gpu in allocated_gpus}

        # 模拟 ProcessManager 成功启动后的 GPU 状态。
        task.status = TaskStatus.RUNNING
        for gpu in allocated_gpus:
            gpu.status = GpuStatus.RUNNING
        await allocated.commit()
        task_id = task.id

    manager = ProcessManager(db_session_factory, interval=0.1)
    async with db_session_factory() as finalizing:
        await manager._finalize_task(finalizing, task_id, 0)

    async with db_session_factory() as finished:
        task = (await finished.execute(select(Task).where(Task.id == task_id))).scalar_one()
        gpus = (await finished.execute(select(GPU).order_by(GPU.id))).scalars().all()
        logs = (await finished.execute(
            select(AllocationLog).where(AllocationLog.task_id == task_id)
        )).scalars().all()

        assert task.status == TaskStatus.COMPLETED
        assert all(gpu.status == GpuStatus.IDLE for gpu in gpus)
        assert all(gpu.current_task_id is None for gpu in gpus)
        assert len([log for log in logs if log.action == AllocationAction.ALLOCATE]) == 2
        assert len([log for log in logs if log.action == AllocationAction.RELEASE]) == 2
