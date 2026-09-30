"""Utility functions for FastAPI routers and endpoints."""

import os
from typing import Any

from fastapi import Request


def build_location_url(request: Request, path: str) -> str:
    """Build a full URL for the Location header."""
    return f"{request.url.scheme}://{request.url.netloc}{path}"


def run_app(
    app: Any | str,
    *,
    host: str | None = None,
    port: int | None = None,
    workers: int | None = None,
    reload: bool | None = None,
    log_level: str | None = None,
    **uvicorn_kwargs: Any,
) -> None:
    """Run FastAPI app with Uvicorn development server.

    For reload to work, pass a string in "module:app" format.
    App instance disables reload automatically.

    Examples:
    --------
        # Direct execution (reload disabled)
        if __name__ == "__main__":
            run_app(app)

        # With module path (reload enabled)
        run_app("examples.config_api:app")

        # Production: multiple workers
        run_app(app, workers=4)

    Args:
        app: FastAPI app instance OR string "module:app" path
        host: Server host (default: "127.0.0.1", env: HOST)
        port: Server port (default: 8000, env: PORT). The resolved value is
            exported as PORT so service registration probes the port uvicorn
            binds, and as SERVICEKIT_PORT (unless already set) so it is also
            the advertised port by default.
        workers: Number of worker processes (default: 1, env: WORKERS)
        reload: Enable auto-reload (default: True for string, False for instance)
        log_level: Logging level (default: from LOG_LEVEL env var or "info")
        **uvicorn_kwargs: Additional uvicorn.run() arguments
    """
    import uvicorn

    # Configure structured logging before uvicorn starts
    from servicekit.logging import configure_logging

    configure_logging()

    # Read from environment variables with defaults
    resolved_host: str = host if host is not None else os.getenv("HOST", "127.0.0.1")
    resolved_port: int = port if port is not None else int(os.getenv("PORT", "8000"))
    resolved_workers: int = workers if workers is not None else int(os.getenv("WORKERS", "1"))
    resolved_log_level: str = log_level if log_level is not None else os.getenv("LOG_LEVEL", "info").lower()

    # Auto-detect reload behavior if not specified
    if reload is None:
        reload = isinstance(app, str)  # Enable reload for string paths, disable for instances

    # Auto-reload is incompatible with multiple workers
    if resolved_workers > 1 and reload:
        reload = False

    # Make the bind port visible to service registration, which runs inside the
    # app lifespan with no knowledge of where uvicorn actually bound. PORT is the
    # local port its readiness probe tries first. SERVICEKIT_PORT is the port
    # advertised to the orchestrator; setdefault means an explicitly set value
    # (e.g. a published host port or a port behind a proxy) still wins.
    os.environ["PORT"] = str(resolved_port)
    os.environ.setdefault("SERVICEKIT_PORT", str(resolved_port))

    uvicorn.run(
        app,
        host=resolved_host,
        port=resolved_port,
        workers=resolved_workers,
        reload=reload,
        log_level=resolved_log_level,
        log_config=None,  # Disable uvicorn's default logging config
        **uvicorn_kwargs,
    )
