"""Tests for job router endpoints."""

import asyncio
import json
from collections.abc import AsyncGenerator

import pytest
import ulid
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from servicekit.api import BaseServiceBuilder, JobOptions, ServiceInfo
from servicekit.scheduler import InMemoryScheduler, Scheduler

ULID = ulid.ULID


@pytest.fixture
async def app() -> AsyncGenerator[FastAPI, None]:
    """Create FastAPI app with job router and trigger lifespan."""
    info = ServiceInfo(id="test-service", display_name="Test Service")
    app_instance = BaseServiceBuilder(info=info).with_jobs().build()

    # Manually trigger lifespan
    async with app_instance.router.lifespan_context(app_instance):
        yield app_instance


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Create async test client."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", follow_redirects=True) as ac:
        yield ac


class TestJobRouter:
    """Test job router endpoints."""

    @pytest.mark.asyncio
    async def test_get_jobs_empty(self, client: AsyncClient):
        """Test GET /api/v1/jobs returns empty list initially."""
        response = await client.get("/api/v1/jobs")
        assert response.status_code == 200
        jobs = response.json()
        assert jobs == []

    @pytest.mark.asyncio
    async def test_get_jobs_after_adding(self, client: AsyncClient, app: FastAPI):
        """Test GET /api/v1/jobs returns jobs after adding them."""
        # Get scheduler and add a job
        scheduler = app.state.scheduler

        async def task():
            return "result"

        job_id = await scheduler.add_job(task)
        await scheduler.wait(job_id)

        # Get jobs
        response = await client.get("/api/v1/jobs")
        assert response.status_code == 200
        jobs = response.json()
        assert len(jobs) == 1
        assert jobs[0]["id"] == str(job_id)
        assert jobs[0]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_get_jobs_filtered_by_status(self, client: AsyncClient, app: FastAPI):
        """Test GET /api/v1/jobs?status_filter=completed filters jobs."""
        scheduler = app.state.scheduler

        async def quick_task():
            return "done"

        async def slow_task():
            await asyncio.sleep(10)
            return "never"

        # Add completed and running jobs
        completed_id = await scheduler.add_job(quick_task)
        await scheduler.wait(completed_id)

        running_id = await scheduler.add_job(slow_task)
        await asyncio.sleep(0.01)  # Let it start

        # Filter by completed
        response = await client.get("/api/v1/jobs?status_filter=completed")
        assert response.status_code == 200
        jobs = response.json()
        assert len(jobs) == 1
        assert jobs[0]["id"] == str(completed_id)

        # Filter by running
        response = await client.get("/api/v1/jobs?status_filter=running")
        assert response.status_code == 200
        jobs = response.json()
        assert len(jobs) == 1
        assert jobs[0]["id"] == str(running_id)

        # Cleanup
        await scheduler.cancel(running_id)

    @pytest.mark.asyncio
    async def test_get_job_by_id(self, client: AsyncClient, app: FastAPI):
        """Test GET /api/v1/jobs/{id} returns job record."""
        scheduler = app.state.scheduler

        async def task():
            return "result"

        job_id = await scheduler.add_job(task)
        await scheduler.wait(job_id)

        # Get specific job
        response = await client.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        assert job["id"] == str(job_id)
        assert job["status"] == "completed"
        assert job["submitted_at"] is not None
        assert job["started_at"] is not None
        assert job["finished_at"] is not None

    @pytest.mark.asyncio
    async def test_get_job_not_found(self, client: AsyncClient):
        """Test GET /api/v1/jobs/{id} returns an RFC 9457 404 for a non-existent job."""
        fake_id = ULID()
        response = await client.get(f"/api/v1/jobs/{fake_id}")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")
        body = response.json()
        assert body["detail"] == f"Job with id {fake_id} not found"
        assert body["type"] == "urn:servicekit:error:not-found"

    @pytest.mark.asyncio
    async def test_get_job_invalid_ulid(self, client: AsyncClient):
        """Test GET /api/v1/jobs/{id} returns an RFC 9457 400 for an invalid ULID."""
        response = await client.get("/api/v1/jobs/invalid-ulid")
        assert response.status_code == 400
        assert response.headers["content-type"].startswith("application/problem+json")
        body = response.json()
        assert body["detail"] == "Invalid job ID format: invalid-ulid"
        assert body["type"] == "urn:servicekit:error:invalid-ulid"

    @pytest.mark.asyncio
    async def test_delete_job(self, client: AsyncClient, app: FastAPI):
        """Test DELETE /api/v1/jobs/{id} deletes job."""
        scheduler = app.state.scheduler

        async def task():
            return "result"

        job_id = await scheduler.add_job(task)
        await scheduler.wait(job_id)

        # Delete job
        response = await client.delete(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 204
        assert response.text == ""

        # Verify job is gone
        response = await client.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_running_job_cancels_it(self, client: AsyncClient, app: FastAPI):
        """Test DELETE /api/v1/jobs/{id} cancels running job."""
        scheduler = app.state.scheduler

        async def long_task():
            await asyncio.sleep(10)
            return "never"

        job_id = await scheduler.add_job(long_task)
        await asyncio.sleep(0.01)  # Let it start

        # Delete while running
        response = await client.delete(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 204

        # Verify job is gone
        response = await client.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_job_not_found(self, client: AsyncClient):
        """Test DELETE /api/v1/jobs/{id} returns an RFC 9457 404 for a non-existent job."""
        fake_id = ULID()
        response = await client.delete(f"/api/v1/jobs/{fake_id}")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")
        body = response.json()
        assert body["detail"] == f"Job with id {fake_id} not found"
        assert body["type"] == "urn:servicekit:error:not-found"

    @pytest.mark.asyncio
    async def test_failed_job_has_error(self, client: AsyncClient, app: FastAPI):
        """Test failed job includes error traceback."""
        scheduler = app.state.scheduler

        async def failing_task():
            raise ValueError("Something went wrong")

        job_id = await scheduler.add_job(failing_task)

        # Wait for failure
        try:
            await scheduler.wait(job_id)
        except ValueError:
            pass

        # Get job record
        response = await client.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        assert job["status"] == "failed"
        assert job["error"] is not None
        assert "ValueError" in job["error"]
        assert "Something went wrong" in job["error"]

    @pytest.mark.asyncio
    async def test_jobs_sorted_newest_first(self, client: AsyncClient, app: FastAPI):
        """Test GET /api/v1/jobs returns jobs sorted newest first."""
        scheduler = app.state.scheduler

        async def task():
            return "done"

        job_ids = []
        for _ in range(3):
            jid = await scheduler.add_job(task)
            job_ids.append(jid)
            await asyncio.sleep(0.01)  # Ensure different timestamps

        # Get jobs
        response = await client.get("/api/v1/jobs")
        assert response.status_code == 200
        jobs = response.json()
        assert len(jobs) == 3

        # Should be newest first
        assert jobs[0]["id"] == str(job_ids[2])
        assert jobs[1]["id"] == str(job_ids[1])
        assert jobs[2]["id"] == str(job_ids[0])

    @pytest.mark.asyncio
    async def test_stream_job_status_quick_job(self, client: AsyncClient, app: FastAPI):
        """Test SSE streaming for quick job that completes immediately."""
        scheduler = app.state.scheduler

        async def quick_task():
            return "done"

        job_id = await scheduler.add_job(quick_task)
        await scheduler.wait(job_id)

        # Stream SSE events
        events = []
        async with client.stream("GET", f"/api/v1/jobs/{job_id}/$stream") as response:
            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
            assert response.headers["cache-control"] == "no-cache"

            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    import json

                    data = json.loads(line[6:])
                    events.append(data)

        # Should have at least one event with completed status
        assert len(events) >= 1
        assert events[-1]["status"] == "completed"
        assert events[-1]["id"] == str(job_id)

    @pytest.mark.asyncio
    async def test_stream_job_status_running_job(self, client: AsyncClient, app: FastAPI):
        """Test SSE streaming for running job with status transitions."""
        scheduler = app.state.scheduler

        async def slow_task():
            await asyncio.sleep(0.5)
            return "done"

        job_id = await scheduler.add_job(slow_task)

        # Stream SSE events
        events = []
        async with client.stream("GET", f"/api/v1/jobs/{job_id}/$stream?poll_interval=0.1") as response:
            assert response.status_code == 200

            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    import json

                    data = json.loads(line[6:])
                    events.append(data)
                    if data["status"] == "completed":
                        break

        # Should have multiple events showing status transitions
        assert len(events) >= 2
        statuses = [e["status"] for e in events]
        assert "running" in statuses or "pending" in statuses
        assert events[-1]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_stream_job_status_failed_job(self, client: AsyncClient, app: FastAPI):
        """Test SSE streaming for failed job."""
        scheduler = app.state.scheduler

        async def failing_task():
            raise ValueError("Task failed")

        job_id = await scheduler.add_job(failing_task)

        # Stream SSE events
        events = []
        async with client.stream("GET", f"/api/v1/jobs/{job_id}/$stream") as response:
            assert response.status_code == 200

            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    import json

                    data = json.loads(line[6:])
                    events.append(data)
                    if data["status"] == "failed":
                        break

        # Final event should show failed status with error
        assert events[-1]["status"] == "failed"
        assert events[-1]["error"] is not None
        assert "ValueError" in events[-1]["error"]

    @pytest.mark.asyncio
    async def test_stream_job_status_not_found(self, client: AsyncClient):
        """Test SSE streaming for non-existent job returns an RFC 9457 404."""
        fake_id = ULID()
        response = await client.get(f"/api/v1/jobs/{fake_id}/$stream")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["detail"] == f"Job with id {fake_id} not found"

    @pytest.mark.asyncio
    async def test_stream_job_status_invalid_ulid(self, client: AsyncClient):
        """Test SSE streaming with invalid ULID returns an RFC 9457 400."""
        response = await client.get("/api/v1/jobs/invalid-ulid/$stream")
        assert response.status_code == 400
        assert response.headers["content-type"].startswith("application/problem+json")
        body = response.json()
        assert body["detail"] == "Invalid job ID format: invalid-ulid"
        assert body["type"] == "urn:servicekit:error:invalid-ulid"

    @pytest.mark.asyncio
    async def test_stream_job_status_custom_poll_interval(self, client: AsyncClient, app: FastAPI):
        """Test SSE streaming with custom poll interval."""
        scheduler = app.state.scheduler

        async def slow_task():
            await asyncio.sleep(0.5)
            return "done"

        job_id = await scheduler.add_job(slow_task)

        # Stream with custom poll interval
        events = []
        async with client.stream("GET", f"/api/v1/jobs/{job_id}/$stream?poll_interval=0.2") as response:
            assert response.status_code == 200

            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    import json

                    data = json.loads(line[6:])
                    events.append(data)
                    if data["status"] == "completed":
                        break

        # Should have received events and completed
        assert len(events) >= 1
        assert events[-1]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_jobs_schema_endpoint(self, client: AsyncClient):
        """Test GET /api/v1/jobs/$schema returns JSON schema."""
        response = await client.get("/api/v1/jobs/$schema")
        assert response.status_code == 200
        schema = response.json()

        # Verify schema structure
        assert schema["type"] == "array"
        assert "items" in schema
        assert "$ref" in schema["items"]
        assert schema["items"]["$ref"] == "#/$defs/JobRecord"

        # Verify JobRecord definition exists
        assert "$defs" in schema
        assert "JobRecord" in schema["$defs"]

        # Verify JobRecord schema has required fields
        job_record_schema = schema["$defs"]["JobRecord"]
        assert job_record_schema["type"] == "object"
        assert "properties" in job_record_schema
        assert "id" in job_record_schema["properties"]
        assert "status" in job_record_schema["properties"]
        assert "submitted_at" in job_record_schema["properties"]

        # Verify required fields (only id is required, others have defaults)
        assert "required" in job_record_schema
        assert "id" in job_record_schema["required"]

    @pytest.mark.asyncio
    async def test_stream_job_status_rejects_non_positive_poll_interval(self, client: AsyncClient, app: FastAPI):
        """Test poll_interval must be greater than zero."""
        scheduler = app.state.scheduler

        async def quick_task():
            return "done"

        job_id = await scheduler.add_job(quick_task)
        await scheduler.wait(job_id)

        response = await client.get(f"/api/v1/jobs/{job_id}/$stream?poll_interval=0")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_stream_job_status_rejects_oversized_poll_interval(self, client: AsyncClient, app: FastAPI):
        """Test poll_interval is capped at 60 seconds."""
        scheduler = app.state.scheduler

        async def quick_task():
            return "done"

        job_id = await scheduler.add_job(quick_task)
        await scheduler.wait(job_id)

        response = await client.get(f"/api/v1/jobs/{job_id}/$stream?poll_interval=61")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_stream_job_status_bounded_read(self, client: AsyncClient, app: FastAPI):
        """Test a bounded SSE read collects several polled events and stops at the terminal one."""
        scheduler = app.state.scheduler
        release_task = asyncio.Event()

        async def long_task():
            await release_task.wait()
            return "done"

        async def release_after_delay() -> None:
            await asyncio.sleep(0.2)
            release_task.set()

        job_id = await scheduler.add_job(long_task)
        releaser = asyncio.create_task(release_after_delay())

        statuses: list[str] = []
        async with client.stream("GET", f"/api/v1/jobs/{job_id}/$stream?poll_interval=0.05") as response:
            assert response.status_code == 200

            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    statuses.append(json.loads(line[6:])["status"])
                    if statuses[-1] == "completed":
                        break

        await releaser
        assert len(statuses) >= 3
        assert statuses[-1] == "completed"

    @pytest.mark.asyncio
    async def test_stream_terminates_for_job_canceled_while_queued(self, client: AsyncClient, app: FastAPI):
        """Test the SSE stream reaches a terminal event for a job canceled before it started."""
        scheduler = app.state.scheduler
        await scheduler.set_max_concurrency(1)
        release_first = asyncio.Event()

        async def blocking_task():
            await release_first.wait()
            return "first"

        async def queued_task():
            return "second"

        first_id = await scheduler.add_job(blocking_task)
        await asyncio.sleep(0.01)
        queued_id = await scheduler.add_job(queued_task)
        await asyncio.sleep(0.01)

        assert await scheduler.cancel(queued_id) is True

        statuses: list[str] = []
        async with client.stream("GET", f"/api/v1/jobs/{queued_id}/$stream?poll_interval=0.05") as response:
            assert response.status_code == 200

            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    statuses.append(json.loads(line[6:])["status"])

        assert statuses[-1] == "canceled"

        release_first.set()
        await scheduler.wait(first_id)


class TestJobRouterIntegration:
    """Integration tests for job router with BaseServiceBuilder."""

    @pytest.mark.asyncio
    async def test_service_builder_with_jobs(self) -> None:
        """Test BaseServiceBuilder.with_jobs() creates functional job endpoints."""
        info = ServiceInfo(id="test-service", display_name="Test Service")
        app = BaseServiceBuilder(info=info).with_jobs(prefix="/jobs", tags=["background"]).build()

        # Trigger lifespan to initialize scheduler
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test", follow_redirects=True
            ) as client:
                # Check jobs endpoint exists
                response = await client.get("/jobs")
                assert response.status_code == 200
                assert response.json() == []

    @pytest.mark.asyncio
    async def test_create_scheduler_hook_receives_public_job_options(self) -> None:
        """Test that _create_scheduler can be overridden using the public JobOptions type."""
        received: list[JobOptions] = []

        class CustomSchedulerBuilder(BaseServiceBuilder):
            """Builder that records the job options passed to the scheduler hook."""

            def _create_scheduler(self, job_options: JobOptions) -> Scheduler:
                """Create the scheduler while recording its configuration."""
                received.append(job_options)
                return InMemoryScheduler(max_concurrency=job_options.max_concurrency)

        info = ServiceInfo(id="test-service", display_name="Test Service")
        app = CustomSchedulerBuilder(info=info).with_jobs(max_concurrency=3).build()

        async with app.router.lifespan_context(app):
            assert app.state.scheduler.max_concurrency == 3

        assert len(received) == 1
        assert received[0].max_concurrency == 3

    @pytest.mark.asyncio
    async def test_service_builder_with_max_concurrency(self) -> None:
        """Test BaseServiceBuilder.with_jobs(max_concurrency=N) configures scheduler."""
        info = ServiceInfo(id="test-service", display_name="Test Service")
        app = BaseServiceBuilder(info=info).with_jobs(max_concurrency=2).build()

        # Trigger lifespan to initialize scheduler
        async with app.router.lifespan_context(app):
            # Access scheduler via app.state
            scheduler = app.state.scheduler
            assert scheduler.max_concurrency == 2

    @pytest.mark.asyncio
    async def test_job_endpoints_in_openapi_schema(self) -> None:
        """Test job endpoints appear in OpenAPI schema."""
        info = ServiceInfo(id="test-service", display_name="Test Service")
        app = BaseServiceBuilder(info=info).with_jobs().build()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", follow_redirects=True
        ) as client:
            response = await client.get("/openapi.json")
            assert response.status_code == 200
            schema = response.json()

            # Check job endpoints exist in schema
            paths = schema["paths"]
            assert "/api/v1/jobs" in paths
            assert "/api/v1/jobs/{job_id}" in paths

            # Check tags at operation level
            jobs_list_tags = paths["/api/v1/jobs"]["get"]["tags"]
            assert "Jobs" in jobs_list_tags


def test_job_options_alias_is_backwards_compatible() -> None:
    """Test that the previously private _JobOptions name still resolves to JobOptions."""
    from servicekit.api.service_builder import _JobOptions

    assert _JobOptions is JobOptions
