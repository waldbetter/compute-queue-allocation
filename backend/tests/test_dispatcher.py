import pytest
from sqlalchemy import select

from app.core.dispatcher import Dispatcher
from app.models.allocation_log import AllocationAction, AllocationLog
from app.models.gpu import GPU, GpuStatus
from app.models.task import Task, TaskStatus
from app.models.user import Role, User


async def _seed_dispatcher(db_session):
    db_session.add_all([
        User(id=1, username="admin", role=Role.ADMIN),
        User(id=2, username="alice", role=Role.MEMBER),
        GPU(id=1, name="gpu-0", model="RTX 3090", total_memory_mb=24576, status=GpuStatus.IDLE),
        GPU(id=2, name="gpu-1", model="RTX 3090", total_memory_mb=24576, status=GpuStatus.IDLE),
        GPU(id=3, name="gpu-2", model="A100", total_memory_mb=40960, status=GpuStatus.RUNNING),
    ])
    await db_session.commit()


async def _task_count(db, status_filter=None):
    stmt = select(Task)
    if status_filter is not None:
        stmt = stmt.where(Task.status.in_(status_filter))
    return (await db.execute(stmt)).scalars().all()


@pytest.mark.asyncio
async def test_dispatcher_no_tasks(db_session_factory, db_session):
    await _seed_dispatcher(db_session)
    dispatcher = Dispatcher(db_session_factory, interval=0.1, max_passes_per_tick=5)

    allocated = await dispatcher.run_once()
    assert allocated == 0

    async with db_session_factory() as check:
        gpus = (await check.execute(select(GPU).where(GPU.status == GpuStatus.IDLE))).scalars().all()
        assert len(gpus) == 2


@pytest.mark.asyncio
async def test_dispatcher_no_idle_gpu(db_session_factory, db_session):
    await _seed_dispatcher(db_session)

    db_session.add(GPU(id=4, name="gpu-3", model="3090", total_memory_mb=24576, status=GpuStatus.MAINTENANCE))
    db_session.add_all([
        Task(user_id=1, name="t1", command="echo 1", status=TaskStatus.QUEUED),
        Task(user_id=1, name="t2", command="echo 2", status=TaskStatus.QUEUED),
    ])
    await db_session.commit()

    await db_session.execute(
        select(GPU).where(GPU.status == GpuStatus.IDLE).execution_options()
    )

    async with db_session_factory() as check:
        idle_count = (await check.execute(select(GPU).where(GPU.status == GpuStatus.IDLE))).scalars().all()
        for g in idle_count:
            g.status = GpuStatus.RUNNING
        await check.commit()

    dispatcher = Dispatcher(db_session_factory, interval=0.1, max_passes_per_tick=5)
    allocated = await dispatcher.run_once()
    assert allocated == 0

    async with db_session_factory() as check:
        tasks = (await check.execute(select(Task))).scalars().all()
        assert all(t.status == TaskStatus.QUEUED for t in tasks)


@pytest.mark.asyncio
async def test_dispatcher_success_allocates_one(db_session_factory, db_session):
    await _seed_dispatcher(db_session)
    db_session.add(Task(user_id=1, name="train-01", command="python train.py", status=TaskStatus.QUEUED))
    await db_session.commit()

    dispatcher = Dispatcher(db_session_factory, interval=0.1, max_passes_per_tick=5)
    allocated = await dispatcher.run_once()
    assert allocated == 1

    async with db_session_factory() as check:
        gpu = (await check.execute(select(GPU).where(GPU.id == 1))).scalar_one()
        assert gpu.status == GpuStatus.ALLOCATED
        assert gpu.current_task_id is not None

        task = (await check.execute(select(Task).where(Task.name == "train-01"))).scalar_one()
        assert task.status == TaskStatus.PENDING
        assert task.allocated_gpu_id == 1

        log = (await check.execute(
            select(AllocationLog).where(AllocationLog.task_id == task.id)
        )).scalar_one_or_none()
        assert log is not None
        assert log.action == AllocationAction.ALLOCATE
        assert log.gpu_id == 1


@pytest.mark.asyncio
async def test_dispatcher_does_not_double_allocate(db_session_factory, db_session):
    await _seed_dispatcher(db_session)
    db_session.add(Task(user_id=1, name="once-task", command="echo once", status=TaskStatus.QUEUED))
    await db_session.commit()

    dispatcher = Dispatcher(db_session_factory, interval=0.1, max_passes_per_tick=5)
    first = await dispatcher.run_once()
    second = await dispatcher.run_once()

    assert first == 1
    assert second == 0

    async with db_session_factory() as check:
        task = (await check.execute(select(Task).where(Task.name == "once-task"))).scalar_one()
        assert task.status == TaskStatus.PENDING
        assert task.allocated_gpu_id is not None

        logs = (await check.execute(
            select(AllocationLog).where(AllocationLog.task_id == task.id)
        )).scalars().all()
        assert len(logs) == 1


@pytest.mark.asyncio
async def test_dispatcher_fcfs_multiple(db_session_factory, db_session):
    await _seed_dispatcher(db_session)

    import datetime
    t1 = Task(user_id=1, name="first", command="echo 1", status=TaskStatus.QUEUED)
    t2 = Task(user_id=2, name="second", command="echo 2", status=TaskStatus.QUEUED)
    t3 = Task(user_id=1, name="third", command="echo 3", status=TaskStatus.QUEUED)
    db_session.add_all([t1, t2, t3])
    await db_session.commit()

    dispatcher = Dispatcher(db_session_factory, interval=0.1, max_passes_per_tick=10)
    allocated = await dispatcher.run_once()
    assert allocated == 2

    async with db_session_factory() as check:
        t1_db = (await check.execute(select(Task).where(Task.name == "first"))).scalar_one()
        t2_db = (await check.execute(select(Task).where(Task.name == "second"))).scalar_one()
        t3_db = (await check.execute(select(Task).where(Task.name == "third"))).scalar_one()

        assert t1_db.status == TaskStatus.PENDING
        assert t2_db.status == TaskStatus.PENDING
        assert t3_db.status == TaskStatus.QUEUED

        assert t1_db.allocated_gpu_id == 1
        assert t2_db.allocated_gpu_id == 2
        assert t3_db.allocated_gpu_id is None

        idle_count = (await check.execute(select(GPU).where(GPU.status == GpuStatus.IDLE))).scalars().all()
        assert len(idle_count) == 0


@pytest.mark.asyncio
async def test_dispatcher_skips_non_queued_tasks(db_session_factory, db_session):
    await _seed_dispatcher(db_session)

    db_session.add_all([
        Task(user_id=1, name="already-pending", command="echo p", status=TaskStatus.PENDING, allocated_gpu_id=3),
        Task(user_id=1, name="already-running", command="echo r", status=TaskStatus.RUNNING, allocated_gpu_id=3),
        Task(user_id=1, name="completed", command="echo c", status=TaskStatus.COMPLETED),
        Task(user_id=1, name="fresh", command="echo f", status=TaskStatus.QUEUED),
    ])
    await db_session.commit()

    dispatcher = Dispatcher(db_session_factory, interval=0.1, max_passes_per_tick=5)
    allocated = await dispatcher.run_once()
    assert allocated == 1

    async with db_session_factory() as check:
        fresh = (await check.execute(select(Task).where(Task.name == "fresh"))).scalar_one()
        assert fresh.status == TaskStatus.PENDING
        assert fresh.allocated_gpu_id is not None

        pending = (await check.execute(select(Task).where(Task.name == "already-pending"))).scalar_one()
        assert pending.allocated_gpu_id == 3

        running = (await check.execute(select(Task).where(Task.name == "already-running"))).scalar_one()
        assert running.allocated_gpu_id == 3