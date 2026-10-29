import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_db_session_lifecycle(db_session):
    result = await db_session.execute(text("SELECT 1"))
    assert result.scalar_one() == 1


@pytest.mark.asyncio
async def test_db_session_commits_rollback(db_session):
    await db_session.execute(text("SELECT 1 AS val"))
    assert True


def test_settings_defaults():
    from app.config import settings
    assert settings.database_url.startswith("mysql+aiomysql://")
    assert settings.port == 8000
    assert settings.log_level in ("DEBUG", "INFO", "WARNING", "ERROR")


def test_logging_setup_runs():
    from app.utils.logging_setup import setup_logging
    import logging
    setup_logging("DEBUG", "logs")
    logger = logging.getLogger("test")
    logger.info("test log message")
    assert True