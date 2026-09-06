"""Tests for FastAPI middleware and error handlers."""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from servicekit.api.middleware import (
    add_error_handlers,
    add_logging_middleware,
    database_error_handler,
    validation_error_handler,
)
from servicekit.exceptions import ConflictError
from servicekit.logging import configure_logging


class SampleModel(BaseModel):
    """Sample Pydantic model for validation tests."""

    name: str
    age: int


@pytest.fixture
def app_with_handlers() -> FastAPI:
    """Create a FastAPI app with error handlers registered."""
    app = FastAPI()
    add_error_handlers(app)

    @app.get("/db-error")
    async def trigger_db_error() -> None:
        raise SQLAlchemyError("Database connection failed")

    @app.get("/db-error-with-parameters")
    async def trigger_db_error_with_parameters() -> None:
        raise OperationalError("SELECT secret FROM t WHERE p = ?", ("hunter2",), Exception("boom"))

    @app.get("/integrity-error")
    async def trigger_integrity_error() -> None:
        raise IntegrityError("INSERT INTO t (p) VALUES (?)", ("hunter2",), Exception("duplicate key"))

    @app.get("/integrity-error-foreign-key")
    async def trigger_foreign_key_error() -> None:
        raise IntegrityError(
            "INSERT INTO t (parent_id) VALUES (?)",
            ("hunter2",),
            Exception("FOREIGN KEY constraint failed"),
        )

    @app.get("/integrity-error-unique")
    async def trigger_unique_error() -> None:
        raise IntegrityError(
            "INSERT INTO t (id) VALUES (?)",
            ("hunter2",),
            Exception("UNIQUE constraint failed: t.id"),
        )

    @app.get("/validation-error")
    async def trigger_validation_error() -> None:
        raise ValidationError.from_exception_data(
            "SampleModel",
            [
                {
                    "type": "missing",
                    "loc": ("name",),
                    "input": {},
                }
            ],
        )

    return app


def test_database_error_handler_returns_500(app_with_handlers: FastAPI) -> None:
    """Test that database errors return 500 status with proper error message."""
    client = TestClient(app_with_handlers)

    response = client.get("/db-error")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    payload = response.json()
    assert payload["detail"] == "A database error occurred"
    assert payload["trace_id"]
    assert "Database connection failed" not in response.text


def test_database_error_handler_hides_sql_and_parameters(app_with_handlers: FastAPI) -> None:
    """Test that SQL statements and bound parameters never reach the response body."""
    client = TestClient(app_with_handlers)

    response = client.get("/db-error-with-parameters")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "hunter2" not in response.text
    assert "SELECT" not in response.text
    payload = response.json()
    assert payload["detail"] == "A database error occurred"
    assert payload["trace_id"]


def test_database_error_handler_maps_integrity_error_to_409(app_with_handlers: FastAPI) -> None:
    """Test that integrity errors are reported as conflicts."""
    client = TestClient(app_with_handlers)

    response = client.get("/integrity-error")

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    payload = response.json()
    assert payload["title"] == "Conflict"
    assert payload["detail"] == "The request conflicts with existing data"
    assert payload["trace_id"]
    assert "hunter2" not in response.text


def test_database_error_handler_classifies_foreign_key_violation(app_with_handlers: FastAPI) -> None:
    """Test that a foreign key violation is classified without leaking SQL."""
    client = TestClient(app_with_handlers)

    response = client.get("/integrity-error-foreign-key")

    assert response.status_code == 409
    payload = response.json()
    assert payload["constraint"] == "foreign_key"
    assert payload["detail"] == "The request conflicts with existing data"
    assert "hunter2" not in response.text
    assert "INSERT" not in response.text


def test_database_error_handler_classifies_unique_violation(app_with_handlers: FastAPI) -> None:
    """Test that a unique violation is classified without leaking SQL."""
    client = TestClient(app_with_handlers)

    response = client.get("/integrity-error-unique")

    assert response.status_code == 409
    payload = response.json()
    assert payload["constraint"] == "unique"
    assert "hunter2" not in response.text


def test_database_error_handler_omits_unknown_constraint(app_with_handlers: FastAPI) -> None:
    """Test that an unrecognized integrity error carries no constraint extension."""
    client = TestClient(app_with_handlers)

    response = client.get("/integrity-error")

    assert response.status_code == 409
    assert "constraint" not in response.json()


def test_validation_error_handler_returns_422(app_with_handlers: FastAPI) -> None:
    """Test that validation errors return 422 status with structured error details."""
    client = TestClient(app_with_handlers)

    response = client.get("/validation-error")

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    payload = response.json()
    assert payload["detail"] == "Request validation failed"
    assert isinstance(payload["errors"], list)
    assert payload["errors"][0]["type"] == "missing"
    assert payload["errors"][0]["loc"] == ["name"]


async def test_database_error_handler_direct() -> None:
    """Test database_error_handler directly without FastAPI context."""

    class MockURL:
        """Mock URL object."""

        path = "/test"

        def __str__(self) -> str:
            """Return the full mock URL."""
            return "http://testserver/test"

    class MockRequest:
        """Mock request object."""

        url = MockURL()

    exc = SQLAlchemyError("Test error")
    response = await database_error_handler(MockRequest(), exc)  # type: ignore

    assert response.status_code == 500
    assert b"Test error" not in response.body
    assert b"A database error occurred" in response.body


async def test_validation_error_handler_direct() -> None:
    """Test validation_error_handler directly without FastAPI context."""

    class MockURL:
        """Mock URL object."""

        path = "/test"

        def __str__(self) -> str:
            """Return the full mock URL."""
            return "http://testserver/test"

    class MockRequest:
        """Mock request object."""

        url = MockURL()

    exc = ValidationError.from_exception_data(
        "TestModel",
        [
            {
                "type": "missing",
                "loc": ("field",),
                "input": {},
            }
        ],
    )
    response = await validation_error_handler(MockRequest(), exc)  # type: ignore

    assert response.status_code == 422
    assert b"Request validation failed" in response.body


def test_logging_configuration_console() -> None:
    """Test that logging can be configured for console output."""
    os.environ["LOG_FORMAT"] = "console"
    os.environ["LOG_LEVEL"] = "INFO"

    # Should not raise
    configure_logging()


def test_logging_configuration_json() -> None:
    """Test that logging can be configured for JSON output."""
    os.environ["LOG_FORMAT"] = "json"
    os.environ["LOG_LEVEL"] = "DEBUG"

    # Should not raise
    configure_logging()


def test_request_logging_middleware_adds_request_id() -> None:
    """Test that RequestLoggingMiddleware adds request_id to request state and response headers."""
    app = FastAPI()
    add_logging_middleware(app)

    @app.get("/test")
    async def test_endpoint(request: Request) -> dict:
        # Request ID should be accessible in request state
        request_id = getattr(request.state, "request_id", None)
        return {"request_id": request_id}

    client = TestClient(app)
    response = client.get("/test")

    assert response.status_code == 200
    payload = response.json()

    # Request ID should be in response body
    assert "request_id" in payload
    assert payload["request_id"] is not None
    assert len(payload["request_id"]) == 26  # ULID length

    # Request ID should be in response headers
    assert "X-Request-ID" in response.headers
    assert response.headers["X-Request-ID"] == payload["request_id"]


def test_request_logging_middleware_unique_request_ids() -> None:
    """Test that each request gets a unique request_id."""
    app = FastAPI()
    add_logging_middleware(app)

    @app.get("/test")
    async def test_endpoint(request: Request) -> dict:
        return {"request_id": request.state.request_id}

    client = TestClient(app)
    response1 = client.get("/test")
    response2 = client.get("/test")

    assert response1.status_code == 200
    assert response2.status_code == 200

    request_id1 = response1.json()["request_id"]
    request_id2 = response2.json()["request_id"]

    # Request IDs should be different
    assert request_id1 != request_id2


def test_request_logging_middleware_handles_exceptions() -> None:
    """Test that RequestLoggingMiddleware properly handles and re-raises exceptions."""
    app = FastAPI()
    add_logging_middleware(app)

    @app.get("/error")
    async def error_endpoint() -> dict:
        raise ValueError("Test exception from endpoint")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/error")

    # Exception should result in 500 error
    assert response.status_code == 500


def test_request_logging_middleware_logs_on_exception() -> None:
    """Test that middleware logs errors when exceptions occur during request processing."""
    app = FastAPI()
    add_logging_middleware(app)

    @app.get("/test-error")
    async def error_endpoint() -> None:
        raise RuntimeError("Simulated error")

    client = TestClient(app, raise_server_exceptions=False)

    # This should trigger the exception handler in middleware
    response = client.get("/test-error")

    # Should return 500 as the exception is unhandled
    assert response.status_code == 500


def test_servicekit_exception_handler_preserves_extensions() -> None:
    """Test that custom exception extensions appear in the Problem Details body."""
    app = FastAPI()
    add_error_handlers(app)

    @app.get("/conflict")
    async def trigger_conflict() -> None:
        raise ConflictError("dup", entity_id="test-id", meta={"a": 1})

    client = TestClient(app)
    response = client.get("/conflict")

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    payload = response.json()
    assert payload["entity_id"] == "test-id"
    assert payload["meta"] == {"a": 1}


def test_servicekit_exception_handler_drops_reserved_extensions() -> None:
    """Test that extensions colliding with Problem Details fields are dropped instead of failing."""
    app = FastAPI()
    add_error_handlers(app)

    @app.get("/reserved")
    async def trigger_reserved() -> None:
        error = ConflictError("dup", entity_id="test-id")
        error.extensions["status"] = 999
        raise error

    client = TestClient(app)
    response = client.get("/reserved")

    assert response.status_code == 409
    payload = response.json()
    assert payload["status"] == 409
    assert payload["entity_id"] == "test-id"
