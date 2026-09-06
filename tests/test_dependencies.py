"""Tests for request-scoped API dependency injection."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Request

from servicekit import Database
from servicekit.api.app import AppManager
from servicekit.api.dependencies import get_app_manager, get_database, get_scheduler, get_session
from servicekit.scheduler import Scheduler


def _make_request(**state: object) -> Request:
    """Build a fake request whose app carries the given state attributes."""
    return cast(Request, SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(**state))))


def test_get_database_raises_when_state_missing():
    """Test that get_database raises RuntimeError when app.state has no database."""
    with pytest.raises(RuntimeError, match="app.state.database"):
        get_database(_make_request())


def test_get_database_raises_when_state_none():
    """Test that get_database raises RuntimeError when app.state.database is None."""
    with pytest.raises(RuntimeError, match="app.state.database"):
        get_database(_make_request(database=None))


def test_get_database_returns_app_state_database():
    """Test that get_database returns the database stored on app.state."""
    mock_database = MagicMock(spec=Database)
    assert get_database(_make_request(database=mock_database)) is mock_database


def test_get_scheduler_raises_when_state_missing():
    """Test that get_scheduler raises RuntimeError when app.state has no scheduler."""
    with pytest.raises(RuntimeError, match="app.state.scheduler"):
        get_scheduler(_make_request())


def test_get_scheduler_returns_app_state_scheduler():
    """Test that get_scheduler returns the scheduler stored on app.state."""
    mock_scheduler = MagicMock(spec=Scheduler)
    assert get_scheduler(_make_request(scheduler=mock_scheduler)) is mock_scheduler


def test_get_app_manager_raises_when_state_missing():
    """Test that get_app_manager raises RuntimeError when app.state has no app manager."""
    with pytest.raises(RuntimeError, match="app.state.app_manager"):
        get_app_manager(_make_request())


def test_get_app_manager_returns_app_state_app_manager():
    """Test that get_app_manager returns the app manager stored on app.state."""
    mock_app_manager = MagicMock(spec=AppManager)
    assert get_app_manager(_make_request(app_manager=mock_app_manager)) is mock_app_manager


def test_dependencies_are_isolated_per_app():
    """Test that two applications resolve their own database instances."""
    first_database = MagicMock(spec=Database)
    second_database = MagicMock(spec=Database)

    assert get_database(_make_request(database=first_database)) is first_database
    assert get_database(_make_request(database=second_database)) is second_database


async def test_get_session_yields_session():
    """Test that get_session yields a session from the database."""
    mock_database = MagicMock(spec=Database)

    mock_session = MagicMock()
    mock_context_manager = AsyncMock()
    mock_context_manager.__aenter__.return_value = mock_session
    mock_context_manager.__aexit__.return_value = None
    mock_database.session.return_value = mock_context_manager

    async for session in get_session(mock_database):
        assert session is mock_session
        break

    mock_database.session.assert_called_once()
