"""多卡同型号分配（story 3-9）测试。

覆盖范围：
- Dispatcher：多卡一次性分配、型号偏好、凑不齐队首阻塞（FCFS）、无偏好回退最早空闲卡型号
- ProcessManager：多卡任务结束批量释放全部 GPU
- API：gpu_count 1-64 校验
- Model：allocated_gpu_ids 字段持久化
"""
import asyncio
import sys

import pytest
from sqlalchemy import select

from app.core.dispatcher import Dispatcher
from app.core.process_manager import ProcessManager
from app.models.allocation_log import AllocationAction, AllocationLog
from app.models.gpu import GPU, GpuStatus
from app.models.task import Task, TaskStatus
from app.models.user import Role, User


def _python_exit(rc: int) -> str:
    return f'"{sys.executable}" -c "import sys; sys.exit({rc})"'


async def _seed(db_session, gpus: list[tuple[int, str, str]]):
    """gpus: [(id, name, model), ...]，全部 IDLE。"""
    db_session.add_all([
        User(id=1, username="admin", role=Role.ADMIN),
        *[
            GPU(id=gid, name=name, model=model, total_memory_mb=24576, status=GpuStatus.IDLE)
            for gid, name, model in gpus
        ],
    ])
    await db_session.commit()


async def _gpu_state(db, gpu_id):
    return (await db.execute(select(GPU).where(GPU.id == gpu_id))).scalar_one()


async def _task_by_name(db, name):
    return (await db.execute(select(Task).where(Task.name == name))).scalar_one()


# ═══════════════════════════════════════════════════════════════
# Dispatcher：多卡一次性分配（story 3-9 核心）
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_multigpu_allocates_two_same_model(db_session_factory, db_session):
    # 2×RTX 3090 空闲 + 1×A100 空闲
    await _seed(db_session, [
        (1, "gpu-1", "RTX 3090"),
        (2, "gpu-2", "RTX 3090"),
        (3, "gpu-3", "A100"),
    ])
    db_session.add(Task(
        user_id=1, name="ddp-train", command="python train.py",
        status=TaskStatus.QUEUED, gpu_count=2,
    ))
    await db_session.commit()

    dispatcher = Dispatcher(db_session_factory, interval=0.1, max_passes_per_tick=5)
    allocated = await dispatcher.run_once()
    assert allocated == 1

    async with db_session_factory() as check:
        task = await _task_by_name(check, "ddp-train")
        assert task.status == TaskStatus.PENDING
        assert task.allocated_gpu_id == 1          # 第一张卡
        assert task.allocated_gpu_ids == "1,2"     # 逗号串

        g1 = await _gpu_state(check, 1)
        g2 = await _gpu_state(check, 2)
        assert g1.status == GpuStatus.ALLOCATED and g1.current_task_id == task.id
        assert g2.status == GpuStatus.ALLOCATED and g2.current_task_id == task.id
        # A100 未被占用
        g3 = await _gpu_state(check, 3)
        assert g3.status == GpuStatus.IDLE

        logs = (await check.execute(
            select(AllocationLog).where(AllocationLog.task_id == task.id)
        )).scalars().all()
        assert len(logs) == 2                       # 每张卡一条 ALLOCATE
        assert all(l.action == AllocationAction.ALLOCATE for l in logs)
        assert {l.gpu_id for l in logs} == {1, 2}


@pytest.mark.asyncio
async def test_multigpu_respects_model_preference(db_session_factory, db_session):
    # 偏好 A100，但 A100 只有 1 张 → 凑不齐 → 不分配、保持排队
    await _seed(db_session, [
        (1, "gpu-1", "RTX 3090"),
        (2, "gpu-2", "RTX 3090"),
        (3, "gpu-3", "A100"),
    ])
    db_session.add(Task(
        user_id=1, name="pref-a100", command="echo hi",
        status=TaskStatus.QUEUED, gpu_count=2, gpu_model_preference="A100",
    ))
    await db_session.commit()

    dispatcher = Dispatcher(db_session_factory, interval=0.1, max_passes_per_tick=5)
    allocated = await dispatcher.run_once()
    assert allocated == 0

    async with db_session_factory() as check:
        task = await _task_by_name(check, "pref-a100")
        assert task.status == TaskStatus.QUEUED
        assert task.allocated_gpu_id is None
        gpus = (await check.execute(select(GPU))).scalars().all()
        assert all(g.status == GpuStatus.IDLE for g in gpus)


@pytest.mark.asyncio
async def test_multigpu_falls_back_to_earliest_idle_model(db_session_factory, db_session):
    # 无偏好：目标型号 = 最早空闲卡型号（RTX 3090），不能混入 A100
    await _seed(db_session, [
        (1, "gpu-1", "RTX 3090"),
        (2, "gpu-2", "RTX 3090"),
        (3, "gpu-3", "A100"),
    ])
    db_session.add(Task(
        user_id=1, name="no-pref", command="echo hi",
        status=TaskStatus.QUEUED, gpu_count=2,
    ))
    await db_session.commit()

    dispatcher = Dispatcher(db_session_factory, interval=0.1, max_passes_per_tick=5)
    assert await dispatcher.run_once() == 1

    async with db_session_factory() as check:
        task = await _task_by_name(check, "no-pref")
        assert task.allocated_gpu_ids == "1,2"   # 两张 3090，不含 3 号 A100


@pytest.mark.asyncio
async def test_multigpu_insufficient_blocks_fcfs_head(db_session_factory, db_session):
    # 队首任务要 2 张卡但只有 1 张同型号空闲 → 队首阻塞，后续单卡任务也不得插队
    await _seed(db_session, [
        (1, "gpu-1", "RTX 3090"),
        (2, "gpu-2", "RTX 3090"),
    ])
    db_session.add_all([
        Task(user_id=1, name="head-2card", command="echo a",
             status=TaskStatus.QUEUED, gpu_count=2),
        Task(user_id=1, name="tail-1card", command="echo b",
             status=TaskStatus.QUEUED, gpu_count=1),
    ])
    await db_session.commit()

    # 先把 gpu-2 占走，只剩 1 张 3090
    async with db_session_factory() as occupy:
        g2 = await _gpu_state(occupy, 2)
        g2.status = GpuStatus.RUNNING
        await occupy.commit()

    dispatcher = Dispatcher(db_session_factory, interval=0.1, max_passes_per_tick=5)
    assert await dispatcher.run_once() == 0

    async with db_session_factory() as check:
        head = await _task_by_name(check, "head-2card")
        tail = await _task_by_name(check, "tail-1card")
        assert head.status == TaskStatus.QUEUED
        assert tail.status == TaskStatus.QUEUED   # FCFS：队首未解决，后面不分配
        g1 = await _gpu_state(check, 1)
        assert g1.status == GpuStatus.IDLE        # 不会把唯一空闲卡分给队尾任务


@pytest.mark.asyncio
async def test_single_gpu_task_unchanged(db_session_factory, db_session):
    # 回归：gpu_count=1 时行为与 MVP 完全一致
    await _seed(db_session, [
        (1, "gpu-1", "RTX 3090"),
        (2, "gpu-2", "RTX 3090"),
    ])
    db_session.add(Task(
        user_id=1, name="single", command="echo hi",
        status=TaskStatus.QUEUED, gpu_count=1,
    ))
    await db_session.commit()

    dispatcher = Dispatcher(db_session_factory, interval=0.1, max_passes_per_tick=5)
    assert await dispatcher.run_once() == 1

    async with db_session_factory() as check:
        task = await _task_by_name(check, "single")
        assert task.status == TaskStatus.PENDING
        assert task.allocated_gpu_id == 1
        assert task.allocated_gpu_ids == "1"


# ═══════════════════════════════════════════════════════════════
# ProcessManager：多卡任务结束批量释放（story 3-9 配套）
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_pm_multigpu_exit_releases_all_gpus(db_session_factory, db_session):
    await _seed(db_session, [
        (1, "gpu-1", "RTX 3090"),
        (2, "gpu-2", "RTX 3090"),
    ])
    db_session.add(Task(
        user_id=1, name="multi-finish", command=_python_exit(0),
        status=TaskStatus.PENDING, allocated_gpu_id=1, allocated_gpu_ids="1,2",
    ))
    await db_session.commit()

    # 模拟分配阶段：两张卡都绑定到该任务
    async with db_session_factory() as bind:
        g1 = await _gpu_state(bind, 1)
        g2 = await _gpu_state(bind, 2)
        g1.status = GpuStatus.ALLOCATED
        g2.status = GpuStatus.ALLOCATED
        g1.current_task_id = 1
        g2.current_task_id = 1
        await bind.commit()

    pm = ProcessManager(db_session_factory, interval=0.1)
    await pm._run_once()                 # 启动 → 两张卡 RUNNING
    await asyncio.sleep(0.5)
    await pm._run_once()                 # 收尾 → 全部释放

    async with db_session_factory() as check:
        task = await _task_by_name(check, "multi-finish")
        assert task.status == TaskStatus.COMPLETED
        assert task.exit_code == 0
        assert task.id not in pm._active_procs

        g1 = await _gpu_state(check, 1)
        g2 = await _gpu_state(check, 2)
        assert g1.status == GpuStatus.IDLE and g1.current_task_id is None
        assert g2.status == GpuStatus.IDLE and g2.current_task_id is None

        releases = (await check.execute(
            select(AllocationLog).where(
                AllocationLog.task_id == task.id,
                AllocationLog.action == AllocationAction.RELEASE,
            )
        )).scalars().all()
        assert len(releases) == 2
        assert {l.gpu_id for l in releases} == {1, 2}


# ═══════════════════════════════════════════════════════════════
# API：gpu_count 1-64 校验
# ═══════════════════════════════════════════════════════════════

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.api.routes.tasks import router as tasks_router
from app.infrastructure.mysql.database import get_db
from app.utils.middleware import setup_exception_handlers, setup_middleware
from fastapi import FastAPI  # noqa: E402


async def _make_task_client(db_session) -> AsyncClient:
    db_session.add_all([
        User(id=1, username="admin", role=Role.ADMIN),
        GPU(id=1, name="gpu-0", model="RTX 3090", total_memory_mb=24576, status=GpuStatus.IDLE),
    ])
    await db_session.commit()

    app = FastAPI()
    setup_middleware(app)
    setup_exception_handlers(app)
    app.include_router(tasks_router)

    async def _override_get_db():
        async with db_session as s:
            yield s

    app.dependency_overrides[get_db] = _override_get_db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def task_client(db_session) -> AsyncClient:
    return await _make_task_client(db_session)


@pytest.mark.asyncio
@pytest.mark.parametrize("gpu_count", [0, -1, 65, 100])
async def test_create_task_rejects_bad_gpu_count(task_client, gpu_count):
    resp = await task_client.post("/tasks", json={
        "name": "t", "command": "echo 1", "gpu_count": gpu_count,
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("gpu_count", [1, 2, 8, 64])
async def test_create_task_accepts_valid_gpu_count(task_client, gpu_count):
    resp = await task_client.post("/tasks", json={
        "name": f"t-{gpu_count}", "command": "echo 1", "gpu_count": gpu_count,
    })
    assert resp.status_code == 201
    assert resp.json()["gpu_count"] == gpu_count


# ═══════════════════════════════════════════════════════════════
# Model：allocated_gpu_ids 字段
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_task_allocated_gpu_ids_roundtrip(db_session):
    db_session.add(User(id=1, username="admin", role=Role.ADMIN))
    await db_session.commit()

    t = Task(
        user_id=1, name="multi", command="echo hi", status=TaskStatus.PENDING,
        allocated_gpu_id=1, allocated_gpu_ids="1,2",
    )
    db_session.add(t)
    await db_session.commit()

    result = await db_session.execute(select(Task).where(Task.name == "multi"))
    fetched = result.scalar_one()
    assert fetched.allocated_gpu_ids == "1,2"
    assert fetched.allocated_gpu_id == 1
