"""Request-scoped FastAPI dependencies resolved from ``request.app.state``.

Every dependency here is per application: two apps running in the same process each
resolve their own database, scheduler, and app manager. Library code that runs outside
a request (for example inside a lifespan) should capture the objects it needs directly
instead of calling these getters.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from servicekit import Database
from servicekit.scheduler import Scheduler

from .app import AppManager


def get_database(request: Request) -> Database:
    """Get the database bound to the current application."""
    database: Database | None = getattr(request.app.state, "database", None)
    if database is None:
        raise RuntimeError(
            "Database not available on app.state.database. "
            "The application lifespan must run before requests are served."
        )
    return database


async def get_session(database: Annotated[Database, Depends(get_database)]) -> AsyncIterator[AsyncSession]:
    """Get a database session for dependency injection."""
    async with database.session() as session:
        yield session


def get_scheduler(request: Request) -> Scheduler:
    """Get the scheduler bound to the current application."""
    scheduler: Scheduler | None = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise RuntimeError(
            "Scheduler not available on app.state.scheduler. Enable jobs with .with_jobs() and run the lifespan."
        )
    return scheduler


def get_app_manager(request: Request) -> AppManager:
    """Get the app manager bound to the current application."""
    app_manager: AppManager | None = getattr(request.app.state, "app_manager", None)
    if app_manager is None:
        raise RuntimeError("AppManager not available on app.state.app_manager. Build the app with a ServiceBuilder.")
    return app_manager
