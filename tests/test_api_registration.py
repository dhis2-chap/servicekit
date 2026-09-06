"""Tests for service registration with orchestrator."""

import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from servicekit.api.registration import (
    RegistrationConfig,
    deregister_service,
    register_service,
    start_keepalive,
    stop_keepalive,
)
from servicekit.api.service_builder import ServiceInfo


class CustomServiceInfo(ServiceInfo):
    """Custom ServiceInfo with additional fields."""

    team: str = "platform"
    priority: int = 1


# --- ServiceInfo ID Validation Tests ---


def test_service_info_valid_id():
    """Test valid slug format IDs are accepted."""
    valid_ids = [
        "my-service",
        "chap-ewars",
        "prediction-service",
        "service1",
        "a",
        "a1",
        "my-service-v2",
        "test123",
    ]
    for service_id in valid_ids:
        info = ServiceInfo(id=service_id, display_name="Test")
        assert info.id == service_id


def test_service_info_invalid_id_uppercase():
    """Test uppercase letters are rejected."""
    with pytest.raises(ValueError, match="slug format"):
        ServiceInfo(id="My-Service", display_name="Test")


def test_service_info_invalid_id_spaces():
    """Test spaces are rejected."""
    with pytest.raises(ValueError, match="slug format"):
        ServiceInfo(id="my service", display_name="Test")


def test_service_info_invalid_id_special_chars():
    """Test special characters are rejected."""
    invalid_ids = ["my_service", "my.service", "my@service", "my/service"]
    for service_id in invalid_ids:
        with pytest.raises(ValueError, match="slug format"):
            ServiceInfo(id=service_id, display_name="Test")


def test_service_info_invalid_id_starts_with_number():
    """Test IDs starting with number are rejected."""
    with pytest.raises(ValueError, match="slug format"):
        ServiceInfo(id="1-service", display_name="Test")


def test_service_info_invalid_id_consecutive_hyphens():
    """Test consecutive hyphens are rejected."""
    with pytest.raises(ValueError, match="slug format"):
        ServiceInfo(id="my--service", display_name="Test")


def test_service_info_invalid_id_trailing_hyphen():
    """Test trailing hyphen is rejected."""
    with pytest.raises(ValueError, match="slug format"):
        ServiceInfo(id="my-service-", display_name="Test")


def test_service_info_invalid_id_leading_hyphen():
    """Test leading hyphen is rejected."""
    with pytest.raises(ValueError, match="slug format"):
        ServiceInfo(id="-my-service", display_name="Test")


def test_service_info_id_required():
    """Test missing ID raises validation error."""
    with pytest.raises(ValueError):
        ServiceInfo(display_name="Test")  # type: ignore[call-arg]


# --- Registration Tests ---


@pytest.mark.asyncio
async def test_registration_missing_service_id_fail_on_error():
    """Test registration fails when info has no id attribute and fail_on_error=True."""
    # Create a mock info object without 'id' attribute
    mock_info = MagicMock(spec=[])  # Empty spec means no 'id' attribute
    mock_info.model_dump = MagicMock(return_value={"display_name": "Test"})

    with pytest.raises(ValueError, match="must have an 'id' attribute"):
        await register_service(
            orchestrator_url="http://orchestrator:9000/services/$register",
            host="test-service",
            port=8000,
            info=mock_info,
            fail_on_error=True,
        )


@pytest.mark.asyncio
async def test_registration_missing_service_id_returns_none():
    """Test registration returns None when info has no id attribute and fail_on_error=False."""
    # Create a mock info object without 'id' attribute
    mock_info = MagicMock(spec=[])  # Empty spec means no 'id' attribute
    mock_info.model_dump = MagicMock(return_value={"display_name": "Test"})

    result = await register_service(
        orchestrator_url="http://orchestrator:9000/services/$register",
        host="test-service",
        port=8000,
        info=mock_info,
        fail_on_error=False,
    )

    assert result is None


@pytest.mark.asyncio
async def test_successful_registration():
    """Test successful service registration."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(
        return_value={
            "id": "01K83B5V85PQZ1HTH4DQ7NC9JM",
            "status": "registered",
            "service_url": "http://test-service:8000",
            "message": "Service registered successfully",
        }
    )

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

        info = ServiceInfo(id="test-service", display_name="Test Service", version="1.0.0")

        await register_service(
            orchestrator_url="http://orchestrator:9000/services/$register",
            host="test-service",
            port=8000,
            info=info,
        )

        # Verify POST was called with correct payload
        call_args = mock_client.return_value.__aenter__.return_value.post.call_args
        assert call_args[0][0] == "http://orchestrator:9000/services/$register"
        payload = call_args[1]["json"]
        assert payload["id"] == "test-service"
        assert payload["url"] == "http://test-service:8000"
        assert payload["info"]["display_name"] == "Test Service"


@pytest.mark.asyncio
async def test_retry_logic_success_on_second_attempt():
    """Test retry logic succeeds on second attempt."""
    mock_response_fail = MagicMock()
    mock_response_fail.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("500 error", request=MagicMock(), response=MagicMock())
    )

    mock_response_success = MagicMock()
    mock_response_success.status_code = 200
    mock_response_success.raise_for_status = MagicMock()
    mock_response_success.json = MagicMock(
        return_value={
            "id": "01K83B5V85PQZ1HTH4DQ7NC9JM",
            "status": "registered",
            "service_url": "http://test-service:8000",
            "message": "Service registered successfully",
        }
    )

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            side_effect=[mock_response_fail, mock_response_success]
        )

        info = ServiceInfo(id="test-service", display_name="Test Service")

        await register_service(
            orchestrator_url="http://orchestrator:9000/services/$register",
            host="test-service",
            port=8000,
            info=info,
            max_retries=3,
            retry_delay=0.1,  # Short delay for testing
        )

        # Should have been called twice (fail, then success)
        assert mock_client.return_value.__aenter__.return_value.post.call_count == 2


@pytest.mark.asyncio
async def test_fail_on_error_true_raises_exception():
    """Test that fail_on_error=True raises exception after retries exhausted."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("500 error", request=MagicMock(), response=MagicMock())
    )

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

        info = ServiceInfo(id="test-service", display_name="Test Service")

        with pytest.raises(RuntimeError, match="Failed to register service"):
            await register_service(
                orchestrator_url="http://orchestrator:9000/services/$register",
                host="test-service",
                port=8000,
                info=info,
                max_retries=2,
                retry_delay=0.1,
                fail_on_error=True,
            )


@pytest.mark.asyncio
async def test_fail_on_error_false_continues():
    """Test that fail_on_error=False logs warning and continues."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("500 error", request=MagicMock(), response=MagicMock())
    )

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

        info = ServiceInfo(id="test-service", display_name="Test Service")

        # Should not raise exception
        await register_service(
            orchestrator_url="http://orchestrator:9000/services/$register",
            host="test-service",
            port=8000,
            info=info,
            max_retries=2,
            retry_delay=0.1,
            fail_on_error=False,
        )


@pytest.mark.asyncio
async def test_hostname_resolution_parameter():
    """Test hostname resolution from parameter."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client, patch.dict(os.environ, {}, clear=True):
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

        info = ServiceInfo(id="test-service", display_name="Test Service")

        await register_service(
            orchestrator_url="http://orchestrator:9000/services/$register",
            host="param-hostname",  # Explicit parameter
            port=8000,
            info=info,
        )

        payload = mock_client.return_value.__aenter__.return_value.post.call_args[1]["json"]
        assert payload["url"] == "http://param-hostname:8000"


@pytest.mark.asyncio
async def test_hostname_resolution_auto_detect():
    """Test hostname resolution from socket.gethostname()."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    with (
        patch("httpx.AsyncClient") as mock_client,
        patch("socket.gethostname", return_value="container-name"),
        patch.dict(os.environ, {}, clear=True),
    ):
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

        info = ServiceInfo(id="test-service", display_name="Test Service")

        await register_service(
            orchestrator_url="http://orchestrator:9000/services/$register",
            host=None,  # No explicit host
            port=8000,
            info=info,
        )

        payload = mock_client.return_value.__aenter__.return_value.post.call_args[1]["json"]
        assert payload["url"] == "http://container-name:8000"


@pytest.mark.asyncio
async def test_hostname_resolution_env_var():
    """Test hostname resolution from environment variable takes priority over auto-detect."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    with (
        patch("httpx.AsyncClient") as mock_client,
        patch("socket.gethostname", return_value="auto-detected-host"),
        patch.dict(os.environ, {"SERVICEKIT_HOST": "env-hostname"}),
    ):
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

        info = ServiceInfo(id="test-service", display_name="Test Service")

        await register_service(
            orchestrator_url="http://orchestrator:9000/services/$register",
            host=None,
            port=8000,
            info=info,
        )

        payload = mock_client.return_value.__aenter__.return_value.post.call_args[1]["json"]
        assert payload["url"] == "http://env-hostname:8000"


@pytest.mark.asyncio
async def test_hostname_missing_raises_with_fail_on_error():
    """Test missing hostname raises exception when fail_on_error=True."""
    with patch("socket.gethostname", side_effect=Exception("No hostname")), patch.dict(os.environ, {}, clear=True):
        info = ServiceInfo(id="test-service", display_name="Test Service")

        # Should log warning and return early (no exception with fail_on_error=False)
        await register_service(
            orchestrator_url="http://orchestrator:9000/services/$register",
            host=None,
            port=8000,
            info=info,
            fail_on_error=False,
        )

        # With fail_on_error=True, should raise
        with pytest.raises(ValueError, match="Host not provided"):
            await register_service(
                orchestrator_url="http://orchestrator:9000/services/$register",
                host=None,
                port=8000,
                info=info,
                fail_on_error=True,
            )


@pytest.mark.asyncio
async def test_port_resolution_parameter():
    """Test port resolution from parameter."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

        info = ServiceInfo(id="test-service", display_name="Test Service")

        await register_service(
            orchestrator_url="http://orchestrator:9000/services/$register",
            host="test-service",
            port=9999,  # Explicit parameter
            info=info,
        )

        payload = mock_client.return_value.__aenter__.return_value.post.call_args[1]["json"]
        assert payload["url"] == "http://test-service:9999"


@pytest.mark.asyncio
async def test_port_resolution_env_var():
    """Test port resolution from environment variable."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client, patch.dict(os.environ, {"SERVICEKIT_PORT": "7777"}):
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

        info = ServiceInfo(id="test-service", display_name="Test Service")

        await register_service(
            orchestrator_url="http://orchestrator:9000/services/$register",
            host="test-service",
            port=None,  # No explicit port
            info=info,
        )

        payload = mock_client.return_value.__aenter__.return_value.post.call_args[1]["json"]
        assert payload["url"] == "http://test-service:7777"


@pytest.mark.asyncio
async def test_port_resolution_default():
    """Test port resolution defaults to 8000."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client, patch.dict(os.environ, {}, clear=True):
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

        info = ServiceInfo(id="test-service", display_name="Test Service")

        await register_service(
            orchestrator_url="http://orchestrator:9000/services/$register",
            host="test-service",
            port=None,
            info=info,
        )

        payload = mock_client.return_value.__aenter__.return_value.post.call_args[1]["json"]
        assert payload["url"] == "http://test-service:8000"


@pytest.mark.asyncio
async def test_custom_env_var_names():
    """Test custom environment variable names."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    with (
        patch("httpx.AsyncClient") as mock_client,
        patch("socket.gethostname", side_effect=Exception("No auto-detect")),  # Prevent auto-detection
        patch.dict(
            os.environ,
            {
                "MY_ORCHESTRATOR_URL": "http://custom-orch:9000/register",
                "MY_HOST": "custom-host",
                "MY_PORT": "5555",
            },
        ),
    ):
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

        info = ServiceInfo(id="test-service", display_name="Test Service")

        await register_service(
            orchestrator_url=None,
            host=None,
            port=None,
            info=info,
            orchestrator_url_env="MY_ORCHESTRATOR_URL",
            host_env="MY_HOST",
            port_env="MY_PORT",
        )

        call_args = mock_client.return_value.__aenter__.return_value.post.call_args
        assert call_args[0][0] == "http://custom-orch:9000/register"
        payload = call_args[1]["json"]
        assert payload["url"] == "http://custom-host:5555"


@pytest.mark.asyncio
async def test_custom_serviceinfo_serialization():
    """Test that custom ServiceInfo subclasses serialize correctly."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

        info = CustomServiceInfo(
            id="custom-service",
            display_name="Custom Service",
            version="2.0.0",
            team="data-science",
            priority=5,
        )

        await register_service(
            orchestrator_url="http://orchestrator:9000/services/$register",
            host="test-service",
            port=8000,
            info=info,
        )

        payload = mock_client.return_value.__aenter__.return_value.post.call_args[1]["json"]
        assert payload["info"]["display_name"] == "Custom Service"
        assert payload["info"]["version"] == "2.0.0"
        assert payload["info"]["team"] == "data-science"
        assert payload["info"]["priority"] == 5


@pytest.mark.asyncio
async def test_missing_orchestrator_url():
    """Test missing orchestrator URL."""
    with patch.dict(os.environ, {}, clear=True):
        info = ServiceInfo(id="test-service", display_name="Test Service")

        # Should log warning and return early (no exception with fail_on_error=False)
        await register_service(
            orchestrator_url=None,
            host="test-service",
            port=8000,
            info=info,
            fail_on_error=False,
        )

        # With fail_on_error=True, should raise
        with pytest.raises(ValueError, match="Orchestrator URL not provided"):
            await register_service(
                orchestrator_url=None,
                host="test-service",
                port=8000,
                info=info,
                fail_on_error=True,
            )


@pytest.mark.asyncio
async def test_url_construction():
    """Test correct URL construction."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

        info = ServiceInfo(id="test-service", display_name="Test Service")

        await register_service(
            orchestrator_url="http://orchestrator:9000/services/$register",
            host="my-service",
            port=8080,
            info=info,
        )

        payload = mock_client.return_value.__aenter__.return_value.post.call_args[1]["json"]
        assert payload["url"] == "http://my-service:8080"


@pytest.mark.asyncio
async def test_timeout_parameter():
    """Test that timeout parameter is passed to httpx client."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

        info = ServiceInfo(id="test-service", display_name="Test Service")

        await register_service(
            orchestrator_url="http://orchestrator:9000/services/$register",
            host="test-service",
            port=8000,
            info=info,
            timeout=5.0,
        )

        # Verify AsyncClient was called with timeout
        assert mock_client.call_args[1]["timeout"] == 5.0


@pytest.mark.asyncio
async def test_registration_returns_info():
    """Test that successful registration returns registration info."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(
        return_value={
            "id": "01K83B5V85PQZ1HTH4DQ7NC9JM",
            "status": "registered",
            "service_url": "http://test-service:8000",
            "message": "Service registered successfully",
            "ttl_seconds": 30,
            "ping_url": "http://orchestrator:9000/services/01K83B5V85PQZ1HTH4DQ7NC9JM/$ping",
        }
    )

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

        info = ServiceInfo(id="test-service", display_name="Test Service", version="1.0.0")

        result = await register_service(
            orchestrator_url="http://orchestrator:9000/services/$register",
            host="test-service",
            port=8000,
            info=info,
        )

        assert result is not None
        assert result["service_id"] == "test-service"
        assert result["service_url"] == "http://test-service:8000"
        assert result["ttl_seconds"] == 30
        assert result["ping_url"] == "http://orchestrator:9000/services/01K83B5V85PQZ1HTH4DQ7NC9JM/$ping"


@pytest.mark.asyncio
async def test_registration_returns_none_on_failure():
    """Test that failed registration returns None."""
    with patch.dict(os.environ, {}, clear=True):
        info = ServiceInfo(id="test-service", display_name="Test Service")

        result = await register_service(
            orchestrator_url=None,  # Missing URL
            host="test-service",
            port=8000,
            info=info,
            fail_on_error=False,
        )

        assert result is None


@pytest.mark.asyncio
async def test_start_keepalive():
    """Test starting keepalive background task."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(
        return_value={
            "id": "01K83B5V85PQZ1HTH4DQ7NC9JM",
            "status": "alive",
            "last_ping_at": "2025-10-27T12:00:00Z",
            "expires_at": "2025-10-27T12:00:30Z",
        }
    )

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.put = AsyncMock(return_value=mock_response)

        # Start keepalive with short interval for testing
        handle = await start_keepalive(
            service_id="test-service",
            ping_url="http://orchestrator:9000/services/01K83B5V85PQZ1HTH4DQ7NC9JM/$ping",
            interval=0.1,
            timeout=5.0,
        )

        # Give it time for at least one ping
        await asyncio.sleep(0.15)

        # Verify PUT was called
        assert mock_client.return_value.__aenter__.return_value.put.call_count >= 1

        # Clean up
        await stop_keepalive(handle)


@pytest.mark.asyncio
async def test_stop_keepalive():
    """Test stopping keepalive background task."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"status": "alive"})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.put = AsyncMock(return_value=mock_response)

        # Start keepalive
        handle = await start_keepalive(
            service_id="test-service",
            ping_url="http://orchestrator:9000/services/test/$ping",
            interval=0.1,
            timeout=5.0,
        )

        # Stop it immediately
        await stop_keepalive(handle)

        # Give it time to ensure it doesn't ping again
        initial_count = mock_client.return_value.__aenter__.return_value.put.call_count
        await asyncio.sleep(0.2)
        final_count = mock_client.return_value.__aenter__.return_value.put.call_count

        # Call count should not increase after stop
        assert final_count == initial_count


@pytest.mark.asyncio
async def test_keepalive_handles_errors_gracefully():
    """Test that keepalive task handles ping failures without crashing."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("500 error", request=MagicMock(), response=MagicMock())
    )

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.put = AsyncMock(return_value=mock_response)

        # Start keepalive - should not crash despite errors
        handle = await start_keepalive(
            service_id="test-service",
            ping_url="http://orchestrator:9000/services/test/$ping",
            interval=0.1,
            timeout=5.0,
        )

        # Wait for at least one ping attempt
        await asyncio.sleep(0.15)

        # Task should still be running despite error
        assert mock_client.return_value.__aenter__.return_value.put.call_count >= 1

        # Clean up
        await stop_keepalive(handle)


@pytest.mark.asyncio
async def test_deregister_service_success():
    """Test successful service deregistration."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.delete = AsyncMock(return_value=mock_response)

        await deregister_service(
            service_id="01K83B5V85PQZ1HTH4DQ7NC9JM",
            orchestrator_url="http://orchestrator:9000/services/$register",
            timeout=5.0,
        )

        # Verify DELETE was called with correct URL
        call_args = mock_client.return_value.__aenter__.return_value.delete.call_args
        assert call_args[0][0] == "http://orchestrator:9000/services/01K83B5V85PQZ1HTH4DQ7NC9JM"


@pytest.mark.asyncio
async def test_deregister_service_handles_errors():
    """Test that deregister_service handles errors gracefully."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("404 error", request=MagicMock(), response=MagicMock())
    )

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.delete = AsyncMock(return_value=mock_response)

        # Should not raise exception, just log warning
        await deregister_service(
            service_id="01K83B5V85PQZ1HTH4DQ7NC9JM",
            orchestrator_url="http://orchestrator:9000/services/$register",
            timeout=5.0,
        )


@pytest.mark.asyncio
async def test_registration_with_service_key_parameter():
    """Test registration sends X-Service-Key header when service_key parameter is provided."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"id": "01K83B5V85PQZ1HTH4DQ7NC9JM", "status": "registered"})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

        info = ServiceInfo(id="test-service", display_name="Test Service", version="1.0.0")

        await register_service(
            orchestrator_url="http://orchestrator:9000/services/$register",
            host="test-service",
            port=8000,
            info=info,
            service_key="my-secret-key",
        )

        # Verify POST was called with X-Service-Key header
        call_args = mock_client.return_value.__aenter__.return_value.post.call_args
        headers = call_args[1].get("headers")
        assert headers is not None
        assert headers.get("X-Service-Key") == "my-secret-key"


@pytest.mark.asyncio
async def test_registration_with_service_key_from_env():
    """Test registration sends X-Service-Key header from default environment variable."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"id": "01K83B5V85PQZ1HTH4DQ7NC9JM", "status": "registered"})

    with (
        patch("httpx.AsyncClient") as mock_client,
        patch.dict(os.environ, {"SERVICEKIT_REGISTRATION_KEY": "env-secret-key"}),
    ):
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

        info = ServiceInfo(id="test-service", display_name="Test Service", version="1.0.0")

        await register_service(
            orchestrator_url="http://orchestrator:9000/services/$register",
            host="test-service",
            port=8000,
            info=info,
        )

        # Verify POST was called with X-Service-Key header from env
        call_args = mock_client.return_value.__aenter__.return_value.post.call_args
        headers = call_args[1].get("headers")
        assert headers is not None
        assert headers.get("X-Service-Key") == "env-secret-key"


@pytest.mark.asyncio
async def test_registration_with_custom_service_key_env():
    """Test registration uses custom environment variable name for service key."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"id": "01K83B5V85PQZ1HTH4DQ7NC9JM", "status": "registered"})

    with (
        patch("httpx.AsyncClient") as mock_client,
        patch.dict(os.environ, {"MY_CUSTOM_SERVICE_KEY": "custom-env-key"}),
    ):
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

        info = ServiceInfo(id="test-service", display_name="Test Service", version="1.0.0")

        await register_service(
            orchestrator_url="http://orchestrator:9000/services/$register",
            host="test-service",
            port=8000,
            info=info,
            service_key_env="MY_CUSTOM_SERVICE_KEY",
        )

        # Verify POST was called with X-Service-Key header from custom env
        call_args = mock_client.return_value.__aenter__.return_value.post.call_args
        headers = call_args[1].get("headers")
        assert headers is not None
        assert headers.get("X-Service-Key") == "custom-env-key"


@pytest.mark.asyncio
async def test_registration_without_service_key():
    """Test registration works without service key (backwards compatibility)."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"id": "01K83B5V85PQZ1HTH4DQ7NC9JM", "status": "registered"})

    with patch("httpx.AsyncClient") as mock_client, patch.dict(os.environ, {}, clear=True):
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

        info = ServiceInfo(id="test-service", display_name="Test Service", version="1.0.0")

        await register_service(
            orchestrator_url="http://orchestrator:9000/services/$register",
            host="test-service",
            port=8000,
            info=info,
        )

        # Verify POST was called without headers (or with None)
        call_args = mock_client.return_value.__aenter__.return_value.post.call_args
        headers = call_args[1].get("headers")
        assert headers is None


@pytest.mark.asyncio
async def test_service_key_parameter_overrides_env():
    """Test that service_key parameter takes precedence over environment variable."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"id": "01K83B5V85PQZ1HTH4DQ7NC9JM", "status": "registered"})

    with (
        patch("httpx.AsyncClient") as mock_client,
        patch.dict(os.environ, {"SERVICEKIT_REGISTRATION_KEY": "env-key"}),
    ):
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

        info = ServiceInfo(id="test-service", display_name="Test Service", version="1.0.0")

        await register_service(
            orchestrator_url="http://orchestrator:9000/services/$register",
            host="test-service",
            port=8000,
            info=info,
            service_key="param-key",  # Should override env
        )

        # Verify POST was called with parameter value, not env value
        call_args = mock_client.return_value.__aenter__.return_value.post.call_args
        headers = call_args[1].get("headers")
        assert headers is not None
        assert headers.get("X-Service-Key") == "param-key"


@pytest.mark.asyncio
async def test_keepalive_sends_service_key():
    """Test that keepalive pings include X-Service-Key header."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"status": "alive", "last_ping_at": "2025-01-01T00:00:00Z"})

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.put = AsyncMock(return_value=mock_response)

        # Start keepalive with service key
        handle = await start_keepalive(
            service_id="test-service",
            ping_url="http://orchestrator:9000/services/test/$ping",
            interval=0.1,
            timeout=5.0,
            service_key="keepalive-secret-key",
        )

        # Wait for at least one ping
        await asyncio.sleep(0.15)

        # Verify PUT was called with X-Service-Key header
        call_args = mock_client.return_value.__aenter__.return_value.put.call_args
        headers = call_args[1].get("headers")
        assert headers is not None
        assert headers.get("X-Service-Key") == "keepalive-secret-key"

        # Clean up
        await stop_keepalive(handle)


@pytest.mark.asyncio
async def test_deregister_sends_service_key():
    """Test that deregistration includes X-Service-Key header."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.delete = AsyncMock(return_value=mock_response)

        await deregister_service(
            service_id="01K83B5V85PQZ1HTH4DQ7NC9JM",
            orchestrator_url="http://orchestrator:9000/services/$register",
            timeout=5.0,
            service_key="deregister-secret-key",
        )

        # Verify DELETE was called with X-Service-Key header
        call_args = mock_client.return_value.__aenter__.return_value.delete.call_args
        headers = call_args[1].get("headers")
        assert headers is not None
        assert headers.get("X-Service-Key") == "deregister-secret-key"


# --- Keepalive Re-registration Tests ---


def _make_registration_config() -> RegistrationConfig:
    """Build registration config for testing re-registration."""
    return RegistrationConfig(
        orchestrator_url="http://orchestrator:9000/services/$register",
        host="test-service",
        port=8000,
        info=ServiceInfo(id="test-service", display_name="Test Service", version="1.0.0"),
        max_retries=3,
        retry_delay=0.01,
        fail_on_error=False,
        timeout=5.0,
    )


def _make_404_response() -> MagicMock:
    """Build a mock 404 response for HTTPStatusError."""
    mock_response = MagicMock()
    mock_response.status_code = 404
    return mock_response


@pytest.mark.asyncio
async def test_keepalive_reregisters_on_404():
    """Test that keepalive re-registers when ping returns 404."""
    mock_404_response = _make_404_response()
    error_404 = httpx.HTTPStatusError("404 Not Found", request=MagicMock(), response=mock_404_response)

    # First ping returns 404, subsequent pings succeed after re-registration
    mock_put_response = MagicMock()
    mock_put_response.raise_for_status = MagicMock(side_effect=[error_404, None])
    mock_put_response.json = MagicMock(return_value={"status": "alive"})

    new_registration = {
        "service_id": "test-service",
        "service_url": "http://test-service:8000",
        "orchestrator_url": "http://orchestrator:9000/services/$register",
        "ping_url": "http://orchestrator:9000/services/test-service/$ping",
        "ttl_seconds": 30,
    }

    with (
        patch("httpx.AsyncClient") as mock_client,
        patch("servicekit.api.registration.register_service", new_callable=AsyncMock) as mock_register,
    ):
        mock_client.return_value.__aenter__.return_value.put = AsyncMock(return_value=mock_put_response)
        mock_register.return_value = new_registration

        handle = await start_keepalive(
            service_id="test-service",
            ping_url="http://orchestrator:9000/services/test-service/$ping",
            interval=0.05,
            timeout=5.0,
            registration_config=_make_registration_config(),
            re_register_grace_period=0.1,
        )

        # Wait for 404 + grace period + re-registration
        await asyncio.sleep(0.3)

        # Verify register_service was called
        assert mock_register.call_count >= 1

        await stop_keepalive(handle)


@pytest.mark.asyncio
async def test_keepalive_grace_period_respected():
    """Test that re-registration waits for the grace period."""
    mock_404_response = _make_404_response()
    error_404 = httpx.HTTPStatusError("404 Not Found", request=MagicMock(), response=mock_404_response)

    mock_put_response = MagicMock()
    mock_put_response.raise_for_status = MagicMock(side_effect=error_404)

    new_registration = {
        "service_id": "test-service",
        "service_url": "http://test-service:8000",
        "orchestrator_url": "http://orchestrator:9000/services/$register",
        "ping_url": "http://orchestrator:9000/services/test-service/$ping",
        "ttl_seconds": 30,
    }

    with (
        patch("httpx.AsyncClient") as mock_client,
        patch("servicekit.api.registration.register_service", new_callable=AsyncMock) as mock_register,
    ):
        mock_client.return_value.__aenter__.return_value.put = AsyncMock(return_value=mock_put_response)
        mock_register.return_value = new_registration

        handle = await start_keepalive(
            service_id="test-service",
            ping_url="http://orchestrator:9000/services/test-service/$ping",
            interval=0.05,
            timeout=5.0,
            registration_config=_make_registration_config(),
            re_register_grace_period=0.3,
        )

        # Before grace period expires, register_service should not have been called
        await asyncio.sleep(0.15)
        assert mock_register.call_count == 0

        # After grace period, it should have been called
        await asyncio.sleep(0.25)
        assert mock_register.call_count >= 1

        await stop_keepalive(handle)


@pytest.mark.asyncio
async def test_keepalive_reregistration_failure_retries():
    """Test that failed re-registration retries on next 404 cycle."""
    mock_404_response = _make_404_response()
    error_404 = httpx.HTTPStatusError("404 Not Found", request=MagicMock(), response=mock_404_response)

    mock_put_response = MagicMock()
    mock_put_response.raise_for_status = MagicMock(side_effect=error_404)

    with (
        patch("httpx.AsyncClient") as mock_client,
        patch("servicekit.api.registration.register_service", new_callable=AsyncMock) as mock_register,
    ):
        mock_client.return_value.__aenter__.return_value.put = AsyncMock(return_value=mock_put_response)
        # Re-registration fails every time
        mock_register.return_value = None

        handle = await start_keepalive(
            service_id="test-service",
            ping_url="http://orchestrator:9000/services/test-service/$ping",
            interval=0.05,
            timeout=5.0,
            registration_config=_make_registration_config(),
            re_register_grace_period=0.05,
        )

        # Wait for multiple 404 + re-registration cycles
        await asyncio.sleep(0.5)

        # Should have retried re-registration multiple times
        assert mock_register.call_count >= 2

        await stop_keepalive(handle)


@pytest.mark.asyncio
async def test_keepalive_non_404_does_not_reregister():
    """Test that non-404 HTTP errors do not trigger re-registration."""
    mock_500_response = MagicMock()
    mock_500_response.status_code = 500
    error_500 = httpx.HTTPStatusError("500 Error", request=MagicMock(), response=mock_500_response)

    mock_put_response = MagicMock()
    mock_put_response.raise_for_status = MagicMock(side_effect=error_500)

    with (
        patch("httpx.AsyncClient") as mock_client,
        patch("servicekit.api.registration.register_service", new_callable=AsyncMock) as mock_register,
    ):
        mock_client.return_value.__aenter__.return_value.put = AsyncMock(return_value=mock_put_response)

        handle = await start_keepalive(
            service_id="test-service",
            ping_url="http://orchestrator:9000/services/test-service/$ping",
            interval=0.05,
            timeout=5.0,
            registration_config=_make_registration_config(),
            re_register_grace_period=0.05,
        )

        await asyncio.sleep(0.2)

        # register_service should never be called for non-404 errors
        assert mock_register.call_count == 0

        await stop_keepalive(handle)


@pytest.mark.asyncio
async def test_keepalive_no_registration_kwargs_skips_reregistration():
    """Test that 404 without registration_kwargs just logs a warning."""
    mock_404_response = _make_404_response()
    error_404 = httpx.HTTPStatusError("404 Not Found", request=MagicMock(), response=mock_404_response)

    mock_put_response = MagicMock()
    mock_put_response.raise_for_status = MagicMock(side_effect=error_404)

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.put = AsyncMock(return_value=mock_put_response)

        # Start without registration_kwargs -- backward compatible behavior
        handle = await start_keepalive(
            service_id="test-service",
            ping_url="http://orchestrator:9000/services/test-service/$ping",
            interval=0.05,
            timeout=5.0,
        )

        await asyncio.sleep(0.15)

        # Task should still be running (not crashed)
        assert mock_client.return_value.__aenter__.return_value.put.call_count >= 1

        await stop_keepalive(handle)


@pytest.mark.asyncio
async def test_keepalive_reregistration_posts_full_service_info():
    """Re-registration after a 404 sends the original service info, not an empty object."""
    info = CustomServiceInfo(id="test-service", display_name="Test Service", version="2.1.0", team="analytics")
    registration_config = RegistrationConfig(
        orchestrator_url="http://orchestrator:9000/services/$register",
        host="test-service",
        port=8000,
        info=info,
        max_retries=1,
        retry_delay=0.0,
        timeout=1.0,
    )

    posted_bodies: list[dict] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        """Answer pings with 404 and record registration POST bodies."""
        if request.method == "PUT":
            return httpx.Response(404, json={"detail": "not found"})
        posted_bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"ping_url": "http://orchestrator:9000/services/test-service/$ping", "ttl_seconds": 30},
        )

    transport = httpx.MockTransport(handle_request)
    original_client = httpx.AsyncClient

    def make_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        """Build an AsyncClient wired to the mock transport."""
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)  # type: ignore[arg-type]

    with patch("httpx.AsyncClient", make_client):
        handle = await start_keepalive(
            ping_url="http://orchestrator:9000/services/test-service/$ping",
            service_id="test-service",
            interval=0.01,
            timeout=1.0,
            registration_config=registration_config,
            re_register_grace_period=0.01,
        )

        for _ in range(50):
            if posted_bodies:
                break
            await asyncio.sleep(0.02)

        await stop_keepalive(handle)

    assert posted_bodies, "re-registration never POSTed to the orchestrator"
    body = posted_bodies[0]
    assert body["id"] == "test-service"
    assert body["info"]["id"] == "test-service"
    assert body["info"]["display_name"] == "Test Service"
    assert body["info"]["version"] == "2.1.0"
    assert body["info"]["team"] == "analytics"


def test_registration_config_dump_preserves_subclass_fields():
    """RegistrationConfig serializes the concrete info subclass, not the BaseModel view."""
    config = RegistrationConfig(
        info=CustomServiceInfo(id="test-service", display_name="Test Service", team="analytics"),
    )
    assert config.model_dump()["info"]["id"] == "test-service"
    assert config.model_dump()["info"]["team"] == "analytics"
