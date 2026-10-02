"""Monitoring example with OpenTelemetry and Prometheus metrics."""

from servicekit.api import BaseServiceBuilder, ServiceInfo

app = (
    BaseServiceBuilder(
        info=ServiceInfo(
            id="monitoring-example",
            display_name="Monitoring Example Service",
            version="1.0.0",
            description="Demonstrates automatic instrumentation of FastAPI and SQLAlchemy "
            "with metrics exposed at /metrics endpoint. Includes health check endpoint.",
        )
    )
    .with_database()
    .with_health()
    .with_system()
    .with_monitoring(service_name="monitoring-example")  # Monitoring is on by default; this sets the service name
    .with_logging()
    .with_landing_page()
    .build()
)


if __name__ == "__main__":
    from servicekit.api import run_app

    run_app(app)
