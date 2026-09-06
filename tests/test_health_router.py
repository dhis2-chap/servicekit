"""Tests for health check router."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from servicekit.api.routers.health import CheckResult, HealthRouter, HealthState, HealthStatus


@pytest.fixture
def app_no_checks() -> FastAPI:
    """FastAPI app with health router but no checks."""
    app = FastAPI()
    health_router = HealthRouter.create(prefix="/health", tags=["Observability"])
    app.include_router(health_router)
    return app


@pytest.fixture
def app_with_checks() -> FastAPI:
    """FastAPI app with health router and custom checks."""

    async def check_healthy() -> tuple[HealthState, str | None]:
        return (HealthState.HEALTHY, None)

    async def check_degraded() -> tuple[HealthState, str | None]:
        return (HealthState.DEGRADED, "Partial outage")

    async def check_unhealthy() -> tuple[HealthState, str | None]:
        return (HealthState.UNHEALTHY, "Service down")

    async def check_exception() -> tuple[HealthState, str | None]:
        raise RuntimeError("Check failed")

    app = FastAPI()
    health_router = HealthRouter.create(
        prefix="/health",
        tags=["Observability"],
        checks={
            "healthy_check": check_healthy,
            "degraded_check": check_degraded,
            "unhealthy_check": check_unhealthy,
            "exception_check": check_exception,
        },
    )
    app.include_router(health_router)
    return app


def test_health_check_no_checks(app_no_checks: FastAPI) -> None:
    """Test health check endpoint with no custom checks returns healthy."""
    client = TestClient(app_no_checks)
    response = client.get("/health/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "checks" not in data or data["checks"] is None


def test_health_check_with_checks(app_with_checks: FastAPI) -> None:
    """Test health check endpoint with custom checks aggregates results and returns 503."""
    client = TestClient(app_with_checks)
    response = client.get("/health/")
    assert response.status_code == 503
    data = response.json()

    # Overall status should be unhealthy (worst state)
    assert data["status"] == "unhealthy"

    # Verify individual check results
    checks = data["checks"]
    assert checks["healthy_check"]["state"] == "healthy"
    assert "message" not in checks["healthy_check"]  # None excluded

    assert checks["degraded_check"]["state"] == "degraded"
    assert checks["degraded_check"]["message"] == "Partial outage"

    assert checks["unhealthy_check"]["state"] == "unhealthy"
    assert checks["unhealthy_check"]["message"] == "Service down"

    # Exception should be caught and reported as unhealthy
    assert checks["exception_check"]["state"] == "unhealthy"
    assert "Check failed" in checks["exception_check"]["message"]


def test_health_check_degraded_returns_200() -> None:
    """Test that a degraded aggregate state still returns 200."""

    async def check_degraded() -> tuple[HealthState, str | None]:
        return (HealthState.DEGRADED, "Partial outage")

    app = FastAPI()
    app.include_router(HealthRouter.create(prefix="/health", tags=["Observability"], checks={"cache": check_degraded}))

    client = TestClient(app)
    response = client.get("/health/")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"


def test_health_check_failing_check_returns_503() -> None:
    """Test that a check raising an exception yields 503."""

    async def check_raises() -> tuple[HealthState, str | None]:
        raise RuntimeError("Check failed")

    app = FastAPI()
    app.include_router(HealthRouter.create(prefix="/health", tags=["Observability"], checks={"db": check_raises}))

    client = TestClient(app)
    response = client.get("/health/")

    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"


def test_health_state_enum() -> None:
    """Test HealthState enum values."""
    assert HealthState.HEALTHY.value == "healthy"
    assert HealthState.DEGRADED.value == "degraded"
    assert HealthState.UNHEALTHY.value == "unhealthy"


def test_check_result_model() -> None:
    """Test CheckResult model."""
    result = CheckResult(state=HealthState.HEALTHY, message=None)
    assert result.state == HealthState.HEALTHY
    assert result.message is None

    result_with_msg = CheckResult(state=HealthState.UNHEALTHY, message="Error occurred")
    assert result_with_msg.state == HealthState.UNHEALTHY
    assert result_with_msg.message == "Error occurred"


def test_health_status_model() -> None:
    """Test HealthStatus model."""
    status = HealthStatus(status=HealthState.HEALTHY)
    assert status.status == HealthState.HEALTHY
    assert status.checks is None

    checks = {"test": CheckResult(state=HealthState.HEALTHY, message=None)}
    status_with_checks = HealthStatus(status=HealthState.HEALTHY, checks=checks)
    assert status_with_checks.status == HealthState.HEALTHY
    assert status_with_checks.checks == checks


def test_health_check_aggregation_priority() -> None:
    """Test that unhealthy > degraded > healthy in aggregation."""

    async def check_healthy() -> tuple[HealthState, str | None]:
        return (HealthState.HEALTHY, None)

    async def check_degraded() -> tuple[HealthState, str | None]:
        return (HealthState.DEGRADED, "Warning")

    # Only healthy checks -> overall healthy
    app = FastAPI()
    router = HealthRouter.create(prefix="/health", tags=["Observability"], checks={"healthy": check_healthy})
    app.include_router(router)

    client = TestClient(app)
    response = client.get("/health/")
    assert response.json()["status"] == "healthy"

    # Healthy + degraded -> overall degraded
    app2 = FastAPI()
    router2 = HealthRouter.create(
        prefix="/health", tags=["Observability"], checks={"healthy": check_healthy, "degraded": check_degraded}
    )
    app2.include_router(router2)

    client2 = TestClient(app2)
    response = client2.get("/health/")
    assert response.json()["status"] == "degraded"


class TestHealthRouterSSE:
    """Test health router SSE streaming.

    Note: SSE streaming tests are skipped for automated testing due to httpx AsyncClient
    + ASGITransport limitations with infinite streams. The endpoint is manually tested
    and works correctly with real HTTP clients (curl, browsers, etc.).
    """

    @pytest.mark.skip(reason="httpx AsyncClient with ASGITransport cannot handle infinite SSE streams properly")
    @pytest.mark.asyncio
    async def test_stream_health_no_checks(self) -> None:
        """Test SSE streaming with no custom checks."""
        import json

        app = FastAPI()
        health_router = HealthRouter.create(prefix="/health", tags=["Observability"])
        app.include_router(health_router)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            events = []
            async with client.stream("GET", "/health/$stream?poll_interval=0.1") as response:
                assert response.status_code == 200
                assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
                assert response.headers["cache-control"] == "no-cache"
                assert response.headers["connection"] == "keep-alive"

                # Collect a few events
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = json.loads(line[6:])
                        events.append(data)
                        if len(events) >= 3:
                            break

        # All events should show healthy status
        assert len(events) >= 3
        for event in events:
            assert event["status"] == "healthy"
            assert "checks" not in event or event["checks"] is None

    @pytest.mark.skip(reason="httpx AsyncClient with ASGITransport cannot handle infinite SSE streams properly")
    @pytest.mark.asyncio
    async def test_stream_health_with_checks(self) -> None:
        """Test SSE streaming with custom health checks."""
        import json

        async def check_healthy() -> tuple[HealthState, str | None]:
            return (HealthState.HEALTHY, None)

        async def check_degraded() -> tuple[HealthState, str | None]:
            return (HealthState.DEGRADED, "Partial outage")

        app = FastAPI()
        health_router = HealthRouter.create(
            prefix="/health",
            tags=["Observability"],
            checks={"healthy_check": check_healthy, "degraded_check": check_degraded},
        )
        app.include_router(health_router)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            events = []
            async with client.stream("GET", "/health/$stream?poll_interval=0.1") as response:
                assert response.status_code == 200

                # Collect a few events
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = json.loads(line[6:])
                        events.append(data)
                        if len(events) >= 2:
                            break

        # All events should show degraded status (worst state)
        assert len(events) >= 2
        for event in events:
            assert event["status"] == "degraded"
            assert event["checks"] is not None
            assert event["checks"]["healthy_check"]["state"] == "healthy"
            assert event["checks"]["degraded_check"]["state"] == "degraded"
            assert event["checks"]["degraded_check"]["message"] == "Partial outage"

    @pytest.mark.skip(reason="httpx AsyncClient with ASGITransport cannot handle infinite SSE streams properly")
    @pytest.mark.asyncio
    async def test_stream_health_custom_poll_interval(self) -> None:
        """Test SSE streaming with custom poll interval."""
        import json
        import time

        app = FastAPI()
        health_router = HealthRouter.create(prefix="/health", tags=["Observability"])
        app.include_router(health_router)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            events = []
            start_time = time.time()

            async with client.stream("GET", "/health/$stream?poll_interval=0.2") as response:
                assert response.status_code == 200

                # Collect 3 events
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = json.loads(line[6:])
                        events.append(data)
                        if len(events) >= 3:
                            break

            elapsed = time.time() - start_time

            # Should have taken at least 0.4 seconds (2 intervals between 3 events)
            assert elapsed >= 0.4
            assert len(events) == 3

    @pytest.mark.skip(reason="httpx AsyncClient with ASGITransport cannot handle infinite SSE streams properly")
    @pytest.mark.asyncio
    async def test_stream_health_state_transitions(self) -> None:
        """Test SSE streaming captures state transitions over time."""
        import json

        health_state = {"current": HealthState.HEALTHY}

        async def dynamic_check() -> tuple[HealthState, str | None]:
            return (health_state["current"], None)

        app = FastAPI()
        health_router = HealthRouter.create(prefix="/health", tags=["Observability"], checks={"dynamic": dynamic_check})
        app.include_router(health_router)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            events = []

            async with client.stream("GET", "/health/$stream?poll_interval=0.1") as response:
                assert response.status_code == 200

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = json.loads(line[6:])
                        events.append(data)

                        # Change state after collecting a few events
                        if len(events) == 2:
                            health_state["current"] = HealthState.UNHEALTHY
                        elif len(events) >= 4:
                            break

        # Verify we captured the state transition
        assert len(events) >= 4
        assert events[0]["status"] == "healthy"
        assert events[1]["status"] == "healthy"
        # State should transition to unhealthy
        assert events[3]["status"] == "unhealthy"

    @pytest.mark.skip(reason="httpx AsyncClient with ASGITransport cannot handle infinite SSE streams properly")
    @pytest.mark.asyncio
    async def test_stream_health_continuous(self) -> None:
        """Test SSE streaming continues indefinitely until client disconnects."""
        app = FastAPI()
        health_router = HealthRouter.create(prefix="/health", tags=["Observability"])
        app.include_router(health_router)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            event_count = 0

            async with client.stream("GET", "/health/$stream?poll_interval=0.05") as response:
                assert response.status_code == 200

                # Collect many events to verify continuous streaming
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        event_count += 1
                        if event_count >= 10:
                            break

        # Should have received many events
        assert event_count == 10
