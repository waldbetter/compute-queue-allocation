import pytest
from httpx import ASGITransport, AsyncClient

from app.api.routes.tasks import router as tasks_router
from app.infrastructure.mysql.database import get_db
from app.models.gpu import GPU, GpuStatus
from app.models.task import Task, TaskStatus
from app.models.user import Role, User
from app.utils.middleware import setup_exception_handlers, setup_middleware
from fastapi import FastAPI


async def _make_task_client(db_session) -> AsyncClient:
    db_session.add_all([
        User(id=1, username="admin", role=Role.ADMIN),
        User(id=2, username="alice", role=Role.MEMBER),
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

    transport = ASGITransport(app=app)
    c = AsyncClient(transport=transport, base_url="http://test")
    return c


@pytest.fixture
async def task_client(db_session) -> AsyncClient:
    return await _make_task_client(db_session)


# ── Seed helper ─────────────────────────────────────────────────

async def _seed_tasks(db_session):
    samples = [
        (1, "admin-task-1", "echo 1", TaskStatus.COMPLETED),
        (1, "admin-task-2", "echo 2", TaskStatus.RUNNING),
        (1, "admin-task-3", "echo 3", TaskStatus.QUEUED),
        (1, "admin-task-4", "echo 4", TaskStatus.QUEUED),
        (2, "alice-task-1", "echo a", TaskStatus.QUEUED),
        (2, "alice-task-2", "echo b", TaskStatus.FAILED),
    ]
    for uid, name, cmd, status in samples:
        db_session.add(Task(user_id=uid, name=name, command=cmd, status=status))
    await db_session.commit()


# ═══════════════════════════════════════════════════════════════
# POST /tasks — 回归原有 Story 3-1 测试
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_task_default_user(task_client):
    resp = await task_client.post("/tasks", json={"name": "t1", "command": "echo 1"})
    assert resp.status_code == 201
    d = resp.json()
    assert d["user_id"] == 1
    assert d["status"] == "QUEUED"
    assert d["queue_position"] == 1


@pytest.mark.asyncio
async def test_create_task_queue_positions(task_client):
    for i in range(3):
        r = await task_client.post("/tasks", json={"name": f"t{i}", "command": f"echo {i}"})
        assert r.json()["queue_position"] == i + 1


@pytest.mark.asyncio
async def test_create_task_user_dne_409(task_client):
    r = await task_client.post("/tasks?user_id=999", json={"name": "t", "command": "echo"})
    assert r.status_code == 409


# ═══════════════════════════════════════════════════════════════
# GET /tasks — 当前用户列表
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_list_my_tasks_empty(task_client):
    resp = await task_client.get("/tasks")
    assert resp.status_code == 200
    d = resp.json()
    assert d["items"] == []
    assert d["total"] == 0


@pytest.mark.asyncio
async def test_list_my_tasks_default_user(task_client, db_session):
    await _seed_tasks(db_session)
    resp = await task_client.get("/tasks")
    assert resp.status_code == 200
    d = resp.json()
    assert d["total"] == 4
    names = [t["name"] for t in d["items"]]
    assert "admin-task-1" in names
    assert "alice-task-1" not in names


@pytest.mark.asyncio
async def test_list_my_tasks_explicit_user_id(task_client, db_session):
    await _seed_tasks(db_session)
    resp = await task_client.get("/tasks?user_id=2")
    assert resp.status_code == 200
    d = resp.json()
    assert d["total"] == 2
    names = [t["name"] for t in d["items"]]
    assert all("alice" in n for n in names)


@pytest.mark.asyncio
async def test_list_my_tasks_pagination(task_client, db_session):
    for i in range(25):
        db_session.add(Task(user_id=1, name=f"batch-{i}", command="echo", status=TaskStatus.QUEUED))
    await db_session.commit()

    r1 = await task_client.get("/tasks?page=1&page_size=10")
    assert r1.json()["total"] == 25
    assert len(r1.json()["items"]) == 10

    r2 = await task_client.get("/tasks?page=3&page_size=10")
    assert len(r2.json()["items"]) == 5


@pytest.mark.asyncio
async def test_list_my_tasks_page_zero_422(task_client, db_session):
    await _seed_tasks(db_session)
    r = await task_client.get("/tasks?page=0")
    assert r.status_code == 422


# ═══════════════════════════════════════════════════════════════
# GET /tasks/admin — 全部任务
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_admin_list_all(task_client, db_session):
    await _seed_tasks(db_session)
    resp = await task_client.get("/tasks/admin")
    assert resp.status_code == 200
    assert resp.json()["total"] == 6


@pytest.mark.asyncio
async def test_admin_list_pagination(task_client, db_session):
    await _seed_tasks(db_session)
    r = await task_client.get("/tasks/admin?page=2&page_size=3")
    d = r.json()
    assert d["total"] == 6
    assert len(d["items"]) == 3


# ═══════════════════════════════════════════════════════════════
# GET /tasks/{id} — 详情
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_task_detail(task_client, db_session):
    await _seed_tasks(db_session)
    resp = await task_client.get("/tasks/1")
    assert resp.status_code == 200
    d = resp.json()
    assert d["id"] == 1
    assert d["name"] == "admin-task-1"


@pytest.mark.asyncio
async def test_get_task_not_found(task_client):
    resp = await task_client.get("/tasks/999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_admin_does_not_match_task_id(task_client):
    resp = await task_client.get("/tasks/admin")
    assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════
# queue_position: active vs terminal
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_queue_position_active_vs_terminal(task_client, db_session):
    await _seed_tasks(db_session)

    r_running = await task_client.get("/tasks/2")
    assert r_running.json()["status"] == "RUNNING"
    assert r_running.json()["queue_position"] >= 1

    r_completed = await task_client.get("/tasks/1")
    assert r_completed.json()["status"] == "COMPLETED"
    assert r_completed.json()["queue_position"] is None

    r_failed = await task_client.get("/tasks/6")
    assert r_failed.json()["status"] == "FAILED"
    assert r_failed.json()["queue_position"] is None


@pytest.mark.asyncio
async def test_queue_position_in_list(task_client, db_session):
    await _seed_tasks(db_session)
    resp = await task_client.get("/tasks/admin")
    d = resp.json()
    items_by_id = {t["id"]: t for t in d["items"]}

    assert items_by_id[2]["status"] == "RUNNING"
    assert items_by_id[2]["queue_position"] >= 1

    assert items_by_id[3]["status"] == "QUEUED"
    assert items_by_id[3]["queue_position"] >= 1

    assert items_by_id[1]["status"] == "COMPLETED"
    assert items_by_id[1]["queue_position"] is None

    assert items_by_id[6]["status"] == "FAILED"
    assert items_by_id[6]["queue_position"] is None


@pytest.mark.asyncio
async def test_cancel_queued_task_success(task_client, db_session):
    resp = await task_client.post("/tasks", json={
        "name": "to-be-cancelled", "command": "echo bye", "gpu_count": 1,
    })
    assert resp.status_code == 201
    task_id = resp.json()["id"]

    cancel = await task_client.post(f"/tasks/{task_id}/cancel")
    assert cancel.status_code == 200
    body = cancel.json()
    assert body["status"] == "CANCELLED"
    assert body["finished_at"] is not None
    assert body["queue_position"] is None

    get_back = await task_client.get(f"/tasks/{task_id}")
    assert get_back.json()["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_cancel_nonexistent_task(task_client):
    resp = await task_client.post("/tasks/999999/cancel")
    assert resp.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected_msg", [
    (TaskStatus.RUNNING, "RUNNING"),
    (TaskStatus.COMPLETED, "COMPLETED"),
    (TaskStatus.FAILED, "FAILED"),
    (TaskStatus.PENDING, "PENDING"),
    (TaskStatus.CANCELLED, "CANCELLED"),
])
async def test_cancel_rejects_non_queued(task_client, db_session, status, expected_msg):
    from app.models.user import Role, User

    u = User(id=99, username=f"u-{status.value}", role=Role.MEMBER)
    db_session.add(u)
    await db_session.flush()

    t = Task(user_id=u.id, name=f"t-{status.value}", command="echo", status=status)
    db_session.add(t)
    await db_session.commit()

    resp = await task_client.post(f"/tasks/{t.id}/cancel")
    assert resp.status_code == 400
    assert expected_msg in resp.json()["detail"]


@pytest.mark.asyncio
async def test_cancelled_task_not_dispatched(db_session_factory, db_session):
    from sqlalchemy import select as sa_select
    from app.core.dispatcher import Dispatcher
    from app.models.user import Role, User

    u = User(id=1, username="admin", role=Role.ADMIN)
    g = GPU(id=1, name="gpu-0", model="RTX 3090", total_memory_mb=24576, status=GpuStatus.IDLE)
    db_session.add_all([u, g])
    await db_session.flush()

    db_session.add_all([
        Task(user_id=1, name="cancelled-one", command="echo n", status=TaskStatus.CANCELLED),
        Task(user_id=1, name="legit-one", command="echo y", status=TaskStatus.QUEUED),
    ])
    await db_session.commit()

    dispatcher = Dispatcher(db_session_factory, interval=0.1, max_passes_per_tick=3)
    async with db_session_factory() as s:
        ok = await dispatcher.try_allocate_gpu(s)
    assert ok is True, "Should allocate the LEGIT QUEUED task, skip CANCELLED"

    async with db_session_factory() as check:
        rows = (await check.execute(sa_select(Task).order_by(Task.id))).scalars().all()
        assert rows[0].status == TaskStatus.CANCELLED
        assert rows[1].status == TaskStatus.PENDING