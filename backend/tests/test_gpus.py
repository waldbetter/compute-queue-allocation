import pytest
from httpx import ASGITransport, AsyncClient

from app.api.routes.gpus import router as gpus_router
from app.infrastructure.mysql.database import get_db
from app.models.gpu import GPU, GpuStatus
from app.utils.middleware import setup_exception_handlers, setup_middleware
from fastapi import FastAPI


@pytest.fixture
async def gpu_client(db_session) -> AsyncClient:
    app = FastAPI()
    setup_middleware(app)
    setup_exception_handlers(app)
    app.include_router(gpus_router)

    async def _override_get_db():
        async with db_session as s:
            yield s

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _seed_gpus(db_session):
    for name, model, status in [
        ("gpu-0", "RTX 3090", GpuStatus.IDLE),
        ("gpu-1", "RTX 3090", GpuStatus.RUNNING),
        ("gpu-2", "A100", GpuStatus.IDLE),
        ("gpu-3", "RTX 4090", GpuStatus.MAINTENANCE),
        ("gpu-4", "A100", GpuStatus.IDLE),
        ("gpu-5", "RTX 3080", GpuStatus.FAULTY),
        ("gpu-6", "RTX 3090", GpuStatus.RUNNING),
    ]:
        db_session.add(GPU(name=name, model=model, total_memory_mb=24576, status=status))
    await db_session.commit()


# ── POST /gpus 新增 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_gpu_success(gpu_client, db_session):
    payload = {"name": "new-gpu-0", "model": "RTX 4090", "total_memory_mb": 32768}
    resp = await gpu_client.post("/gpus", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "new-gpu-0"
    assert data["status"] == "IDLE"
    assert data["notes"] is None


@pytest.mark.asyncio
async def test_create_gpu_name_conflict(gpu_client, db_session):
    db_session.add(GPU(name="gpu-0", model="RTX 3090", total_memory_mb=24576))
    await db_session.commit()

    resp = await gpu_client.post("/gpus", json={
        "name": "gpu-0", "model": "A100", "total_memory_mb": 40960,
    })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_gpu_validation(gpu_client):
    assert (await gpu_client.post("/gpus", json={"name": "x", "model": "y", "total_memory_mb": 0})).status_code == 422
    assert (await gpu_client.post("/gpus", json={"name": "", "model": "y", "total_memory_mb": 1024})).status_code == 422
    assert (await gpu_client.post("/gpus", json={"name": "x"})).status_code == 422


# ── PATCH /gpus/{id} 更新 ────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_gpu_status_only(gpu_client, db_session):
    await _seed_gpus(db_session)
    resp = await gpu_client.patch("/gpus/1", json={"status": "MAINTENANCE"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "MAINTENANCE"


@pytest.mark.asyncio
async def test_update_gpu_notes_only(gpu_client, db_session):
    await _seed_gpus(db_session)
    resp = await gpu_client.patch("/gpus/1", json={"notes": "driver update pending"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["notes"] == "driver update pending"
    assert data["status"] == "IDLE"


@pytest.mark.asyncio
async def test_update_gpu_both_fields(gpu_client, db_session):
    await _seed_gpus(db_session)
    resp = await gpu_client.patch("/gpus/1", json={
        "status": "ALLOCATED", "notes": "assigned to task 42",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ALLOCATED"
    assert data["notes"] == "assigned to task 42"


@pytest.mark.asyncio
async def test_update_gpu_clear_notes_with_null(gpu_client, db_session):
    g = GPU(name="gpu-7", model="3090", total_memory_mb=24576, notes="temporary")
    db_session.add(g)
    await db_session.commit()
    await db_session.refresh(g)

    resp = await gpu_client.patch(f"/gpus/{g.id}", json={"notes": None})
    assert resp.status_code == 200
    assert resp.json()["notes"] is None


@pytest.mark.asyncio
async def test_update_gpu_not_found(gpu_client, db_session):
    resp = await gpu_client.patch("/gpus/999", json={"status": "IDLE"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_gpu_running_to_maintenance_rejected(gpu_client, db_session):
    await _seed_gpus(db_session)
    resp = await gpu_client.patch("/gpus/2", json={"status": "MAINTENANCE"})
    assert resp.status_code == 400
    assert "running" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_gpu_running_to_faulty_rejected(gpu_client, db_session):
    await _seed_gpus(db_session)
    resp = await gpu_client.patch("/gpus/2", json={"status": "FAULTY"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_update_gpu_idle_to_maintenance_allowed(gpu_client, db_session):
    await _seed_gpus(db_session)
    resp = await gpu_client.patch("/gpus/1", json={"status": "MAINTENANCE"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "MAINTENANCE"


@pytest.mark.asyncio
async def test_update_gpu_running_to_allocated_allowed(gpu_client, db_session):
    await _seed_gpus(db_session)
    resp = await gpu_client.patch("/gpus/2", json={"status": "ALLOCATED"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ALLOCATED"


@pytest.mark.asyncio
async def test_update_gpu_invalid_status(gpu_client, db_session):
    await _seed_gpus(db_session)
    resp = await gpu_client.patch("/gpus/1", json={"status": "DEAD"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_gpu_empty_body_noop(gpu_client, db_session):
    await _seed_gpus(db_session)
    resp = await gpu_client.patch("/gpus/1", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "IDLE"
    assert data["notes"] is None


# ── GET /gpus 列表（回归）─────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_gpus_default_page(gpu_client, db_session):
    await _seed_gpus(db_session)
    resp = await gpu_client.get("/gpus")
    assert resp.status_code == 200
    assert resp.json()["total"] == 7


@pytest.mark.asyncio
async def test_list_gpus_status_filter(gpu_client, db_session):
    await _seed_gpus(db_session)
    resp = await gpu_client.get("/gpus?status=RUNNING")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2