"""Tests that two applications in one process keep independent database, scheduler, and app state."""

from typing import Annotated, Any

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from servicekit import Database, SqliteDatabaseBuilder
from servicekit.api.dependencies import get_session
from servicekit.api.service_builder import BaseServiceBuilder, ServiceInfo


def _build_app(*, service_id: str, database: Database, marker: str) -> FastAPI:
    """Build an app with its own database, jobs, health, and a marker-returning route."""
    router = APIRouter(prefix="/api/v1/marker")

    @router.get("")
    async def read_marker(session: Annotated[AsyncSession, Depends(get_session)]) -> dict[str, Any]:
        """Read the marker row seeded into this app's own database."""
        result = await session.execute(text("SELECT value FROM markers"))
        return {"marker": result.scalar_one()}

    async def seed_marker(app: FastAPI) -> None:
        """Create and populate the marker table in this app's database."""
        async with app.state.database.session() as session:
            await session.execute(text("CREATE TABLE markers (value TEXT)"))
            await session.execute(text("INSERT INTO markers (value) VALUES (:value)"), {"value": marker})
            await session.commit()

    return (
        BaseServiceBuilder(info=ServiceInfo(id=service_id, display_name=service_id))
        .with_database(database)
        .with_health()
        .with_jobs()
        .include_router(router)
        .on_startup(seed_marker)
        .build()
    )


async def _client(app: FastAPI) -> AsyncClient:
    """Create an HTTP client bound to the given ASGI app."""
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_two_apps_keep_independent_state() -> None:
    """Two concurrently running apps use their own database, scheduler, and job list."""
    database_a = SqliteDatabaseBuilder.in_memory().build()
    database_b = SqliteDatabaseBuilder.in_memory().build()

    app_a = _build_app(service_id="app-a", database=database_a, marker="alpha")
    app_b = _build_app(service_id="app-b", database=database_b, marker="beta")

    async def noop() -> str:
        """Trivial job payload."""
        return "done"

    async with app_a.router.lifespan_context(app_a):
        async with app_b.router.lifespan_context(app_b):
            assert app_a.state.database is database_a
            assert app_b.state.database is database_b
            assert app_a.state.scheduler is not app_b.state.scheduler

            job_a = await app_a.state.scheduler.add_job(noop)
            job_b = await app_b.state.scheduler.add_job(noop)
            await app_a.state.scheduler.wait(job_a, timeout=5.0)
            await app_b.state.scheduler.wait(job_b, timeout=5.0)

            client_a = await _client(app_a)
            client_b = await _client(app_b)

            async with client_a, client_b:
                assert (await client_a.get("/api/v1/marker")).json() == {"marker": "alpha"}
                assert (await client_b.get("/api/v1/marker")).json() == {"marker": "beta"}

                jobs_a = (await client_a.get("/api/v1/jobs")).json()
                jobs_b = (await client_b.get("/api/v1/jobs")).json()

                assert [job["id"] for job in jobs_a] == [str(job_a)]
                assert [job["id"] for job in jobs_b] == [str(job_b)]

        # App B has shut down; app A must still serve its own health and jobs.
        assert app_b.state.database is None
        assert app_a.state.database is database_a

        client_a = await _client(app_a)
        async with client_a:
            health = await client_a.get("/health")
            assert health.json()["checks"]["database"]["state"] == "healthy"

            jobs_a = (await client_a.get("/api/v1/jobs")).json()
            assert [job["id"] for job in jobs_a] == [str(job_a)]

    assert app_a.state.database is None
    await database_a.dispose()
    await database_b.dispose()


@pytest.mark.asyncio
async def test_app_manager_is_per_application() -> None:
    """Each built app carries its own AppManager on app.state."""
    app_a = BaseServiceBuilder(info=ServiceInfo(id="app-a", display_name="A")).with_system().build()
    app_b = BaseServiceBuilder(info=ServiceInfo(id="app-b", display_name="B")).with_system().build()

    assert app_a.state.app_manager is not app_b.state.app_manager


@pytest.mark.asyncio
async def test_scheduler_dependency_rejects_app_without_jobs() -> None:
    """An app without jobs has no scheduler on state, so the dependency raises."""
    app = BaseServiceBuilder(info=ServiceInfo(id="no-jobs", display_name="No Jobs")).with_health().build()

    async with app.router.lifespan_context(app):
        assert getattr(app.state, "scheduler", None) is None
