"""OpenTelemetry monitoring setup with auto-instrumentation."""

from fastapi import FastAPI
from opentelemetry import metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
from prometheus_client import REGISTRY, ProcessCollector

from servicekit.logging import get_logger

logger = get_logger(__name__)

# Global state to track instrumentation
_meter_provider_initialized = False
_sqlalchemy_instrumented = False
_process_collector_registered = False

# The single reader attached to the global MeterProvider, shared by every app in the process
_metric_reader: PrometheusMetricReader | None = None


def setup_monitoring(
    app: FastAPI,
    *,
    service_name: str | None = None,
    enable_traces: bool = False,
) -> PrometheusMetricReader:
    """Setup OpenTelemetry with FastAPI and SQLAlchemy auto-instrumentation."""
    global _meter_provider_initialized, _sqlalchemy_instrumented, _process_collector_registered, _metric_reader

    # Use app title as service name if not provided
    service_name = service_name or app.title

    # Create resource with service name
    resource = Resource.create({"service.name": service_name})

    # Setup Prometheus metrics exporter - only once globally, reusing the attached reader
    if not _meter_provider_initialized or _metric_reader is None:
        _metric_reader = PrometheusMetricReader()
        provider = MeterProvider(resource=resource, metric_readers=[_metric_reader])
        metrics.set_meter_provider(provider)
        _meter_provider_initialized = True
    reader = _metric_reader

    # Register process collector for CPU, memory, and Python runtime metrics
    if not _process_collector_registered:
        try:
            ProcessCollector(registry=REGISTRY)
            _process_collector_registered = True
        except ValueError:
            # Already registered
            pass

    # Auto-instrument FastAPI - check if already instrumented
    instrumentor = FastAPIInstrumentor()
    if not instrumentor.is_instrumented_by_opentelemetry:
        instrumentor.instrument_app(app)

    # Auto-instrument SQLAlchemy - only once globally
    if not _sqlalchemy_instrumented:
        try:
            SQLAlchemyInstrumentor().instrument()
            _sqlalchemy_instrumented = True
        except RuntimeError:
            # Already instrumented
            pass

    logger.info(
        "monitoring.enabled",
        service_name=service_name,
        fastapi_instrumented=True,
        sqlalchemy_instrumented=True,
        process_metrics=True,
    )

    if enable_traces:
        logger.warning(
            "monitoring.traces_not_implemented",
            message="Distributed tracing is not yet implemented",
        )

    return reader


def teardown_monitoring() -> None:
    """Teardown OpenTelemetry instrumentation and reset module state."""
    global _meter_provider_initialized, _sqlalchemy_instrumented, _process_collector_registered, _metric_reader

    _meter_provider_initialized = False
    _sqlalchemy_instrumented = False
    _process_collector_registered = False
    _metric_reader = None

    try:
        # Uninstrument FastAPI
        FastAPIInstrumentor().uninstrument()

        # Uninstrument SQLAlchemy
        SQLAlchemyInstrumentor().uninstrument()

        logger.info("monitoring.disabled")
    except Exception as e:
        logger.warning("monitoring.teardown_failed", error=str(e))


def get_meter(name: str) -> metrics.Meter:
    """Get a meter for custom metrics."""
    return metrics.get_meter(name)
