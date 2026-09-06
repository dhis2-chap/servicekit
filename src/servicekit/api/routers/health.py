"""Health check router."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from enum import StrEnum

from fastapi import Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..router import Router
from ..sse import SSE_HEADERS, format_sse_model_event


class HealthState(StrEnum):
    """Health state enumeration for health checks."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


HealthCheck = Callable[[], Awaitable[tuple[HealthState, str | None]]]


class CheckResult(BaseModel):
    """Result of an individual health check."""

    state: HealthState = Field(description="Health state of this check")
    message: str | None = Field(default=None, description="Optional message or error detail")


class HealthStatus(BaseModel):
    """Overall health status response."""

    status: HealthState = Field(description="Overall service health indicator")
    checks: dict[str, CheckResult] | None = Field(
        default=None, description="Individual health check results (if checks are configured)"
    )


class HealthRouter(Router):
    """Health check router for service health monitoring."""

    default_response_model_exclude_none = True

    def __init__(
        self,
        prefix: str,
        tags: list[str],
        checks: dict[str, HealthCheck] | None = None,
        **kwargs: object,
    ) -> None:
        """Initialize health router with optional health checks."""
        self.checks = checks or {}
        super().__init__(prefix=prefix, tags=tags, **kwargs)

    def _register_routes(self) -> None:
        """Register health check endpoint."""
        checks = self.checks

        async def run_health_checks() -> HealthStatus:
            """Run all health checks and aggregate results."""
            if not checks:
                return HealthStatus(status=HealthState.HEALTHY)

            check_results: dict[str, CheckResult] = {}
            overall_state = HealthState.HEALTHY

            for name, check_fn in checks.items():
                try:
                    state, message = await check_fn()
                    check_results[name] = CheckResult(state=state, message=message)

                    if state == HealthState.UNHEALTHY:
                        overall_state = HealthState.UNHEALTHY
                    elif state == HealthState.DEGRADED and overall_state == HealthState.HEALTHY:
                        overall_state = HealthState.DEGRADED

                except Exception as e:
                    check_results[name] = CheckResult(state=HealthState.UNHEALTHY, message=f"Check failed: {str(e)}")
                    overall_state = HealthState.UNHEALTHY

            return HealthStatus(status=overall_state, checks=check_results)

        @self.router.get(
            "",
            summary="Health check",
            response_model=HealthStatus,
            responses={503: {"model": HealthStatus, "description": "Service is unhealthy"}},
            response_model_exclude_none=self.default_response_model_exclude_none,
        )
        async def health_check(response: Response) -> HealthStatus:
            """Return aggregate health status, with 503 when the service is unhealthy."""
            health_status = await run_health_checks()
            if health_status.status == HealthState.UNHEALTHY:
                response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return health_status

        @self.router.get(
            "/$stream",
            summary="Stream health status updates via SSE",
            description="Real-time Server-Sent Events stream of health status at regular intervals",
        )
        async def stream_health_status(poll_interval: float = 1.0) -> StreamingResponse:
            """Stream real-time health status updates using Server-Sent Events."""

            async def event_stream() -> AsyncGenerator[bytes, None]:
                while True:
                    status = await run_health_checks()
                    yield format_sse_model_event(status, exclude_none=self.default_response_model_exclude_none)
                    await asyncio.sleep(poll_interval)

            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers=SSE_HEADERS,
            )
