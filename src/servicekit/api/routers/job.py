"""REST API router for job scheduler (list, get, delete jobs)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from typing import Any

import ulid
from fastapi import Depends, HTTPException, status
from fastapi.responses import Response, StreamingResponse
from pydantic import TypeAdapter

from servicekit.api.router import Router
from servicekit.api.sse import SSE_HEADERS, format_sse_model_event
from servicekit.scheduler import Scheduler
from servicekit.schemas import JobRecord, JobStatus

ULID = ulid.ULID


class JobRouter(Router):
    """REST API router for job scheduler operations."""

    def __init__(
        self,
        prefix: str,
        tags: list[str],
        scheduler_factory: Callable[..., Scheduler],
        **kwargs: object,
    ) -> None:
        """Initialize job router with scheduler factory."""
        self.scheduler_factory = scheduler_factory
        super().__init__(prefix=prefix, tags=tags, **kwargs)

    def _register_routes(self) -> None:
        """Register job management endpoints."""
        scheduler_dependency = Depends(self.scheduler_factory)

        @self.router.get("", summary="List all jobs", response_model=list[JobRecord])
        async def get_jobs(
            scheduler: Scheduler = scheduler_dependency,
            status_filter: JobStatus | None = None,
        ) -> list[JobRecord]:
            jobs = await scheduler.get_all_records()
            if status_filter:
                return [job for job in jobs if job.status == status_filter]
            return jobs

        @self.router.get("/$schema", summary="Get jobs list schema", response_model=dict[str, Any])
        async def get_jobs_schema() -> dict[str, Any]:
            """Get JSON schema for jobs list response."""
            return TypeAdapter(list[JobRecord]).json_schema()

        @self.router.get("/{job_id}", summary="Get job by ID", response_model=JobRecord)
        async def get_job(
            job_id: str,
            scheduler: Scheduler = scheduler_dependency,
        ) -> JobRecord:
            try:
                ulid_id = ULID.from_str(job_id)
                return await scheduler.get_record(ulid_id)
            except (ValueError, KeyError):
                raise HTTPException(status_code=404, detail="Job not found")

        @self.router.delete("/{job_id}", summary="Cancel and delete job", status_code=status.HTTP_204_NO_CONTENT)
        async def delete_job(
            job_id: str,
            scheduler: Scheduler = scheduler_dependency,
        ) -> Response:
            try:
                ulid_id = ULID.from_str(job_id)
                await scheduler.delete(ulid_id)
                return Response(status_code=status.HTTP_204_NO_CONTENT)
            except (ValueError, KeyError):
                raise HTTPException(status_code=404, detail="Job not found")

        @self.router.get(
            "/{job_id}/$stream",
            summary="Stream job status updates via SSE",
            description="Real-time Server-Sent Events stream of job status changes until terminal state",
        )
        async def stream_job_status(
            job_id: str,
            scheduler: Scheduler = scheduler_dependency,
            poll_interval: float = 0.5,
        ) -> StreamingResponse:
            """Stream real-time job status updates using Server-Sent Events."""
            # Validate job_id format
            try:
                ulid_id = ULID.from_str(job_id)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid job ID format")

            # Check job exists before starting stream
            try:
                await scheduler.get_record(ulid_id)
            except KeyError:
                raise HTTPException(status_code=404, detail="Job not found")

            # SSE event generator
            async def event_stream() -> AsyncGenerator[bytes, None]:
                terminal_states = {"completed", "failed", "canceled"}

                while True:
                    try:
                        record = await scheduler.get_record(ulid_id)
                        # Format as SSE event
                        yield format_sse_model_event(record)

                        # Stop streaming if job reached terminal state
                        if record.status in terminal_states:
                            break

                    except KeyError:
                        # Job was deleted - send final event and close
                        yield b'data: {"status": "deleted"}\n\n'
                        break

                    await asyncio.sleep(poll_interval)

            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers=SSE_HEADERS,
            )
