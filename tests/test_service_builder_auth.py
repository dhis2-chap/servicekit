"""Tests for BaseServiceBuilder.with_auth unauthenticated path handling."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from servicekit.api import BaseServiceBuilder, ServiceInfo

DEFAULT_UNAUTHENTICATED_PATHS = ["/", "/docs", "/redoc", "/openapi.json", "/health"]


def build_app(unauthenticated_paths: list[str] | None) -> FastAPI:
    """Build a service with API key auth and an optional unauthenticated path list."""
    info = ServiceInfo(id="test-service", display_name="Test Service")
    builder = BaseServiceBuilder(info=info).with_health()
    if unauthenticated_paths is None:
        builder = builder.with_auth(api_keys=["test-key"])
    else:
        builder = builder.with_auth(api_keys=["test-key"], unauthenticated_paths=unauthenticated_paths)
    return builder.build()


@pytest.mark.parametrize("path", DEFAULT_UNAUTHENTICATED_PATHS)
async def test_empty_unauthenticated_paths_requires_key(path: str) -> None:
    """Test that an empty unauthenticated_paths list protects the default public paths."""
    app = build_app([])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path)

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize("path", DEFAULT_UNAUTHENTICATED_PATHS)
async def test_empty_unauthenticated_paths_allows_valid_key(path: str) -> None:
    """Test that a valid API key passes authentication for every default public path."""
    app = build_app([])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path, headers={"X-API-Key": "test-key"})

    # "/" has no route registered by default, so authentication succeeds and routing returns 404.
    assert response.status_code == (404 if path == "/" else 200)


@pytest.mark.parametrize("path", DEFAULT_UNAUTHENTICATED_PATHS)
async def test_omitted_unauthenticated_paths_keeps_defaults_public(path: str) -> None:
    """Test that omitting unauthenticated_paths leaves the default paths publicly reachable."""
    app = build_app(None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path)

    assert response.status_code != 401


async def test_explicit_unauthenticated_paths_replace_defaults() -> None:
    """Test that an explicit unauthenticated_paths list replaces the defaults entirely."""
    app = build_app(["/health"])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        health_response = await client.get("/health")
        docs_response = await client.get("/docs")

    assert health_response.status_code == 200
    assert docs_response.status_code == 401
