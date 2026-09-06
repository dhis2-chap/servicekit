"""Tests for lifespan cleanup ordering, hook isolation, and fatal registration handling."""

import asyncio
import signal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from servicekit import SqliteDatabaseBuilder
from servicekit.api.service_builder import BaseServiceBuilder, ServiceInfo


def _builder(service_id: str = "test-svc") -> BaseServiceBuilder:
    """Create a minimal builder for lifespan tests."""
    return BaseServiceBuilder(info=ServiceInfo(id=service_id, display_name="Test"))


# ---------------------------------------------------------------------------
# Finding 8: shutdown drains jobs and isolates hook failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shutdown_cancels_running_jobs_before_disposing_database() -> None:
    """A job blocked at shutdown is canceled and terminal before the database is disposed."""
    blocker = asyncio.Event()
    database = SqliteDatabaseBuilder.in_memory().build()
    app = _builder().with_database(database).with_jobs(shutdown_timeout=0.05).build()

    async def blocked_job() -> None:
        """Job that never finishes on its own."""
        await blocker.wait()

    async with app.router.lifespan_context(app):
        scheduler = app.state.scheduler
        job_id = await scheduler.add_job(blocked_job)
        await asyncio.sleep(0.01)
        assert (await scheduler.get_record(job_id)).status == "running"

    # An injected database is not owned by the app, so it is never disposed for us.
    assert (await scheduler.get_record(job_id)).status == "canceled"
    with pytest.raises(RuntimeError, match="Scheduler is shut down"):
        await scheduler.add_job(blocked_job)
    await database.dispose()


@pytest.mark.asyncio
async def test_owned_database_disposed_after_scheduler_drain() -> None:
    """Scheduler drain happens before dispose for a database the app created."""
    events: list[str] = []
    blocker = asyncio.Event()

    async def blocked_job() -> None:
        """Job that never finishes on its own."""
        try:
            await blocker.wait()
        except asyncio.CancelledError:
            events.append("job_canceled")
            raise

    async def record_dispose(app: FastAPI) -> None:
        """Wrap the created database's dispose to record ordering."""
        database = app.state.database
        original_dispose = database.dispose

        async def spy_dispose() -> None:
            events.append("dispose")
            await original_dispose()

        database.dispose = spy_dispose

    app = _builder().with_jobs(shutdown_timeout=0.05).on_startup(record_dispose).build()

    async with app.router.lifespan_context(app):
        scheduler = app.state.scheduler
        await scheduler.add_job(blocked_job)
        await asyncio.sleep(0.01)

    assert events == ["job_canceled", "dispose"]


@pytest.mark.asyncio
async def test_failing_startup_hook_still_disposes_database() -> None:
    """A raising startup hook propagates but cleanup still disposes the database."""
    disposed: list[str] = []

    async def spy_hook(app: FastAPI) -> None:
        """Wrap dispose so cleanup can be observed."""
        database = app.state.database
        original_dispose = database.dispose

        async def spy_dispose() -> None:
            disposed.append("dispose")
            await original_dispose()

        database.dispose = spy_dispose

    async def failing_hook(app: FastAPI) -> None:
        """Startup hook that fails."""
        raise ValueError("startup boom")

    app = _builder().on_startup(spy_hook).on_startup(failing_hook).build()

    with pytest.raises(ValueError, match="startup boom"):
        async with app.router.lifespan_context(app):
            pass

    assert disposed == ["dispose"]


@pytest.mark.asyncio
async def test_failing_shutdown_hook_runs_remaining_cleanup() -> None:
    """A raising shutdown hook still lets the next hook and dispose run, then propagates."""
    events: list[str] = []

    async def spy_hook(app: FastAPI) -> None:
        """Wrap dispose so cleanup can be observed."""
        database = app.state.database
        original_dispose = database.dispose

        async def spy_dispose() -> None:
            events.append("dispose")
            await original_dispose()

        database.dispose = spy_dispose

    async def failing_hook(app: FastAPI) -> None:
        """First shutdown hook, fails."""
        events.append("first")
        raise ValueError("shutdown boom")

    async def second_hook(app: FastAPI) -> None:
        """Second shutdown hook, must still run."""
        events.append("second")

    app = _builder().on_startup(spy_hook).on_shutdown(failing_hook).on_shutdown(second_hook).build()

    with pytest.raises(ValueError, match="shutdown boom"):
        async with app.router.lifespan_context(app):
            pass

    assert events == ["first", "second", "dispose"]


@pytest.mark.asyncio
async def test_normal_shutdown_clears_app_state() -> None:
    """After a clean shutdown, per-app state is cleared."""
    app = _builder().with_jobs().build()

    async with app.router.lifespan_context(app):
        assert app.state.database is not None
        assert app.state.scheduler is not None

    assert app.state.database is None
    assert app.state.scheduler is None
    assert app.state.keepalive is None


# ---------------------------------------------------------------------------
# Finding 7: fail_on_error shuts the process down gracefully
# ---------------------------------------------------------------------------


def _registration_builder(*, fail_on_error: bool) -> BaseServiceBuilder:
    """Create a builder with registration configured."""
    return (
        _builder()
        .with_health()
        .with_registration(
            orchestrator_url="http://orchestrator:9000/services/$register",
            host="test-host",
            port=9999,
            enable_keepalive=False,
            fail_on_error=fail_on_error,
        )
    )


@pytest.mark.asyncio
async def test_registration_failure_raises_sigterm_and_still_cleans_up() -> None:
    """A raising registration task with fail_on_error signals SIGTERM without skipping cleanup."""
    events: list[str] = []

    async def spy_hook(app: FastAPI) -> None:
        """Wrap dispose so cleanup can be observed."""
        database = app.state.database
        original_dispose = database.dispose

        async def spy_dispose() -> None:
            events.append("dispose")
            await original_dispose()

        database.dispose = spy_dispose

    async def shutdown_hook(app: FastAPI) -> None:
        """Shutdown hook that must run despite the registration failure."""
        events.append("shutdown_hook")

    app = _registration_builder(fail_on_error=True).on_startup(spy_hook).on_shutdown(shutdown_hook).build()

    with (
        patch("servicekit.api.service_builder._wait_until_ready", new_callable=AsyncMock, return_value=True),
        patch(
            "servicekit.api.service_builder._register_and_start_keepalive",
            new_callable=AsyncMock,
            side_effect=RuntimeError("registration exploded"),
        ),
        patch("signal.raise_signal") as mock_signal,
    ):
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0.05)
            assert app.state.registration_failed is True

    mock_signal.assert_called_once_with(signal.SIGTERM)
    assert events == ["shutdown_hook", "dispose"]


@pytest.mark.asyncio
async def test_readiness_timeout_raises_sigterm_when_fail_on_error() -> None:
    """A readiness timeout with fail_on_error signals SIGTERM."""
    app = _registration_builder(fail_on_error=True).build()

    with (
        patch("servicekit.api.service_builder._wait_until_ready", new_callable=AsyncMock, return_value=False),
        patch("signal.raise_signal") as mock_signal,
    ):
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0.05)

    mock_signal.assert_called_once_with(signal.SIGTERM)


@pytest.mark.asyncio
async def test_readiness_timeout_is_tolerated_when_not_fail_on_error() -> None:
    """A readiness timeout without fail_on_error neither signals nor marks failure."""
    app = _registration_builder(fail_on_error=False).build()

    with (
        patch("servicekit.api.service_builder._wait_until_ready", new_callable=AsyncMock, return_value=False),
        patch("signal.raise_signal") as mock_signal,
    ):
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0.05)
            assert getattr(app.state, "registration_failed", False) is False

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                checks = (await client.get("/health")).json()["checks"]
                assert checks["registration"]["state"] == "healthy"

    mock_signal.assert_not_called()


@pytest.mark.asyncio
async def test_registration_failure_without_fail_on_error_does_not_signal() -> None:
    """A raising registration task without fail_on_error neither signals nor marks failure."""
    app = _registration_builder(fail_on_error=False).build()

    with (
        patch("servicekit.api.service_builder._wait_until_ready", new_callable=AsyncMock, return_value=True),
        patch(
            "servicekit.api.service_builder._register_and_start_keepalive",
            new_callable=AsyncMock,
            side_effect=RuntimeError("registration exploded"),
        ),
        patch("signal.raise_signal") as mock_signal,
    ):
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0.05)

    mock_signal.assert_not_called()
    assert getattr(app.state, "registration_failed", False) is False


@pytest.mark.asyncio
async def test_registration_health_check_reports_unhealthy_after_failure() -> None:
    """The built-in registration health check turns unhealthy once registration fails fatally."""
    app = _registration_builder(fail_on_error=True).build()

    with (
        patch("servicekit.api.service_builder._wait_until_ready", new_callable=AsyncMock, return_value=True),
        patch(
            "servicekit.api.service_builder._register_and_start_keepalive",
            new_callable=AsyncMock,
            side_effect=RuntimeError("registration exploded"),
        ),
        patch("signal.raise_signal"),
    ):
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0.05)

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                payload: dict[str, Any] = (await client.get("/health")).json()

    assert payload["checks"]["registration"]["state"] == "unhealthy"
    assert payload["status"] == "unhealthy"


@pytest.mark.asyncio
async def test_no_registration_health_check_without_registration() -> None:
    """The registration health check is absent when registration is not configured."""
    app = _builder().with_health().build()

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            checks = (await client.get("/health")).json()["checks"]

    assert "registration" not in checks
