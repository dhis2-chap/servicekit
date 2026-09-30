"""Tests for API utilities."""

import os
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from servicekit.api.utilities import build_location_url, run_app


@pytest.fixture(autouse=True)
def _isolate_port_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Restore PORT and SERVICEKIT_PORT after each test, since run_app exports them."""
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("SERVICEKIT_PORT", raising=False)


def test_build_location_url() -> None:
    """Test build_location_url constructs full URLs correctly."""
    app = FastAPI()

    @app.get("/test")
    def test_endpoint(request: Request) -> dict[str, str]:
        url = build_location_url(request, "/api/v1/items/123")
        return {"url": url}

    client = TestClient(app)
    response = client.get("/test")

    assert response.status_code == 200
    data = response.json()
    assert data["url"] == "http://testserver/api/v1/items/123"


def test_build_location_url_with_custom_base() -> None:
    """Test build_location_url with custom base URL."""
    app = FastAPI()

    @app.get("/test")
    def test_endpoint(request: Request) -> dict[str, str]:
        url = build_location_url(request, "/resources/456")
        return {"url": url}

    client = TestClient(app, base_url="https://example.com")
    response = client.get("/test")

    assert response.status_code == 200
    data = response.json()
    assert data["url"] == "https://example.com/resources/456"


def test_build_location_url_preserves_path_slashes() -> None:
    """Test build_location_url preserves leading slashes in paths."""
    app = FastAPI()

    @app.get("/test")
    def test_endpoint(request: Request) -> dict[str, str]:
        url1 = build_location_url(request, "/api/v1/items")
        url2 = build_location_url(request, "/api/v1/items/")
        return {"url1": url1, "url2": url2}

    client = TestClient(app)
    response = client.get("/test")

    assert response.status_code == 200
    data = response.json()
    assert data["url1"] == "http://testserver/api/v1/items"
    assert data["url2"] == "http://testserver/api/v1/items/"


def test_run_app_with_defaults() -> None:
    """Test run_app uses default values."""
    mock_run = Mock()
    mock_configure = Mock()

    with patch("uvicorn.run", mock_run):
        with patch("servicekit.logging.configure_logging", mock_configure):
            run_app("test:app")

    # Check logging was configured
    mock_configure.assert_called_once()

    # Check uvicorn.run was called
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[0] == "test:app"
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8000
    assert kwargs["workers"] == 1
    assert kwargs["reload"] is True  # string enables reload
    assert kwargs["log_level"] == "info"
    assert kwargs["log_config"] is None


def test_run_app_with_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test run_app reads from environment variables."""
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "3000")
    monkeypatch.setenv("WORKERS", "4")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    mock_run = Mock()
    mock_configure = Mock()

    with patch("uvicorn.run", mock_run):
        with patch("servicekit.logging.configure_logging", mock_configure):
            run_app("test:app")

    _, kwargs = mock_run.call_args
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 3000
    assert kwargs["workers"] == 4
    assert kwargs["log_level"] == "debug"
    assert kwargs["reload"] is False  # workers > 1 disables reload


def test_run_app_reload_logic_with_string() -> None:
    """Test run_app enables reload for string app path."""
    mock_run = Mock()
    mock_configure = Mock()

    with patch("uvicorn.run", mock_run):
        with patch("servicekit.logging.configure_logging", mock_configure):
            run_app("test:app")

    assert mock_run.call_args[1]["reload"] is True


def test_run_app_reload_logic_with_instance() -> None:
    """Test run_app disables reload for app instance."""
    mock_run = Mock()
    mock_configure = Mock()

    with patch("uvicorn.run", mock_run):
        with patch("servicekit.logging.configure_logging", mock_configure):
            app = FastAPI()
            run_app(app)

    assert mock_run.call_args[1]["reload"] is False


def test_run_app_with_explicit_params(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test run_app with explicit parameters overrides defaults and env vars."""
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "9000")

    mock_run = Mock()
    mock_configure = Mock()

    with patch("uvicorn.run", mock_run):
        with patch("servicekit.logging.configure_logging", mock_configure):
            run_app("test:app", host="localhost", port=5000, workers=2, log_level="warning")

    _, kwargs = mock_run.call_args
    assert kwargs["host"] == "localhost"
    assert kwargs["port"] == 5000
    assert kwargs["workers"] == 2
    assert kwargs["log_level"] == "warning"


def test_run_app_seeds_servicekit_port_from_resolved_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test run_app exports the resolved bind port as SERVICEKIT_PORT for registration."""
    monkeypatch.delenv("SERVICEKIT_PORT", raising=False)

    mock_run = Mock()
    mock_configure = Mock()

    with patch("uvicorn.run", mock_run):
        with patch("servicekit.logging.configure_logging", mock_configure):
            run_app("test:app", port=9090)

    assert os.environ["SERVICEKIT_PORT"] == "9090"


def test_run_app_seeds_servicekit_port_from_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test run_app exports the default port as SERVICEKIT_PORT when none is given."""
    monkeypatch.delenv("SERVICEKIT_PORT", raising=False)
    monkeypatch.delenv("PORT", raising=False)

    mock_run = Mock()
    mock_configure = Mock()

    with patch("uvicorn.run", mock_run):
        with patch("servicekit.logging.configure_logging", mock_configure):
            run_app("test:app")

    assert os.environ["SERVICEKIT_PORT"] == "8000"


def test_run_app_respects_existing_servicekit_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test run_app leaves an explicitly set SERVICEKIT_PORT untouched (proxy/NAT case)."""
    monkeypatch.setenv("SERVICEKIT_PORT", "443")

    mock_run = Mock()
    mock_configure = Mock()

    with patch("uvicorn.run", mock_run):
        with patch("servicekit.logging.configure_logging", mock_configure):
            run_app("test:app", port=9090)

    assert os.environ["SERVICEKIT_PORT"] == "443"


def test_run_app_exports_bind_port_as_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test run_app exports an explicit bind port as PORT, overriding the environment value."""
    monkeypatch.setenv("PORT", "8000")
    monkeypatch.setenv("SERVICEKIT_PORT", "18701")

    mock_run = Mock()
    mock_configure = Mock()

    with patch("uvicorn.run", mock_run):
        with patch("servicekit.logging.configure_logging", mock_configure):
            run_app("test:app", port=9090)

    assert os.environ["PORT"] == "9090"
    assert os.environ["SERVICEKIT_PORT"] == "18701"


def test_run_app_multiple_workers_disables_reload() -> None:
    """Test run_app disables reload when workers > 1."""
    mock_run = Mock()
    mock_configure = Mock()

    with patch("uvicorn.run", mock_run):
        with patch("servicekit.logging.configure_logging", mock_configure):
            run_app("test:app", workers=4)

    assert mock_run.call_args[1]["reload"] is False


def test_run_app_with_explicit_reload_true() -> None:
    """Test run_app with explicit reload=True is respected unless workers > 1."""
    mock_run = Mock()
    mock_configure = Mock()

    with patch("uvicorn.run", mock_run):
        with patch("servicekit.logging.configure_logging", mock_configure):
            app = FastAPI()
            run_app(app, reload=True, workers=1)

    assert mock_run.call_args[1]["reload"] is True


def test_run_app_with_uvicorn_kwargs() -> None:
    """Test run_app passes additional uvicorn kwargs."""
    mock_run = Mock()
    mock_configure = Mock()

    with patch("uvicorn.run", mock_run):
        with patch("servicekit.logging.configure_logging", mock_configure):
            run_app("test:app", access_log=False, proxy_headers=True)

    kwargs = mock_run.call_args[1]
    assert kwargs["access_log"] is False
    assert kwargs["proxy_headers"] is True
