import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from app.main import create_app
from app.utils.errors import AppError, NotFoundError, ValidationError
from app.utils.middleware import setup_exception_handlers, setup_middleware


@pytest.fixture
async def client() -> AsyncClient:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def err_client() -> AsyncClient:
    app = FastAPI()
    setup_middleware(app)
    setup_exception_handlers(app)

    @app.get("/boom")
    async def boom():
        raise AppError("something went wrong", http_status=400)

    @app.get("/notfound")
    async def notfound():
        raise NotFoundError("task 42 not found")

    @app.get("/validate")
    async def validate():
        raise ValidationError("gpu count must be >= 1")

    @app.get("/oops")
    async def oops():
        raise RuntimeError("unexpected")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health_check_returns_ok(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_check_method_not_allowed(client: AsyncClient):
    resp = await client.post("/health")
    assert resp.status_code == 405


@pytest.mark.asyncio
async def test_cors_headers_present(client: AsyncClient):
    resp = await client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") in (
        "http://localhost:5173",
        "*",
    )


@pytest.mark.asyncio
async def test_app_error_400(err_client: AsyncClient):
    resp = await err_client.get("/boom")
    assert resp.status_code == 400
    assert resp.json() == {"detail": "something went wrong"}


@pytest.mark.asyncio
async def test_not_found_404(err_client: AsyncClient):
    resp = await err_client.get("/notfound")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "task 42 not found"}


@pytest.mark.asyncio
async def test_validation_400(err_client: AsyncClient):
    resp = await err_client.get("/validate")
    assert resp.status_code == 400
    assert resp.json() == {"detail": "gpu count must be >= 1"}


@pytest.mark.asyncio
async def test_unknown_exception_500(err_client: AsyncClient):
    resp = await err_client.get("/oops")
    assert resp.status_code == 500
    assert resp.json() == {"detail": "Internal server error"}