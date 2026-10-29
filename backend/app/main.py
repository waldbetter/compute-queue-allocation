import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.api.routes.gpus import router as gpus_router
from app.api.routes.health import router as health_router
from app.api.routes.tasks import router as tasks_router
from app.core.dispatcher import Dispatcher
from app.core.process_manager import ProcessManager
from app.infrastructure.mysql.database import async_session_factory
from app.utils.logging_setup import setup_logging
from app.utils.middleware import setup_exception_handlers, setup_middleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.log_level)
    logger = logging.getLogger("app")
    logger.info("Backend starting on %s:%s", settings.host, settings.port)

    dispatcher = Dispatcher(async_session_factory, interval=0.5)
    process_manager = ProcessManager(async_session_factory, interval=0.5)
    await dispatcher.start()
    await process_manager.start()

    app.state.dispatcher = dispatcher
    app.state.process_manager = process_manager

    try:
        yield
    finally:
        await process_manager.stop()
        await dispatcher.stop()
        logger.info("Backend shutting down")


def create_app() -> FastAPI:
    app = FastAPI(title="GPU Queue Allocation", version="0.1.0", lifespan=lifespan)
    setup_exception_handlers(app)
    setup_middleware(app)
    app.include_router(health_router)
    app.include_router(gpus_router)
    app.include_router(tasks_router)
    return app


app = create_app()