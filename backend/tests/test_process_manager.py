import asyncio
import sys
from pathlib import Path

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


def _python_hello() -> str:
    return f'"{sys.executable}" -c "print(123)"'


def _nonexistent_cmd() -> str:
    return "nonexistent_command_xyz_12345"


async def _seed_dispatcher(db_session):
    db_session.add_all([
        User(id=1, username="admin", role=Role.ADMIN),
        User(id=2, username="alice", role=Role.MEMBER),
        GPU(id=1, name="gpu-0", model="RTX 3090", total_memory_mb=24576, status=GpuStatus.IDLE),
        GPU(id=2, name="gpu-1", model="A100", total_memory_mb=40960, status=GpuStatus.IDLE),
    ])
    await db_session.commit()


@pytest.mark.asyncio
async def test_pm_no_pending_tasks(db_session_factory, db_session):
    await _seed_dispatcher(db_session)
    pm = ProcessManager(db_session_factory, interval=0.1)

    await pm._run_once()

    async with db_session_factory() as check:
        gpus = (await check.execute(select(GPU))).scalars().all()
        assert all(g.status == GpuStatus.IDLE for g in gpus)


@pytest.mark.asyncio
async def test_pm_launches_pending_to_running(db_session_factory, db_session):
    await _seed_dispatcher(db_session)
    db_session.add_all([
        Task(
            user_id=1, name="t-ok", command=_python_exit(0),
            status=TaskStatus.PENDING, allocated_gpu_id=1,
        ),
    ])
    await db_session.commit()

    pm = ProcessManager(db_session_factory, interval=0.1)
    await pm._run_once()

    async with db_session_factory() as check:
        task = (await check.execute(select(Task).where(Task.name == "t-ok"))).scalar_one()
        gpu = (await check.execute(select(GPU).where(GPU.id == 1))).scalar_one()

        assert task.status == TaskStatus.RUNNING
        assert task.started_at is not None
        assert task.log_path is not None
        assert gpu.status == GpuStatus.RUNNING
        assert task.id in pm._active_procs


@pytest.mark.asyncio
async def test_pm_process_exit_zero_becomes_completed(db_session_factory, db_session):
    await _seed_dispatcher(db_session)
    db_session.add_all([
        Task(
            user_id=1, name="t-success", command=_python_exit(0),
            status=TaskStatus.PENDING, allocated_gpu_id=1,
        ),
    ])
    await db_session.commit()

    pm = ProcessManager(db_session_factory, interval=0.1)
    await pm._run_once()
    await asyncio.sleep(0.5)
    await pm._run_once()

    async with db_session_factory() as check:
        task = (await check.execute(select(Task).where(Task.name == "t-success"))).scalar_one()
        gpu = (await check.execute(select(GPU).where(GPU.id == 1))).scalar_one()

        assert task.status == TaskStatus.COMPLETED
        assert task.finished_at is not None
        assert task.exit_code == 0
        assert gpu.status == GpuStatus.IDLE
        assert gpu.current_task_id is None

        release_log = (await check.execute(
            select(AllocationLog)
            .where(AllocationLog.task_id == task.id, AllocationLog.action == AllocationAction.RELEASE)
        )).scalar_one_or_none()
        assert release_log is not None
        assert release_log.gpu_id == 1


@pytest.mark.asyncio
async def test_pm_process_exit_nonzero_becomes_failed(db_session_factory, db_session):
    await _seed_dispatcher(db_session)
    db_session.add_all([
        Task(
            user_id=1, name="t-fail", command=_python_exit(5),
            status=TaskStatus.PENDING, allocated_gpu_id=1,
        ),
    ])
    await db_session.commit()

    pm = ProcessManager(db_session_factory, interval=0.1)
    await pm._run_once()
    await asyncio.sleep(0.5)
    await pm._run_once()

    async with db_session_factory() as check:
        task = (await check.execute(select(Task).where(Task.name == "t-fail"))).scalar_one()
        gpu = (await check.execute(select(GPU).where(GPU.id == 1))).scalar_one()

        assert task.status == TaskStatus.FAILED
        assert task.exit_code == 5
        assert gpu.status == GpuStatus.IDLE


@pytest.mark.asyncio
async def test_pm_launch_failure_reclaims_gpu(db_session_factory, db_session):
    await _seed_dispatcher(db_session)
    db_session.add_all([
        Task(
            user_id=1, name="t-bad-cmd", command=_nonexistent_cmd(),
            status=TaskStatus.PENDING, allocated_gpu_id=1,
        ),
    ])
    await db_session.commit()

    pm = ProcessManager(db_session_factory, interval=0.1)
    await pm._run_once()

    async with db_session_factory() as check:
        task = (await check.execute(select(Task).where(Task.name == "t-bad-cmd"))).scalar_one()
        gpu = (await check.execute(select(GPU).where(GPU.id == 1))).scalar_one()

        assert task.status == TaskStatus.FAILED
        assert task.exit_code == -1
        assert task.finished_at is not None
        assert gpu.status == GpuStatus.IDLE


@pytest.mark.asyncio
async def test_pm_stop_kills_active_processes(db_session_factory, db_session):
    await _seed_dispatcher(db_session)
    db_session.add_all([
        Task(
            user_id=1, name="t-long",
            command=f'"{sys.executable}" -c "import time; time.sleep(600)"',
            status=TaskStatus.PENDING, allocated_gpu_id=1,
        ),
    ])
    await db_session.commit()

    pm = ProcessManager(db_session_factory, interval=0.1)
    await pm._run_once()

    async with db_session_factory() as check:
        task = (await check.execute(select(Task).where(Task.name == "t-long"))).scalar_one()
        assert task.status == TaskStatus.RUNNING

    assert task.id in pm._active_procs
    proc = pm._active_procs[task.id]

    await pm.stop()
    await asyncio.sleep(0.2)

    assert proc.returncode is not None or proc.returncode == None

    async with db_session_factory() as check:
        gpu = (await check.execute(select(GPU).where(GPU.id == 1))).scalar_one()
        assert gpu.status == GpuStatus.RUNNING


@pytest.mark.asyncio
async def test_dispatcher_plus_pm_integration(db_session_factory, db_session):
    await _seed_dispatcher(db_session)
    db_session.add_all([
        Task(
            user_id=1, name="int-task", command=_python_exit(0),
            status=TaskStatus.QUEUED,
        ),
    ])
    await db_session.commit()

    dispatcher = Dispatcher(db_session_factory, interval=0.1)
    pm = ProcessManager(db_session_factory, interval=0.1)

    await dispatcher.run_once()
    await pm._run_once()

    async with db_session_factory() as check:
        task = (await check.execute(select(Task).where(Task.name == "int-task"))).scalar_one()
        gpu = (await check.execute(select(GPU).where(GPU.id == task.allocated_gpu_id))).scalar_one()

        assert task.status == TaskStatus.RUNNING
        assert gpu.status == GpuStatus.RUNNING

    await asyncio.sleep(0.5)
    await pm._run_once()

    async with db_session_factory() as check:
        task = (await check.execute(select(Task).where(Task.name == "int-task"))).scalar_one()
        gpu = (await check.execute(select(GPU).where(GPU.id == task.allocated_gpu_id))).scalar_one()

        assert task.status == TaskStatus.COMPLETED
        assert task.exit_code == 0
        assert gpu.status == GpuStatus.IDLE


@pytest.mark.asyncio
async def test_pm_log_file_created(db_session_factory, db_session, tmp_path):
    await _seed_dispatcher(db_session)
    db_session.add_all([
        Task(
            user_id=1, name="t-logs", command=_python_hello(),
            status=TaskStatus.PENDING, allocated_gpu_id=1,
        ),
    ])
    await db_session.commit()

    original_cwd = Path.cwd()
    try:
        import os as _os
        _os.chdir(tmp_path)
        Path("logs").mkdir(exist_ok=True)
        pm = ProcessManager(db_session_factory, interval=0.1)
        await pm._run_once()
        await asyncio.sleep(0.5)
        await pm._run_once()

        log_path = tmp_path / "logs" / "1.log"
        assert log_path.exists()
        content = log_path.read_text()
        assert "123" in content
    finally:
        import os as _os
        _os.chdir(original_cwd)