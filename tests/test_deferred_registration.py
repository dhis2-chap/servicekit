"""Tests for deferred service registration lifecycle."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI

from servicekit.api.service_builder import (
    _READINESS_TOKEN_HEADER,
    BaseServiceBuilder,
    ServiceInfo,
    _local_port_candidates,
    _register_after_ready,
    _register_and_start_keepalive,
    _RegistrationOptions,
    _wait_until_ready,
)

TOKEN = "test-readiness-token"


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


def _make_app() -> FastAPI:
    """Create a bare app carrying the readiness token that build() would set."""
    app = FastAPI()
    app.state.readiness_token = TOKEN
    return app


def _patch_probe_transport(handler: Any) -> Any:
    """Route the readiness probe's httpx clients through a mock transport handler."""
    real_client = httpx.AsyncClient
    return patch("httpx.AsyncClient", lambda: real_client(transport=httpx.MockTransport(handler)))


def _own_response(status_code: int = 200) -> httpx.Response:
    """Build a response that echoes this app's readiness token."""
    return httpx.Response(status_code, headers={_READINESS_TOKEN_HEADER: TOKEN})


def _make_info() -> ServiceInfo:
    """Create a minimal ServiceInfo."""
    return ServiceInfo(id="test-svc", display_name="Test Service")


# ---------------------------------------------------------------------------
# _wait_until_ready
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_until_ready_health_success():
    """Return the port when the health endpoint responds 200 with the token echoed."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Answer as this app."""
        requests.append(request)
        return _own_response()

    with _patch_probe_transport(handler):
        result = await _wait_until_ready([9999], token=TOKEN, health_path="/health", timeout=2.0)

    assert result == 9999
    assert len(requests) == 1
    assert str(requests[0].url) == "http://127.0.0.1:9999/health"
    assert requests[0].headers[_READINESS_TOKEN_HEADER] == TOKEN


@pytest.mark.asyncio
async def test_wait_until_ready_tcp_fallback_any_status():
    """Return the port on any status from this app when no health_path (TCP mode)."""
    with _patch_probe_transport(lambda request: _own_response(404)):
        result = await _wait_until_ready([9999], token=TOKEN, health_path=None, timeout=2.0)

    assert result == 9999


@pytest.mark.asyncio
async def test_wait_until_ready_timeout():
    """Return None when the endpoint never responds within timeout."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Refuse every connection."""
        raise httpx.ConnectError("refused", request=request)

    with _patch_probe_transport(handler):
        result = await _wait_until_ready([9999], token=TOKEN, health_path="/health", poll_interval=0.05, timeout=0.15)

    assert result is None


@pytest.mark.asyncio
async def test_wait_until_ready_custom_health_path():
    """Use the custom health path, not hardcoded /health."""
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Record the probed path."""
        paths.append(request.url.path)
        return _own_response()

    with _patch_probe_transport(handler):
        result = await _wait_until_ready([9999], token=TOKEN, health_path="/status", timeout=2.0)

    assert result == 9999
    assert paths == ["/status"]


@pytest.mark.asyncio
async def test_wait_until_ready_unhealthy_is_not_ready():
    """A non-200 health response from this app is not ready."""
    with _patch_probe_transport(lambda request: _own_response(503)):
        result = await _wait_until_ready([9999], token=TOKEN, health_path="/health", poll_interval=0.05, timeout=0.15)

    assert result is None


@pytest.mark.asyncio
async def test_wait_until_ready_ignores_other_service_on_candidate_port():
    """A healthy response without this app's token (another service) is not accepted."""
    with _patch_probe_transport(lambda request: httpx.Response(200)):
        result = await _wait_until_ready([8000], token=TOKEN, health_path="/health", poll_interval=0.05, timeout=0.15)

    assert result is None


@pytest.mark.asyncio
async def test_wait_until_ready_finds_bind_port_behind_published_port():
    """CLIM-1248: advertised port 18701 is not bound locally, the app answers on 8000."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Only port 8000 is bound inside the container."""
        if request.url.port == 8000:
            return _own_response()
        raise httpx.ConnectError("refused", request=request)

    with _patch_probe_transport(handler):
        result = await _wait_until_ready([18701, 8000], token=TOKEN, health_path="/health", timeout=2.0)

    assert result == 8000


@pytest.mark.asyncio
async def test_readiness_token_middleware_echoes_token_through_auth():
    """The built app echoes the token only when presented, even on responses auth rejects."""
    app = (
        BaseServiceBuilder(info=ServiceInfo(id="test-svc", display_name="Test"))
        .with_auth(api_keys=["secret"], unauthenticated_paths=[])
        .with_registration(orchestrator_url="http://orchestrator:9000/services/$register")
        .build()
    )
    token = app.state.readiness_token

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        probed = await client.get("/api/v1/info", headers={_READINESS_TOKEN_HEADER: token})
        wrong = await client.get("/api/v1/info", headers={_READINESS_TOKEN_HEADER: "other"})
        plain = await client.get("/api/v1/info")

    assert probed.status_code == 401
    assert probed.headers[_READINESS_TOKEN_HEADER] == token
    assert _READINESS_TOKEN_HEADER not in wrong.headers
    assert _READINESS_TOKEN_HEADER not in plain.headers


def test_readiness_token_only_installed_with_registration():
    """Apps without registration get no readiness token."""
    app = BaseServiceBuilder(info=ServiceInfo(id="test-svc", display_name="Test")).build()

    assert not hasattr(app.state, "readiness_token")


# ---------------------------------------------------------------------------
# _register_after_ready
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_after_ready_skips_when_not_ready():
    """Do not register when readiness check times out."""
    options = _make_options()
    info = _make_info()
    app = _make_app()

    with (
        patch(
            "servicekit.api.service_builder._wait_until_ready",
            new_callable=AsyncMock,
            return_value=None,
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
    app = _make_app()
    reg_info = {"service_id": "svc-1", "orchestrator_url": "http://orch", "ping_url": None}

    with (
        patch(
            "servicekit.api.service_builder._wait_until_ready",
            new_callable=AsyncMock,
            return_value=9999,
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
    app = _make_app()
    reg_info = {"service_id": "svc-1", "orchestrator_url": "http://orch", "ping_url": None}

    async def slow_register(*_args: object, **_kwargs: object) -> dict[str, str | None]:
        """Simulate a registration that takes some time."""
        await asyncio.sleep(0.1)
        return reg_info

    with (
        patch(
            "servicekit.api.service_builder._wait_until_ready",
            new_callable=AsyncMock,
            return_value=9999,
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
# _local_port_candidates
# ---------------------------------------------------------------------------


def _make_port_options(*, port: int | None = None, local_port: int | None = None) -> _RegistrationOptions:
    """Create _RegistrationOptions with only the port settings varied."""
    return _RegistrationOptions(
        orchestrator_url="http://orch:9000/services/$register",
        host="h",
        port=port,
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
        local_port=local_port,
    )


@pytest.fixture
def clean_port_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Clear PORT and SERVICEKIT_PORT so candidates depend only on the test."""
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("SERVICEKIT_PORT", raising=False)
    return monkeypatch


def test_local_port_candidates_explicit_local_port_only(clean_port_env: pytest.MonkeyPatch):
    """An explicit local_port is authoritative."""
    clean_port_env.setenv("PORT", "5000")
    assert _local_port_candidates(_make_port_options(port=18701, local_port=9000)) == [9000]


def test_local_port_candidates_default(clean_port_env: pytest.MonkeyPatch):
    """Default to 8000 when no port is set anywhere."""
    assert _local_port_candidates(_make_port_options()) == [8000]


def test_local_port_candidates_advertised_port_from_options(clean_port_env: pytest.MonkeyPatch):
    """Try the advertised port before the 8000 default."""
    assert _local_port_candidates(_make_port_options(port=9999)) == [9999, 8000]


def test_local_port_candidates_advertised_port_from_env(clean_port_env: pytest.MonkeyPatch):
    """CLIM-1248: a published SERVICEKIT_PORT still falls back to the 8000 bind port."""
    clean_port_env.setenv("SERVICEKIT_PORT", "18701")
    assert _local_port_candidates(_make_port_options()) == [18701, 8000]


def test_local_port_candidates_port_env_first(clean_port_env: pytest.MonkeyPatch):
    """PORT is tried first, then the advertised port, then 8000."""
    clean_port_env.setenv("PORT", "5000")
    clean_port_env.setenv("SERVICEKIT_PORT", "18701")
    assert _local_port_candidates(_make_port_options()) == [5000, 18701, 8000]


def test_local_port_candidates_deduplicates(clean_port_env: pytest.MonkeyPatch):
    """Identical ports are probed once."""
    clean_port_env.setenv("PORT", "8000")
    clean_port_env.setenv("SERVICEKIT_PORT", "8000")
    assert _local_port_candidates(_make_port_options()) == [8000]


def test_local_port_candidates_ignores_invalid_env(clean_port_env: pytest.MonkeyPatch):
    """Invalid port values in the environment are skipped."""
    clean_port_env.setenv("PORT", "abc")
    clean_port_env.setenv("SERVICEKIT_PORT", "not-a-number")
    assert _local_port_candidates(_make_port_options()) == [8000]


@pytest.mark.asyncio
async def test_register_after_ready_probes_candidates_with_app_token(clean_port_env: pytest.MonkeyPatch):
    """Readiness is probed over the candidate ports with the app's own token."""
    clean_port_env.setenv("SERVICEKIT_PORT", "18701")
    options = _make_port_options()

    with (
        patch(
            "servicekit.api.service_builder._wait_until_ready",
            new_callable=AsyncMock,
            return_value=8000,
        ) as mock_wait,
        patch(
            "servicekit.api.service_builder._register_and_start_keepalive",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_register,
    ):
        await _register_after_ready(options, _make_info(), _make_app(), "/health")

    mock_wait.assert_awaited_once_with([18701, 8000], token=TOKEN, health_path="/health")
    mock_register.assert_awaited_once()


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
            return_value=9999,
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
            return_value=None,
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
