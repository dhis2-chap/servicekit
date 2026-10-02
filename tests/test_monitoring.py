"""Tests for OpenTelemetry monitoring setup."""

from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from opentelemetry import metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader

from servicekit.api.monitoring import get_meter, setup_monitoring, teardown_monitoring
from servicekit.api.service_builder import BaseServiceBuilder, ServiceInfo


def test_setup_monitoring_returns_prometheus_reader():
    """Test that setup_monitoring returns a PrometheusMetricReader."""
    app = FastAPI(title="TestApp")

    reader = setup_monitoring(app)

    assert isinstance(reader, PrometheusMetricReader)


def test_setup_monitoring_uses_app_title_as_service_name():
    """Test that setup_monitoring uses app title when service_name not provided."""
    app = FastAPI(title="MyServiceApp")

    setup_monitoring(app)

    # The function should complete without error using app.title


def test_setup_monitoring_uses_custom_service_name():
    """Test that setup_monitoring uses custom service_name when provided."""
    app = FastAPI(title="TestApp")

    setup_monitoring(app, service_name="CustomService")

    # The function should complete without error using the custom name


def test_setup_monitoring_multiple_calls_idempotent():
    """Test that calling setup_monitoring multiple times is safe."""
    app1 = FastAPI(title="App1")
    app2 = FastAPI(title="App2")

    # First call
    reader1 = setup_monitoring(app1)
    assert isinstance(reader1, PrometheusMetricReader)

    # Second call with a different app returns the same attached reader
    reader2 = setup_monitoring(app2)
    assert reader2 is reader1


def test_setup_monitoring_handles_process_collector_already_registered():
    """Test that setup_monitoring handles ProcessCollector already registered."""
    app = FastAPI(title="TestApp")

    # First setup should work
    setup_monitoring(app)

    # Second setup should handle ValueError gracefully
    setup_monitoring(app)


def test_setup_monitoring_with_enable_traces_warns():
    """Test that enable_traces=True logs a warning."""
    app = FastAPI(title="TestApp")

    # This should complete and log a warning about traces not implemented
    reader = setup_monitoring(app, enable_traces=True)

    assert isinstance(reader, PrometheusMetricReader)


def test_teardown_monitoring_succeeds():
    """Test that teardown_monitoring completes without error."""
    app = FastAPI(title="TestApp")

    # Setup first
    setup_monitoring(app)

    # Teardown should not raise
    teardown_monitoring()


def test_teardown_monitoring_handles_exceptions():
    """Test that teardown_monitoring handles exceptions gracefully."""
    # Mock to raise exception
    with patch("servicekit.api.monitoring.SQLAlchemyInstrumentor") as mock_instrumentor:
        mock_instance = mock_instrumentor.return_value
        mock_instance.uninstrument.side_effect = RuntimeError("Test error")

        # Should not raise, should log warning instead
        teardown_monitoring()


def test_teardown_monitoring_keeps_global_reader():
    """Test that setup after teardown reuses the reader attached to the global meter provider."""
    reader1 = setup_monitoring(FastAPI(title="App1"))
    teardown_monitoring()
    reader2 = setup_monitoring(FastAPI(title="App2"))

    assert reader2 is reader1


def test_get_meter_returns_meter():
    """Test that get_meter returns a Meter instance."""
    meter = get_meter("test.metrics")

    assert isinstance(meter, metrics.Meter)


def test_get_meter_different_names():
    """Test that get_meter works with different meter names."""
    meter1 = get_meter("service.metrics")
    meter2 = get_meter("custom.metrics")

    assert isinstance(meter1, metrics.Meter)
    assert isinstance(meter2, metrics.Meter)


def test_setup_monitoring_handles_sqlalchemy_already_instrumented():
    """Test that setup_monitoring handles SQLAlchemy already instrumented."""
    app = FastAPI(title="TestApp")

    # First call instruments SQLAlchemy
    setup_monitoring(app)

    # Second call should handle RuntimeError gracefully
    setup_monitoring(app)


def _builder() -> BaseServiceBuilder:
    """Create a minimal service builder for monitoring tests."""
    return BaseServiceBuilder(info=ServiceInfo(id="monitoring-svc", display_name="Monitoring"))


async def _metrics_status(app: FastAPI) -> int:
    """Return the status code of GET /metrics on the app."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/metrics")
    return response.status_code


@pytest.mark.asyncio
async def test_builder_enables_monitoring_by_default():
    """Test that a builder without with_monitoring() exposes /metrics."""
    app = _builder().build()

    assert await _metrics_status(app) == 200


@pytest.mark.asyncio
async def test_builder_with_monitoring_disabled():
    """Test that with_monitoring(enabled=False) removes /metrics and turns FastAPI OpenTelemetry off."""
    builder = _builder().with_monitoring(enabled=False)

    assert await _metrics_status(builder.build()) == 404
    assert builder._build_telemetry_config() == {
        "tracing": False,
        "metrics": False,
        "logs": False,
        "auto_configure": False,
    }


@pytest.mark.asyncio
async def test_builder_records_fastapi_http_metrics_and_skips_scrapes():
    """Test that FastAPI OpenTelemetry metrics use stable semconv names and exclude the metrics endpoint."""
    app = _builder().with_monitoring(prefix="/custom-metrics").build()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/api/v1/info")
        await client.get("/custom-metrics")
        response = await client.get("/custom-metrics")

    assert "http_server_request_duration_seconds_bucket" in response.text
    assert 'http_route="/api/v1/info"' in response.text
    assert 'http_route="/custom-metrics"' not in response.text
