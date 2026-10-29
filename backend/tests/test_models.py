import pytest
from sqlalchemy import select

from app.models import GPU, GpuStatus, Role, User


@pytest.mark.asyncio
async def test_create_user(db_session):
    u = User(username="alice", email="alice@example.com", role=Role.MEMBER)
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)

    assert u.id is not None
    assert u.username == "alice"
    assert u.role == Role.MEMBER
    assert u.gpu_usage_sec == 0


@pytest.mark.asyncio
async def test_create_admin_user(db_session):
    u = User(username="admin", role=Role.ADMIN)
    db_session.add(u)
    await db_session.commit()

    result = await db_session.execute(select(User).where(User.username == "admin"))
    fetched = result.scalar_one()
    assert fetched.role == Role.ADMIN


@pytest.mark.asyncio
async def test_gpu_defaults(db_session):
    g = GPU(name="gpu-0", model="RTX 3090", total_memory_mb=24576)
    db_session.add(g)
    await db_session.commit()
    await db_session.refresh(g)

    assert g.status == GpuStatus.IDLE
    assert g.current_task_id is None
    assert g.last_heartbeat is None


@pytest.mark.asyncio
async def test_gpu_unique_name(db_session):
    g1 = GPU(name="gpu-0", model="RTX 3090", total_memory_mb=24576)
    g2 = GPU(name="gpu-0", model="RTX 4090", total_memory_mb=32768)
    db_session.add_all([g1, g2])

    with pytest.raises(Exception):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_gpu_update_status(db_session):
    g = GPU(name="gpu-1", model="A100", total_memory_mb=40960)
    db_session.add(g)
    await db_session.commit()

    g.status = GpuStatus.ALLOCATED
    g.current_task_id = 100
    await db_session.commit()

    result = await db_session.execute(select(GPU).where(GPU.id == g.id))
    fetched = result.scalar_one()
    assert fetched.status == GpuStatus.ALLOCATED
    assert fetched.current_task_id == 100


@pytest.mark.asyncio
async def test_gpu_list_filter_idle(db_session):
    db_session.add_all([
        GPU(name="gpu-a", model="3090", total_memory_mb=24576, status=GpuStatus.IDLE),
        GPU(name="gpu-b", model="3090", total_memory_mb=24576, status=GpuStatus.RUNNING),
        GPU(name="gpu-c", model="4090", total_memory_mb=32768, status=GpuStatus.IDLE),
    ])
    await db_session.commit()

    result = await db_session.execute(
        select(GPU).where(GPU.status == GpuStatus.IDLE).order_by(GPU.id)
    )
    idle_gpus = result.scalars().all()
    assert len(idle_gpus) == 2
    assert [g.name for g in idle_gpus] == ["gpu-a", "gpu-c"]


@pytest.mark.asyncio
async def test_task_enum_roundtrip(db_session):
    from app.models import Task, TaskStatus

    u = User(username="bob")
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)

    t = Task(user_id=u.id, name="train-bert", command="python train.py", status=TaskStatus.QUEUED)
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)

    assert t.status == TaskStatus.QUEUED
    assert t.gpu_count == 1
    assert t.id is not None


@pytest.mark.asyncio
async def test_allocation_log_enum(db_session):
    from app.models import AllocationAction, AllocationLog

    log = AllocationLog(gpu_id=1, action=AllocationAction.ALLOCATE, actor_user_id=42, notes="dispatcher")
    db_session.add(log)
    await db_session.commit()

    result = await db_session.execute(
        select(AllocationLog).where(AllocationLog.gpu_id == 1)
    )
    fetched = result.scalar_one()
    assert fetched.action == AllocationAction.ALLOCATE