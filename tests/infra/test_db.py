from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import src.infra.db as db_module
from src.infra.db import dispose_db, get_session, init_db


@pytest.mark.asyncio
async def test_init_and_dispose_db():
    # Mock create_async_engine to avoid real DB connection
    with patch("src.infra.db.create_async_engine") as mock_create_engine:
        mock_engine = AsyncMock(spec=AsyncEngine)
        mock_create_engine.return_value = mock_engine

        # Test init_db
        await init_db()
        assert db_module._engine is not None
        assert db_module._sessionmaker is not None

        # Test dispose_db
        await dispose_db()
        assert db_module._engine is None
        assert db_module._sessionmaker is None
        mock_engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_session_success():
    # Setup mock sessionmaker
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session_maker = MagicMock(return_value=mock_session)

    # Needs to match the context manager behavior of the session
    # async with _sessionmaker() as session:
    # _sessionmaker() returns the session instance which is ALSO an async context manager in SQLAlchemy thinking,
    # OR the sessionmaker itself returns an object that has __aenter__.
    # Actually async_sessionmaker returns a session. AsyncSession is an async context manager.

    # We need to mock the context manager behavior of the session object
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None

    with patch("src.infra.db._sessionmaker", mock_session_maker):
        async with get_session() as session:
            assert session is mock_session

    mock_session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_session_error():
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None

    mock_session_maker = MagicMock(return_value=mock_session)

    with patch("src.infra.db._sessionmaker", mock_session_maker):
        with pytest.raises(ValueError, match="Test error"):
            async with get_session() as _session:
                raise ValueError("Test error")

    mock_session.rollback.assert_awaited_once()
    mock_session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_session_uninitialized():
    # Ensure _sessionmaker is None
    with patch("src.infra.db._sessionmaker", None):
        with pytest.raises(RuntimeError, match="Database is not initialized"):
            async with get_session():
                pass
