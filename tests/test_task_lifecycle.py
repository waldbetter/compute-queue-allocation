"""任务生命周期状态和 GPU 释放测试。"""
import pytest
from sqlalchemy import select

from app.api.routes.tasks import cancel_queued_task
from app.core.process_manager import ProcessManager
from app.models.allocation_log import AllocationAction, AllocationLog
from app.models.gpu import GPU, GpuStatus
from app.models.task import Task, TaskStatus
from app.models.user import Role, User


@pytest.mark.asyncio
async def test_cancel_queued_task_sets_cancelled_without_gpu_allocation(db_session_factory, db_session):
    db_session.add(User(id=1, username="admin", role=Role.ADMIN))
    task = Task(
        user_id=1, name="cancel-me", command="echo cancel",
        status=TaskStatus.QUEUED,
    )
    db_session.add(task)
    await db_session.commit()

    response = await cancel_queued_task(task.id, db_session)
    assert response.status == TaskStatus.CANCELLED

    async with db_session_factory() as check:
        saved = (await check.execute(select(Task).where(Task.id == task.id))).scalar_one()
        assert saved.status == TaskStatus.CANCELLED
        assert saved.finished_at is not None
        assert saved.allocated_gpu_id is None
        assert saved.allocated_gpu_ids is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exit_code", "expected_status"),
    [(0, TaskStatus.COMPLETED), (7, TaskStatus.FAILED)],
)
async def test_process_finalization_updates_task_and_releases_all_gpus(
    db_session_factory, db_session, exit_code, expected_status
):
    db_session.add(User(id=1, username="admin", role=Role.ADMIN))
    task = Task(
        user_id=1, name=f"task-exit-{exit_code}", command="python worker.py",
        status=TaskStatus.RUNNING,
        allocated_gpu_id=1, allocated_gpu_ids="1,2",
    )
    db_session.add(task)
    await db_session.flush()
    db_session.add_all([
        GPU(id=1, name="gpu-1", model="RTX 3090", total_memory_mb=24576,
            status=GpuStatus.RUNNING, current_task_id=task.id),
        GPU(id=2, name="gpu-2", model="RTX 3090", total_memory_mb=24576,
            status=GpuStatus.RUNNING, current_task_id=task.id),
        AllocationLog(task_id=task.id, gpu_id=1, action=AllocationAction.ALLOCATE),
        AllocationLog(task_id=task.id, gpu_id=2, action=AllocationAction.ALLOCATE),
    ])
    await db_session.commit()

    manager = ProcessManager(db_session_factory, interval=0.1)
    await manager._finalize_task(db_session, task.id, exit_code)

    async with db_session_factory() as check:
        saved_task = (await check.execute(select(Task).where(Task.id == task.id))).scalar_one()
        gpus = (await check.execute(select(GPU).order_by(GPU.id))).scalars().all()
        release_logs = (await check.execute(
            select(AllocationLog).where(
                AllocationLog.task_id == task.id,
                AllocationLog.action == AllocationAction.RELEASE,
            )
        )).scalars().all()

        assert saved_task.status == expected_status
        assert saved_task.exit_code == exit_code
        assert saved_task.finished_at is not None
        assert all(gpu.status == GpuStatus.IDLE for gpu in gpus)
        assert all(gpu.current_task_id is None for gpu in gpus)
        assert len(release_logs) == 2
        assert {log.gpu_id for log in release_logs} == {1, 2}
