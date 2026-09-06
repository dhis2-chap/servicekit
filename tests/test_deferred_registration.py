"""Tests for deferred service registration lifecycle."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from servicekit.api.service_builder import (
    BaseServiceBuilder,
    ServiceInfo,
    _register_after_ready,
    _register_and_start_keepalive,
    _RegistrationOptions,
    _resolve_port,
    _wait_until_ready,
)


def _make_options() -> _RegistrationOptions:
    """Create _RegistrationOptions with sensible defaults."""
    return _RegistrationOptions(
        orchestrator_url="http://orchestrator:9000/services/$register",
        host="test-host",
        port=9999,
        orchestrator_url_env="SERVICEKIT_ORCHESTRATOR_URL",
        host_env="SERVICEKIT_HOST",
        port_env="SERVICEKIT_PORT",
        max_retries=1,
        retry_delay=0.0,
        fail_on_error=False,
        timeout=2.0,
        enable_keepalive=False,
        keepalive_interval=10.0,
        auto_deregister=True,
        service_key=None,
        service_key_env="SERVICEKIT_REGISTRATION_KEY",
        re_register_grace_period=30.0,
    )


def _make_info() -> ServiceInfo:
    """Create a minimal ServiceInfo."""
    return ServiceInfo(id="test-svc", display_name="Test Service")


# ---------------------------------------------------------------------------
# _wait_until_ready
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_until_ready_health_success():
    """Return True when health endpoint responds 200."""
    mock_response = MagicMock(status_code=200)
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _wait_until_ready(9999, health_path="/health", timeout=2.0)

    assert result is True
    mock_client.get.assert_called_once()
    assert "/health" in str(mock_client.get.call_args)


@pytest.mark.asyncio
async def test_wait_until_ready_tcp_fallback_any_status():
    """Return True on any HTTP response when no health_path (TCP mode)."""
    mock_response = MagicMock(status_code=404)
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _wait_until_ready(9999, health_path=None, timeout=2.0)

    assert result is True


@pytest.mark.asyncio
async def test_wait_until_ready_timeout():
    """Return False when the endpoint never responds within timeout."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=ConnectionError("refused"))

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _wait_until_ready(9999, health_path="/health", poll_interval=0.05, timeout=0.15)

    assert result is False


@pytest.mark.asyncio
async def test_wait_until_ready_custom_health_path():
    """Use the custom health path, not hardcoded /health."""
    mock_response = MagicMock(status_code=200)
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _wait_until_ready(9999, health_path="/status", timeout=2.0)

    assert result is True
    url_called = str(mock_client.get.call_args)
    assert "/status" in url_called
    assert "/health" not in url_called


# ---------------------------------------------------------------------------
# _register_after_ready
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_after_ready_skips_when_not_ready():
    """Do not register when readiness check times out."""
    options = _make_options()
    info = _make_info()
    app = FastAPI()

    with (
        patch(
            "servicekit.api.service_builder._wait_until_ready",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "servicekit.api.service_builder._register_and_start_keepalive",
            new_callable=AsyncMock,
        ) as mock_register,
    ):
        await _register_after_ready(options, info, app, "/health")

    mock_register.assert_not_called()
    assert not hasattr(app.state, "registration_info")


@pytest.mark.asyncio
async def test_register_after_ready_registers_when_ready():
    """Register and store info on app.state when readiness succeeds."""
    options = _make_options()
    info = _make_info()
    app = FastAPI()
    reg_info = {"service_id": "svc-1", "orchestrator_url": "http://orch", "ping_url": None}

    with (
        patch(
            "servicekit.api.service_builder._wait_until_ready",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "servicekit.api.service_builder._register_and_start_keepalive",
            new_callable=AsyncMock,
            return_value=reg_info,
        ),
    ):
        await _register_after_ready(options, info, app, "/health")

    assert app.state.registration_info == reg_info


@pytest.mark.asyncio
async def test_register_after_ready_stores_state_on_cancellation():
    """Registration info is stored even if task is cancelled mid-registration."""
    options = _make_options()
    info = _make_info()
    app = FastAPI()
    reg_info = {"service_id": "svc-1", "orchestrator_url": "http://orch", "ping_url": None}

    async def slow_register(*_args: object, **_kwargs: object) -> dict[str, str | None]:
        """Simulate a registration that takes some time."""
        await asyncio.sleep(0.1)
        return reg_info

    with (
        patch(
            "servicekit.api.service_builder._wait_until_ready",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "servicekit.api.service_builder._register_and_start_keepalive",
            side_effect=slow_register,
        ),
    ):
        task = asyncio.create_task(_register_after_ready(options, info, app, "/health"))
        # Let the task get past _wait_until_ready and into _register_and_start_keepalive
        await asyncio.sleep(0.01)
        task.cancel()
        # The shielded inner coroutine should still complete
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert app.state.registration_info == reg_info


# ---------------------------------------------------------------------------
# _resolve_port
# ---------------------------------------------------------------------------


def test_resolve_port_from_options():
    """Use port from options when explicitly set."""
    options = _make_options()
    assert _resolve_port(options) == 9999


def test_resolve_port_from_env(monkeypatch: pytest.MonkeyPatch):
    """Fall back to environment variable when options.port is None."""
    options = _RegistrationOptions(
        orchestrator_url="http://orch:9000/services/$register",
        host="h",
        port=None,
        orchestrator_url_env="SERVICEKIT_ORCHESTRATOR_URL",
        host_env="SERVICEKIT_HOST",
        port_env="SERVICEKIT_PORT",
        max_retries=1,
        retry_delay=0.0,
        fail_on_error=False,
        timeout=2.0,
        enable_keepalive=False,
        keepalive_interval=10.0,
        auto_deregister=True,
        service_key=None,
        service_key_env="SERVICEKIT_REGISTRATION_KEY",
        re_register_grace_period=30.0,
    )
    monkeypatch.setenv("SERVICEKIT_PORT", "7777")
    assert _resolve_port(options) == 7777


def test_resolve_port_default(monkeypatch: pytest.MonkeyPatch):
    """Default to 8000 when port not set anywhere."""
    options = _RegistrationOptions(
        orchestrator_url="http://orch:9000/services/$register",
        host="h",
        port=None,
        orchestrator_url_env="SERVICEKIT_ORCHESTRATOR_URL",
        host_env="SERVICEKIT_HOST",
        port_env="SERVICEKIT_PORT",
        max_retries=1,
        retry_delay=0.0,
        fail_on_error=False,
        timeout=2.0,
        enable_keepalive=False,
        keepalive_interval=10.0,
        auto_deregister=True,
        service_key=None,
        service_key_env="SERVICEKIT_REGISTRATION_KEY",
        re_register_grace_period=30.0,
    )
    monkeypatch.delenv("SERVICEKIT_PORT", raising=False)
    assert _resolve_port(options) == 8000


def test_resolve_port_invalid_env(monkeypatch: pytest.MonkeyPatch):
    """Fall back to 8000 when env var is not a valid integer."""
    options = _RegistrationOptions(
        orchestrator_url="http://orch:9000/services/$register",
        host="h",
        port=None,
        orchestrator_url_env="SERVICEKIT_ORCHESTRATOR_URL",
        host_env="SERVICEKIT_HOST",
        port_env="SERVICEKIT_PORT",
        max_retries=1,
        retry_delay=0.0,
        fail_on_error=False,
        timeout=2.0,
        enable_keepalive=False,
        keepalive_interval=10.0,
        auto_deregister=True,
        service_key=None,
        service_key_env="SERVICEKIT_REGISTRATION_KEY",
        re_register_grace_period=30.0,
    )
    monkeypatch.setenv("SERVICEKIT_PORT", "not-a-number")
    assert _resolve_port(options) == 8000


# ---------------------------------------------------------------------------
# _register_and_start_keepalive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_and_start_keepalive_success():
    """Calls register_service and returns registration info."""
    options = _make_options()
    info = _make_info()
    reg_info: dict[str, Any] = {
        "service_id": "svc-1",
        "service_url": "http://test-host:9999",
        "orchestrator_url": "http://orchestrator:9000/services/$register",
        "ttl_seconds": 60,
        "ping_url": None,
    }

    with patch(
        "servicekit.api.registration.register_service",
        new_callable=AsyncMock,
        return_value=reg_info,
    ):
        result = await _register_and_start_keepalive(options, info, FastAPI())

    assert result == reg_info


@pytest.mark.asyncio
async def test_register_and_start_keepalive_with_keepalive():
    """Starts keepalive when registration returns a ping_url."""
    options = _RegistrationOptions(
        orchestrator_url="http://orchestrator:9000/services/$register",
        host="test-host",
        port=9999,
        orchestrator_url_env="SERVICEKIT_ORCHESTRATOR_URL",
        host_env="SERVICEKIT_HOST",
        port_env="SERVICEKIT_PORT",
        max_retries=1,
        retry_delay=0.0,
        fail_on_error=False,
        timeout=2.0,
        enable_keepalive=True,
        keepalive_interval=10.0,
        auto_deregister=True,
        service_key=None,
        service_key_env="SERVICEKIT_REGISTRATION_KEY",
        re_register_grace_period=30.0,
    )
    info = _make_info()
    reg_info: dict[str, Any] = {
        "service_id": "svc-1",
        "service_url": "http://test-host:9999",
        "orchestrator_url": "http://orchestrator:9000/services/$register",
        "ttl_seconds": 60,
        "ping_url": "http://orchestrator:9000/services/svc-1/$ping",
    }

    with (
        patch(
            "servicekit.api.registration.register_service",
            new_callable=AsyncMock,
            return_value=reg_info,
        ),
        patch(
            "servicekit.api.registration.start_keepalive",
            new_callable=AsyncMock,
        ) as mock_keepalive,
    ):
        result = await _register_and_start_keepalive(options, info, FastAPI())

    assert result == reg_info
    mock_keepalive.assert_called_once()


@pytest.mark.asyncio
async def test_register_and_start_keepalive_failure():
    """Returns None when registration fails."""
    options = _make_options()
    info = _make_info()

    with patch(
        "servicekit.api.registration.register_service",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await _register_and_start_keepalive(options, info, FastAPI())

    assert result is None


# ---------------------------------------------------------------------------
# Lifespan integration: builder creates deferred registration task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifespan_deferred_registration_and_deregistration():
    """Builder with registration creates a deferred task; shutdown deregisters."""
    reg_info: dict[str, Any] = {
        "service_id": "svc-1",
        "service_url": "http://test-host:9999",
        "orchestrator_url": "http://orchestrator:9000/services/$register",
        "ttl_seconds": 60,
        "ping_url": None,
    }

    builder = (
        BaseServiceBuilder(info=ServiceInfo(id="test-svc", display_name="Test"))
        .with_health()
        .with_registration(
            orchestrator_url="http://orchestrator:9000/services/$register",
            host="test-host",
            port=9999,
            enable_keepalive=False,
        )
    )
    app = builder.build()

    with (
        patch(
            "servicekit.api.service_builder._wait_until_ready",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "servicekit.api.registration.register_service",
            new_callable=AsyncMock,
            return_value=reg_info,
        ),
        patch(
            "servicekit.api.registration.deregister_service",
            new_callable=AsyncMock,
        ) as mock_deregister,
    ):
        async with app.router.lifespan_context(app):
            # Let the background task complete
            await asyncio.sleep(0.05)
            assert app.state.registration_info == reg_info

        # After lifespan exit, deregister should have been called
        mock_deregister.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_no_registration_when_not_ready():
    """Registration is skipped when readiness check fails."""
    builder = (
        BaseServiceBuilder(info=ServiceInfo(id="test-svc", display_name="Test"))
        .with_health()
        .with_registration(
            orchestrator_url="http://orchestrator:9000/services/$register",
            host="test-host",
            port=9999,
            enable_keepalive=False,
        )
    )
    app = builder.build()

    with (
        patch(
            "servicekit.api.service_builder._wait_until_ready",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "servicekit.api.registration.register_service",
            new_callable=AsyncMock,
        ) as mock_register,
        patch(
            "servicekit.api.registration.deregister_service",
            new_callable=AsyncMock,
        ) as mock_deregister,
    ):
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0.05)

        mock_register.assert_not_called()
        mock_deregister.assert_not_called()
